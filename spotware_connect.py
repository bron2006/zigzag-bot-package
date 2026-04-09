import logging
import requests
from twisted.internet import reactor
from twisted.internet.defer import Deferred, TimeoutError
from ctrader_open_api.client import Client as SpotwareClientBase
from ctrader_open_api.tcpProtocol import TcpProtocol
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq,
    ProtoOAAccountAuthReq,
    ProtoOAAccountAuthRes,
    ProtoOASymbolsListReq,
    ProtoOASymbolsListRes,
    ProtoOAErrorRes,
    ProtoOASpotEvent,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAPayloadType
from config import get_demo_account_id, get_ctrader_refresh_token
from state import app_state

logger = logging.getLogger(__name__)

TOKEN_REFRESH_URL = "https://connect.spotware.com/apps/token"


class EventEmitter:
    def __init__(self):
        self._events = {}

    def on(self, event, func):
        if event not in self._events:
            self._events[event] = []
        self._events[event].append(func)

    def emit(self, event, *args, **kwargs):
        if event in self._events:
            for func in self._events[event]:
                reactor.callFromThread(func, *args, **kwargs)

    def remove_listener(self, event, func):
        if event in self._events and func in self._events[event]:
            self._events[event].remove(func)


class SpotwareConnect(EventEmitter):
    def __init__(self, client_id, client_secret):
        super().__init__()
        self.host = "demo.ctraderapi.com"
        self.port = 5035
        self._client_id = client_id
        self._client_secret = client_secret
        self.is_authorized = False
        self.is_refreshing_token = False

        self._client = SpotwareClientBase(self.host, self.port, TcpProtocol)
        self._client.setConnectedCallback(self._on_connected)
        self._client.setMessageReceivedCallback(self._on_message_received)
        self._client.setDisconnectedCallback(self._on_disconnected)
        self._client.account_id = None

        self.symbol_map = {}

    def start(self):
        self._client.startService()

    def stop(self):
        try:
            self.is_authorized = False
            stop_method = getattr(self._client, "stopService", None)
            if callable(stop_method):
                stop_method()
        except Exception:
            logger.exception("Failed to stop Spotware client")

    def send(self, message, client_msg_id=None, timeout=30):
        deferred = self._client.send(message, clientMsgId=client_msg_id)
        timeout_deferred = Deferred()

        timeout_call = reactor.callLater(
            timeout,
            lambda: deferred.cancel() if not deferred.called else None
        )

        def on_success(result):
            if timeout_call.active():
                timeout_call.cancel()
            if not timeout_deferred.called:
                timeout_deferred.callback(result)
            return None

        def on_error(failure):
            if timeout_call.active():
                timeout_call.cancel()
            if not timeout_deferred.called:
                if failure.check(TimeoutError):
                    err_msg = f"Таймаут ({timeout}s) для {type(message).__name__}"
                    logger.error(err_msg)
                    timeout_deferred.errback(Exception(err_msg))
                else:
                    timeout_deferred.errback(failure)
            # КРИТИЧНО: не повертаємо failure далі, щоб не було Unhandled error in Deferred
            return None

        deferred.addCallbacks(on_success, on_error)
        return timeout_deferred

    def _refresh_access_token(self):
        if self.is_refreshing_token:
            logger.info("Token refresh already in progress.")
            return

        self.is_refreshing_token = True
        logger.info("Attempting to refresh access token...")

        refresh_token = get_ctrader_refresh_token()
        if not refresh_token:
            logger.error("CRITICAL: CTRADER_REFRESH_TOKEN is not set. Cannot refresh.")
            self.is_refreshing_token = False
            return

        params = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }

        try:
            response = requests.post(TOKEN_REFRESH_URL, data=params, timeout=20)
            response.raise_for_status()
            data = response.json()

            new_access_token = data.get("accessToken")
            if not new_access_token:
                logger.error(f"Failed to refresh: 'accessToken' missing. Response: {data}")
                raise Exception("Response is missing 'accessToken'")

            app_state.access_token = new_access_token
            logger.info("✅ Access token has been successfully refreshed.")

            self._authorize_account()

        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP error during token refresh: {e}")
            if getattr(e, "response", None) is not None:
                logger.error(f"cTrader response content: {e.response.text}")
        except Exception as e:
            logger.error(f"Failed to parse refresh token response: {e}")
        finally:
            self.is_refreshing_token = False

    def _on_connected(self, client):
        logger.info("Connection successful. Authorizing application...")
        self.send(
            ProtoOAApplicationAuthReq(
                clientId=self._client_id,
                clientSecret=self._client_secret,
            ),
            timeout=20,
        )

    def _on_disconnected(self, client, reason):
        self.is_authorized = False
        try:
            msg = reason.getErrorMessage()
        except Exception:
            msg = str(reason)

        logger.warning(f"Disconnected. Reason: {msg}")
        self.emit("error", f"Disconnected: {msg}")

    def _on_message_received(self, client, message: ProtoMessage):
        pt = message.payloadType

        if pt == ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_RES:
            logger.info("Application authorized. Authorizing account...")
            self._authorize_account()
            return

        elif pt == ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES:
            res = ProtoOAAccountAuthRes()
            res.ParseFromString(message.payload)

            self._client.account_id = res.ctidTraderAccountId
            self.is_authorized = True

            logger.info(f"✅ Account {res.ctidTraderAccountId} authorized.")

            self.get_all_symbols().addCallback(self._on_symbols_list)
            self.emit("ready")
            return

        elif pt == ProtoOAPayloadType.PROTO_OA_ERROR_RES:
            res = ProtoOAErrorRes()
            res.ParseFromString(message.payload)

            logger.error(f"API Error: {res.errorCode} - {res.description}")

            # ГОЛОВНИЙ ФІКС:
            # Якщо Open API app already authorized — просто йдемо далі до account auth
            if res.errorCode == "ALREADY_LOGGED_IN":
                logger.warning("Open API application is already authorized. Proceeding to account auth.")
                if not self.is_authorized:
                    self._authorize_account()
                return

            if res.errorCode == "CH_ACCESS_TOKEN_INVALID" or (
                res.errorCode == "INVALID_REQUEST"
                and "Trading account is not authorized" in res.description
            ):
                self._refresh_access_token()
                return

            self.emit("error", f"API Error: {res.errorCode} - {res.description}")
            return

        elif pt == ProtoOAPayloadType.PROTO_OA_SPOT_EVENT:
            spot_event = ProtoOASpotEvent()
            spot_event.ParseFromString(message.payload)

            self.emit("spot_event", spot_event)
            self.emit(f"spot_event_{spot_event.symbolId}", spot_event)
            return

    def _authorize_account(self):
        acc_id = get_demo_account_id()
        token = app_state.access_token

        logger.info(f"Authorizing account ID: {acc_id}...")
        if not acc_id or not token:
            logger.error("CRITICAL: Account ID or Access Token is missing.")
            return

        self.send(
            ProtoOAAccountAuthReq(
                ctidTraderAccountId=acc_id,
                accessToken=token
            ),
            timeout=20,
        )

    def get_all_symbols(self):
        logger.info("Requesting light symbol list...")
        return self.send(
            ProtoOASymbolsListReq(
                ctidTraderAccountId=self._client.account_id
            ),
            timeout=30,
        )

    def _on_symbols_list(self, message: ProtoMessage):
        res = ProtoOASymbolsListRes()
        res.ParseFromString(message.payload)

        for symbol in res.symbol:
            self.symbol_map[symbol.symbolName] = symbol.symbolId

        logger.info(f"Loaded {len(self.symbol_map)} symbols from cTrader.")

    def subscribe_ticks(self, symbol_name, callback):
        if symbol_name not in self.symbol_map:
            logger.error(f"Symbol {symbol_name} not found in cTrader symbol list.")
            return

        symbol_id = self.symbol_map[symbol_name]

        def handler(event: ProtoOASpotEvent):
            callback(symbol_name, event)

        self.on(f"spot_event_{symbol_id}", handler)
        logger.info(f"Subscribed to ticks for {symbol_name} (ID {symbol_id})")