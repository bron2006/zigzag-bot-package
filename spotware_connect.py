import logging
import threading
from typing import Any, Callable, Dict, List, Optional

import requests
from twisted.internet import reactor
from twisted.internet.defer import Deferred, TimeoutError
from twisted.internet.threads import deferToThreadPool
from twisted.python.failure import Failure

from config import (
    get_ctrader_access_token,
    get_ctrader_refresh_token,
    get_demo_account_id,
)
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

_ACCOUNT_AUTH_TIMEOUT = 12
_MAX_ACCOUNT_AUTH_ATTEMPTS = 3


def _blocking_pool():
    return app_state.blocking_pool or reactor.getThreadPool()


def _mask_secret(value: Optional[str], head: int = 6, tail: int = 4) -> str:
    if not value:
        return "<empty>"
    if len(value) <= head + tail:
        return "*" * len(value)
    return f"{value[:head]}...{value[-tail:]}"


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

        self._application_authed = False
        self._account_auth_watchdog = None
        self._account_auth_attempts = 0

        self._client = SpotwareClientBase(self.host, self.port, TcpProtocol)
        self._client.setConnectedCallback(self._on_connected)
        self._client.setMessageReceivedCallback(self._on_message_received)
        self._client.setDisconnectedCallback(self._on_disconnected)
        self._client.account_id = None

        self.symbol_map: Dict[str, int] = {}

        if not app_state.access_token:
            app_state.access_token = get_ctrader_access_token()

        logger.info(
            "SpotwareConnect init: host=%s port=%s client_id=%s account_id=%s access_token=%s refresh_token=%s",
            self.host,
            self.port,
            _mask_secret(self._client_id),
            get_demo_account_id(),
            _mask_secret(app_state.access_token),
            _mask_secret(get_ctrader_refresh_token()),
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        logger.info("Запуск Spotware client service...")
        self._client.startService()

    def stop(self) -> None:
        logger.info("Зупинка Spotware client service...")
        self._cancel_account_auth_watchdog()
        try:
            self.is_authorized = False
            self._application_authed = False
            stop_method = getattr(self._client, "stopService", None)
            if callable(stop_method):
                stop_method()
        except Exception:
            logger.exception("Не вдалося зупинити Spotware client")

    # ------------------------------------------------------------------
    # Low-level send
    # ------------------------------------------------------------------

    def send(self, message, client_msg_id=None, timeout: int = 30) -> Deferred:
        base_d = self._client.send(message, clientMsgId=client_msg_id)
        result_d: Deferred = Deferred()

        msg_name = type(message).__name__

        def _on_timeout():
            if result_d.called:
                return

            logger.error("Таймаут send(%s) після %ss", msg_name, timeout)

            try:
                if not base_d.called:
                    base_d.cancel()
            except Exception:
                logger.exception("Не вдалося cancel base deferred для %s", msg_name)

            result_d.errback(Failure(TimeoutError(f"Таймаут ({timeout}s) для {msg_name}")))

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

    # ------------------------------------------------------------------
    # Connection callbacks
    # ------------------------------------------------------------------

    def _on_connected(self, client) -> None:
        logger.info(
            "TCP connection established. Sending ProtoOAApplicationAuthReq with client_id=%s",
            _mask_secret(self._client_id),
        )

        self.is_authorized = False
        self._application_authed = False
        self._account_auth_attempts = 0
        self._cancel_account_auth_watchdog()

        self.send(
            ProtoOAApplicationAuthReq(
                clientId=self._client_id,
                clientSecret=self._client_secret,
            ),
            timeout=15,
        ).addErrback(self._on_application_auth_send_error)

    def _on_disconnected(self, client, reason) -> None:
        self.is_authorized = False
        self._application_authed = False
        self._cancel_account_auth_watchdog()

        msg = self._reason_to_text(reason)
        logger.warning("Disconnected. Reason: %s", msg)
        self.emit("error", f"Disconnected: {msg}")

    def _on_message_received(self, client, message: ProtoMessage) -> None:
        pt = message.payloadType
        logger.debug("Incoming payloadType=%s", pt)

        if pt == ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_RES:
            self._application_authed = True
            logger.info("✅ Application authorized successfully.")
            self._send_account_auth("after_application_auth_res")
            return

        if pt == ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES:
            res = ProtoOAAccountAuthRes()
            res.ParseFromString(message.payload)

            self._client.account_id = res.ctidTraderAccountId
            self.is_authorized = True
            self._account_auth_attempts = 0
            self._cancel_account_auth_watchdog()

            logger.info(
                "✅ Account authorized successfully. ctidTraderAccountId=%s",
                res.ctidTraderAccountId,
            )
            self.emit("ready")
            return

        if pt == ProtoOAPayloadType.PROTO_OA_ERROR_RES:
            res = ProtoOAErrorRes()
            res.ParseFromString(message.payload)

            error_code = str(res.errorCode)
            description = str(res.description)

            logger.error("API Error: errorCode=%s description=%s", error_code, description)

            if self._should_refresh_token(error_code, description):
                self._refresh_access_token(reason=f"{error_code}: {description}")
            elif self._looks_like_account_auth_problem(error_code, description):
                logger.warning("Схоже на account auth проблему — запускаю refresh + retry")
                self._refresh_access_token(reason=f"account_auth_problem: {error_code}: {description}")
            else:
                logger.warning(
                    "Помилка API не тригерить refresh token. errorCode=%s description=%s",
                    error_code,
                    description,
                )
            return

        if pt == ProtoOAPayloadType.PROTO_OA_SPOT_EVENT:
            spot_event = ProtoOASpotEvent()
            spot_event.ParseFromString(message.payload)
            self.emit("spot_event", spot_event)
            self.emit(f"spot_event_{spot_event.symbolId}", spot_event)
            return

    # ------------------------------------------------------------------
    # Application / account auth
    # ------------------------------------------------------------------

    def _send_account_auth(self, source: str) -> None:
        acc_id = get_demo_account_id()
        token = app_state.access_token or get_ctrader_access_token()

        logger.info(
            "Починаю account auth. source=%s attempt=%s app_authed=%s acc_id=%s token=%s refresh=%s",
            source,
            self._account_auth_attempts + 1,
            self._application_authed,
            acc_id,
            _mask_secret(token),
            _mask_secret(get_ctrader_refresh_token()),
        )

        if not self._application_authed:
            logger.warning("Application auth ще не завершився — account auth не відправлено")
            return

        if not acc_id:
            msg = "DEMO_ACCOUNT_ID відсутній або не зчитався з env"
            logger.error(msg)
            self.emit("error", msg)
            return

        if not token:
            logger.warning("Access token відсутній — запускаю refresh перед account auth")
            self._refresh_access_token(reason="missing_access_token")
            return

        self._account_auth_attempts += 1
        self._cancel_account_auth_watchdog()

        try:
            self.send(
                ProtoOAAccountAuthReq(
                    ctidTraderAccountId=acc_id,
                    accessToken=token,
                ),
                timeout=20,
            ).addCallbacks(
                self._on_account_auth_send_ok,
                self._on_account_auth_send_error,
            )
            self._schedule_account_auth_watchdog()
        except Exception:
            logger.exception("Виняток під час send(ProtoOAAccountAuthReq)")
            self._refresh_access_token(reason="account_auth_send_exception")

    def _schedule_account_auth_watchdog(self) -> None:
        self._cancel_account_auth_watchdog()
        self._account_auth_watchdog = reactor.callLater(
            _ACCOUNT_AUTH_TIMEOUT,
            self._on_account_auth_watchdog_timeout,
        )
        logger.info("Account auth watchdog запущено на %ss", _ACCOUNT_AUTH_TIMEOUT)

    def _cancel_account_auth_watchdog(self) -> None:
        if self._account_auth_watchdog and self._account_auth_watchdog.active():
            try:
                self._account_auth_watchdog.cancel()
            except Exception:
                logger.exception("Не вдалося скасувати account auth watchdog")
        self._account_auth_watchdog = None

    def _on_account_auth_watchdog_timeout(self) -> None:
        self._account_auth_watchdog = None

        if self.is_authorized:
            return

        logger.warning(
            "Account auth watchdog timeout. account_id=%s attempts=%s",
            self._client.account_id,
            self._account_auth_attempts,
        )

        if self._account_auth_attempts < _MAX_ACCOUNT_AUTH_ATTEMPTS:
            logger.warning("Повторюю account auth після watchdog timeout")
            self._send_account_auth("watchdog_retry")
        else:
            logger.warning(
                "Вичерпано локальні account auth спроби — пробую refresh token"
            )
            self._refresh_access_token(reason="account_auth_watchdog_timeout")

    def _on_application_auth_send_error(self, failure):
        logger.error("Application auth send failed: %s", failure.getErrorMessage())
        self.emit("error", f"Application auth send failed: {failure.getErrorMessage()}")
        return failure

    def _on_account_auth_send_ok(self, result):
        logger.info("ProtoOAAccountAuthReq відправлено. Очікую ProtoOAAccountAuthRes...")
        return result

    def _on_account_auth_send_error(self, failure):
        msg = failure.getErrorMessage()
        logger.error("Account auth send failed: %s", msg)

        if "Таймаут" in msg or "Timeout" in msg or "timed out" in msg.lower():
            logger.warning("Account auth send timeout — запускаю refresh token")
            self._refresh_access_token(reason=f"account_auth_send_timeout: {msg}")
        else:
            self.emit("error", f"Account auth send failed: {msg}")

        return failure

    # ------------------------------------------------------------------
    # Token refresh
    # ------------------------------------------------------------------

    def _refresh_access_token(self, reason: str = "unknown") -> None:
        with self._refresh_lock:
            if self.is_refreshing_token:
                logger.info("Token refresh already in progress. reason=%s", reason)
                return
            self.is_refreshing_token = True

        logger.warning(
            "Запускаю refresh access token. reason=%s refresh_token=%s",
            reason,
            _mask_secret(get_ctrader_refresh_token()),
        )

        d = deferToThreadPool(
            reactor,
            _blocking_pool(),
            self._refresh_access_token_sync,
        )

        def _done(result):
            self.is_refreshing_token = False

            if not result:
                logger.error("Refresh token завершився без результату")
                self.emit("error", "Refresh token failed: empty response")
                return None

            new_access_token = (
                result.get("accessToken")
                or result.get("access_token")
            )
            new_refresh_token = (
                result.get("refreshToken")
                or result.get("refresh_token")
            )

            if not new_access_token:
                logger.error("Refresh token response без accessToken/access_token: %s", result)
                self.emit("error", "Refresh token failed: no access token in response")
                return None

            app_state.access_token = new_access_token

            logger.info(
                "✅ Access token оновлено: access=%s refresh=%s",
                _mask_secret(new_access_token),
                _mask_secret(new_refresh_token or get_ctrader_refresh_token()),
            )

            reactor.callLater(0, self._send_account_auth, "after_refresh")
            return result

        def _failed(failure):
            self.is_refreshing_token = False
            logger.error("Refresh token request failed: %s", failure.getErrorMessage())
            self.emit("error", f"Refresh token failed: {failure.getErrorMessage()}")
            return None

        d.addCallbacks(_done, _failed)

    def _refresh_access_token_sync(self) -> Optional[dict]:
        refresh_token = get_ctrader_refresh_token()
        if not refresh_token:
            raise RuntimeError("CTRADER_REFRESH_TOKEN is not set")

        params = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }

        response = requests.post(TOKEN_REFRESH_URL, data=params, timeout=20)
        response.raise_for_status()
        data = response.json()

        logger.info("Refresh token HTTP OK. Keys: %s", sorted(list(data.keys())))
        return data

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_all_symbols(self) -> Deferred:
        logger.info("Requesting symbol list for account_id=%s", self._client.account_id)
        return self.send(
            ProtoOASymbolsListReq(
                ctidTraderAccountId=self._client.account_id,
            ),
            timeout=30,
        )

    def subscribe_ticks(self, symbol_name: str, callback: Callable) -> None:
        if symbol_name not in self.symbol_map:
            logger.error("Symbol %s not found in cTrader symbol map.", symbol_name)
            return

        symbol_id = self.symbol_map[symbol_name]

        def handler(event: ProtoOASpotEvent):
            callback(symbol_name, event)

        self.on(f"spot_event_{symbol_id}", handler)
        logger.info("Subscribed to ticks for %s (ID %s)", symbol_name, symbol_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _reason_to_text(reason: Any) -> str:
        try:
            if hasattr(reason, "getErrorMessage"):
                return reason.getErrorMessage()
            return str(reason)
        except Exception:
            return "unknown disconnect reason"

    @staticmethod
    def _should_refresh_token(error_code: str, description: str) -> bool:
        desc = (description or "").lower()
        code = (error_code or "").upper()

        if code in {
            "CH_ACCESS_TOKEN_INVALID",
            "CH_ACCESS_TOKEN_EXPIRED",
            "CH_ACCOUNT_AUTH_TOKEN_INVALID",
        }:
            return True

        if code == "INVALID_REQUEST" and "trading account is not authorized" in desc:
            return True

        if "access token" in desc and ("invalid" in desc or "expired" in desc):
            return True

        return False

    @staticmethod
    def _looks_like_account_auth_problem(error_code: str, description: str) -> bool:
        desc = (description or "").lower()
        code = (error_code or "").upper()

        suspicious = [
            "not authorized",
            "account is not authorized",
            "trader account",
            "ctidtraderaccountid",
            "token",
            "authorization",
        ]

        if code in {
            "INVALID_REQUEST",
            "UNSUPPORTED_OPERATION",
            "TRADING_ACCOUNT_NOT_AUTHORIZED",
        }:
            return True

        return any(fragment in desc for fragment in suspicious)