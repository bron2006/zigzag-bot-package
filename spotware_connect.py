import logging
import threading
from typing import Any, Callable, Dict, List, Optional

import requests
from twisted.internet import defer, reactor
from twisted.internet.defer import Deferred, TimeoutError
from twisted.internet.threads import deferToThreadPool
from twisted.python.failure import Failure

from config import get_ctrader_refresh_token, get_demo_account_id
from ctrader_open_api.client import Client as SpotwareClientBase
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAAccountAuthReq,
    ProtoOAAccountAuthRes,
    ProtoOAApplicationAuthReq,
    ProtoOAErrorRes,
    ProtoOASpotEvent,
    ProtoOASymbolsListReq,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAPayloadType
from ctrader_open_api.tcpProtocol import TcpProtocol
from state import app_state

logger = logging.getLogger(__name__)

TOKEN_REFRESH_URL = "https://connect.spotware.com/apps/token"


def _blocking_pool():
    return app_state.blocking_pool or reactor.getThreadPool()


class EventEmitter:
    def __init__(self):
        self._events: Dict[str, List[Callable]] = {}
        self._events_lock = threading.RLock()

    def on(self, event: str, func: Callable) -> None:
        with self._events_lock:
            self._events.setdefault(event, []).append(func)

    def remove_listener(self, event: str, func: Callable) -> None:
        with self._events_lock:
            if event in self._events and func in self._events[event]:
                self._events[event].remove(func)

    def emit(self, event: str, *args, **kwargs) -> None:
        with self._events_lock:
            listeners = list(self._events.get(event, []))

        for func in listeners:
            try:
                reactor.callFromThread(func, *args, **kwargs)
            except Exception:
                logger.exception(f"Не вдалося емітити event '{event}'")


