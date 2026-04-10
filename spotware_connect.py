# spotware_connect.py
import logging
import requests
import time

from twisted.internet import reactor
from twisted.internet.defer import Deferred

from ctrader_open_api.client import Client as SpotwareClientBase
from ctrader_open_api.tcpProtocol import TcpProtocol
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq,
    ProtoOAAccountAuthReq,
    ProtoOAAccountAuthRes,
    ProtoOASymbolsListReq,
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
        if event not in self._events: self._events[event] = []
        self._events[event].append(func)
    def emit(self, event, *args, **kwargs):
        if event in self._events:
            for func in self._events[event]:
                reactor.callFromThread(func, *args, **kwargs)

class SpotwareConnect(EventEmitter):
    def __init__(self, client_id, client_secret):
        super().__init__()
        self.host = "demo.ctraderapi.com"
        self.port = 5035
        self._client_id = client_id
        self._client_secret = client_secret
        self.is_authorized = False
        
        self._client = SpotwareClientBase(self.host, self.port, TcpProtocol)
        self._client.setConnectedCallback(self._on_connected)
        self._client.setMessageReceivedCallback(self._on_message_received)
        self._client.setDisconnectedCallback(self._on_disconnected)
        self._client.account_id = None

    def start(self):
        self._client.startService()

    def stop(self):
        self.is_authorized = False
        try:
            stop_method = getattr(self._client, "stopService", None)
            if callable(stop_method): stop_method()
        except: pass

    def send(self, message):
        return self._client.send(message)

    def _on_connected(self, client):
        logger.info("Connected to cTrader. Waiting 2s before App Auth...")
        # ПАУЗА 1: Щоб сервер нас не забанив на старті
        reactor.callLater(2.0, self._send_app_auth)

    def _send_app_auth(self):
        logger.info("Step 1: Sending Application Auth...")
        req = ProtoOAApplicationAuthReq(clientId=self._client_id, clientSecret=self._client_secret)
        self._client.send(req)

    def _on_message_received(self, client, message: ProtoMessage):
        pt = message.payloadType

        if pt == ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_RES:
            logger.info("Step 1 OK. Waiting 2s before Account Auth...")
            # ПАУЗА 2: Між авторизацією додатка та акаунта
            reactor.callLater(2.0, self._authorize_account)

        elif pt == ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES:
            res = ProtoOAAccountAuthRes()
            res.ParseFromString(message.payload)
            self._client.account_id = res.ctidTraderAccountId
            self.is_authorized = True
            logger.info(f"✅ Step 2 OK. Account {res.ctidTraderAccountId} authorized.")
            self.emit("ready")

        elif pt == ProtoOAPayloadType.PROTO_OA_ERROR_RES:
            res = ProtoOAErrorRes()
            res.ParseFromString(message.payload)
            
            if res.errorCode == "ALREADY_LOGGED_IN":
                logger.info("Account already authorized. Marking as ready.")
                self.is_authorized = True
                self.emit("ready")
                return

            if res.errorCode == "BLOCKED_PAYLOAD_TYPE":
                logger.critical("🚨 cTrader RATE LIMIT! Зупиняємося на 5 хвилин.")
                self.emit("error", "RATE_LIMIT_BLOCKED")
                return

            logger.error(f"API Error: {res.errorCode} - {res.description}")
            self.emit("error", res.errorCode)

        elif pt == ProtoOAPayloadType.PROTO_OA_SPOT_EVENT:
            spot_event = ProtoOASpotEvent()
            spot_event.ParseFromString(message.payload)
            self.emit("spot_event", spot_event)

    def _authorize_account(self):
        acc_id = get_demo_account_id()
        token = app_state.access_token
        if not acc_id or not token:
            logger.error("Missing Account ID or Token")
            return
        req = ProtoOAAccountAuthReq(ctidTraderAccountId=acc_id, accessToken=token)
        self._client.send(req)

    def get_all_symbols(self):
        if not getattr(self._client, "account_id", None):
            d = Deferred()
            d.errback(Exception("No Account ID"))
            return d
        req = ProtoOASymbolsListReq(ctidTraderAccountId=self._client.account_id)
        return self._client.send(req)