class SpotwareConnect(EventEmitter):
    def __init__(self, client_id: str, client_secret: str):
        super().__init__()
        self.host = "demo.ctraderapi.com"
        self.port = 5035

        self._client_id = client_id
        self._client_secret = client_secret

        self.is_authorized = False
        self.is_refreshing_token = False
        self._refresh_lock = threading.Lock()

        self._client = SpotwareClientBase(self.host, self.port, TcpProtocol)
        self._client.setConnectedCallback(self._on_connected)
        self._client.setMessageReceivedCallback(self._on_message_received)
        self._client.setDisconnectedCallback(self._on_disconnected)
        self._client.account_id = None

        self.symbol_map: Dict[str, int] = {}

    def start(self) -> None:
        logger.info("Запуск Spotware client service...")
        self._client.startService()

    def stop(self) -> None:
        logger.info("Зупинка Spotware client service...")
        try:
            self.is_authorized = False
            stop_method = getattr(self._client, "stopService", None)
            if callable(stop_method):
                stop_method()
        except Exception:
            logger.exception("Не вдалося зупинити Spotware client")

    def send(self, message, client_msg_id=None, timeout: int = 30) -> Deferred:
        base_d = self._client.send(message, clientMsgId=client_msg_id)
        result_d: Deferred = Deferred()

        def _on_timeout():
            if result_d.called:
                return
            err = Failure(TimeoutError(f"Таймаут ({timeout}s) для {type(message).__name__}"))
            try:
                if not base_d.called:
                    base_d.cancel()
            except Exception:
                logger.exception("Не вдалося скасувати base deferred після таймауту")
            result_d.errback(err)

        timeout_call = reactor.callLater(timeout, _on_timeout)

        def _finish_success(result):
            if timeout_call.active():
                timeout_call.cancel()
            if not result_d.called:
                result_d.callback(result)
            return result

        def _finish_error(failure):
            if timeout_call.active():
                timeout_call.cancel()
            if not result_d.called:
                result_d.errback(failure)
            return failure

        base_d.addCallbacks(_finish_success, _finish_error)
        return result_d

    def _refresh_access_token(self) -> None:
        with self._refresh_lock:
            if self.is_refreshing_token:
                logger.info("Token refresh already in progress.")
                return
            self.is_refreshing_token = True

        logger.info("Attempting to refresh access token asynchronously...")

        d = deferToThreadPool(
            reactor,
            _blocking_pool(),
            self._refresh_access_token_sync,
        )

        def _done(result):
            self.is_refreshing_token = False
            if not result:
                logger.error("Token refresh failed: empty result")
                return None

            new_access_token = result.get("accessToken")
            if not new_access_token:
                logger.error(f"Token refresh response missing accessToken: {result}")
                return None

            app_state.access_token = new_access_token
            logger.info("✅ Access token has been successfully refreshed.")
            reactor.callLater(0, self._authorize_account)
            return result

        def _failed(failure):
            self.is_refreshing_token = False
            logger.error(f"Refresh token request failed: {failure.getErrorMessage()}")
            return None

        d.addCallbacks(_done, _failed)

    def _refresh_access_token_sync(self) -> Optional[dict]:
        refresh_token = get_ctrader_refresh_token()
        if not refresh_token:
            logger.error("CRITICAL: CTRADER_REFRESH_TOKEN is not set. Cannot refresh.")
            return None

        params = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }

        response = requests.post(TOKEN_REFRESH_URL, data=params, timeout=20)
        response.raise_for_status()
        return response.json()

    def _on_connected(self, client) -> None:
        logger.info("Connection successful. Authorizing application...")
        self.send(
            ProtoOAApplicationAuthReq(
                clientId=self._client_id,
                clientSecret=self._client_secret,
            )
        ).addErrback(self._log_send_error, "application_auth")

    def _on_disconnected(self, client, reason) -> None:
        self.is_authorized = False
        msg = self._reason_to_text(reason)
        logger.warning(f"Disconnected. Reason: {msg}")
        self.emit("error", f"Disconnected: {msg}")

    def _on_message_received(self, client, message: ProtoMessage) -> None:
        pt = message.payloadType

        if pt == ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_RES:
            logger.info("Application authorized. Authorizing account...")
            self._authorize_account()
            return

        if pt == ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES:
            res = ProtoOAAccountAuthRes()
            res.ParseFromString(message.payload)
            self._client.account_id = res.ctidTraderAccountId
            self.is_authorized = True
            logger.info(f"✅ Account {res.ctidTraderAccountId} authorized.")
            self.emit("ready")
            return

        if pt == ProtoOAPayloadType.PROTO_OA_ERROR_RES:
            res = ProtoOAErrorRes()
            res.ParseFromString(message.payload)
            logger.error(f"API Error: {res.errorCode} - {res.description}")

            if res.errorCode == "CH_ACCESS_TOKEN_INVALID" or (
                res.errorCode == "INVALID_REQUEST"
                and "Trading account is not authorized" in res.description
            ):
                self._refresh_access_token()
            return

        if pt == ProtoOAPayloadType.PROTO_OA_SPOT_EVENT:
            spot_event = ProtoOASpotEvent()
            spot_event.ParseFromString(message.payload)
            self.emit("spot_event", spot_event)
            self.emit(f"spot_event_{spot_event.symbolId}", spot_event)
            return

    def _authorize_account(self) -> None:
        acc_id = get_demo_account_id()
        token = app_state.access_token

        logger.info(f"Authorizing account ID: {acc_id}...")
        if not acc_id or not token:
            logger.error("CRITICAL: Account ID or Access Token is missing.")
            return

        self.send(
            ProtoOAAccountAuthReq(
                ctidTraderAccountId=acc_id,
                accessToken=token,
            )
        ).addErrback(self._log_send_error, "account_auth")

    def get_all_symbols(self) -> Deferred:
        logger.info("Requesting symbol list...")
        return self.send(
            ProtoOASymbolsListReq(
                ctidTraderAccountId=self._client.account_id,
            ),
            timeout=30,
        )

    def subscribe_ticks(self, symbol_name: str, callback: Callable) -> None:
        if symbol_name not in self.symbol_map:
            logger.error(f"Symbol {symbol_name} not found in cTrader symbol list.")
            return

        symbol_id = self.symbol_map[symbol_name]

        def handler(event: ProtoOASpotEvent):
            callback(symbol_name, event)

        self.on(f"spot_event_{symbol_id}", handler)
        logger.info(f"Subscribed to ticks for {symbol_name} (ID {symbol_id})")

    @staticmethod
    def _reason_to_text(reason: Any) -> str:
        try:
            if hasattr(reason, "getErrorMessage"):
                return reason.getErrorMessage()
            return str(reason)
        except Exception:
            return "unknown disconnect reason"

    @staticmethod
    def _log_send_error(failure, context: str):
        logger.error(f"Send error [{context}]: {failure.getErrorMessage()}")
        return failure