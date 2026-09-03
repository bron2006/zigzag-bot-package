# spotware_connect.py
import logging

from twisted.internet import reactor
from twisted.internet.defer import Deferred
from twisted.internet.threads import deferToThread

from ctrader_open_api.auth import Auth as CTraderAuth
from ctrader_open_api.client import Client as SpotwareClientBase
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAAccountAuthReq,
    ProtoOAAccountAuthRes,
    ProtoOAAccountsTokenInvalidatedEvent,
    ProtoOAApplicationAuthReq,
    ProtoOAErrorRes,
    ProtoOAExecutionEvent,
    ProtoOAGetAccountListByAccessTokenReq,
    ProtoOAGetAccountListByAccessTokenRes,
    ProtoOASpotEvent,
    ProtoOASymbolsListReq,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAPayloadType
from ctrader_open_api.tcpProtocol import TcpProtocol

from config import (
    SPOTWARE_MAX_PENDING_DATA_REQUESTS,
    get_ctrader_proto_hosts,
    get_ctrader_proto_port,
    get_demo_account_id,
)
from state import app_state

logger = logging.getLogger(__name__)


class EventEmitter:
    def __init__(self):
        self._events = {}

    def on(self, event, func):
        self._events.setdefault(event, []).append(func)

    def emit(self, event, *args, **kwargs):
        handlers = list(self._events.get(event, []))

        def _run_handler(handler):
            try:
                handler(*args, **kwargs)
            except Exception:
                logger.exception("Event handler failed for '%s'", event)

        for handler in handlers:
            reactor.callFromThread(_run_handler, handler)


class SpotwareConnect(EventEmitter):
    # AUDIT FIX (2026-08-17, critical): these three ARE the auth handshake
    # itself (app auth -> account list -> account auth) and must always go
    # out immediately, even before self.is_authorized - everything else
    # gets queued by send() until authorization is confirmed. See send()'s
    # own comment for the incident this addresses.
    _AUTH_HANDSHAKE_TYPES = (
        ProtoOAApplicationAuthReq,
        ProtoOAGetAccountListByAccessTokenReq,
        ProtoOAAccountAuthReq,
    )

    def __init__(self, client_id, client_secret):
        super().__init__()

        self._host_candidates = get_ctrader_proto_hosts()
        self._host_index = 0
        self.host = self._host_candidates[self._host_index]
        self.port = get_ctrader_proto_port()
        self._client_id = client_id
        self._client_secret = client_secret
        self.is_authorized = False
        self._stopping = False
        self._switching_host = False
        self._refresh_in_progress = False
        self._app_auth_completed = False
        self._oauth_client = CTraderAuth(client_id or "", client_secret or "", "")
        # AUDIT FIX (2026-08-17, critical, live finding): ProtoOAGetTrendbarsReq
        # (and other data requests) were observed going out before
        # ProtoOAAccountAuthRes confirmed the account was authorized,
        # getting rejected by cTrader with "Trading account is not
        # authorized" - 0 bars back, every pair falls to WAIT. Callers
        # (analysis.py, ctrader.py) already check client.account_id before
        # sending, but that's a scattered, per-caller convention that's
        # easy to get wrong or bypass; this queue makes the guarantee
        # structural, in the one place all outgoing requests funnel
        # through (send(), below), instead of relying on every call site
        # getting the check right.
        self._pending_data_requests = []

        self._client = self._create_client(self.host)

    def _create_client(self, host):
        client = SpotwareClientBase(host, self.port, TcpProtocol)
        client.setConnectedCallback(self._on_connected)
        client.setMessageReceivedCallback(self._on_message_received)
        client.setDisconnectedCallback(self._on_disconnected)
        client.account_id = None
        return client

    def _schedule_switch_to_next_host(self) -> bool:
        if self._switching_host:
            return True

        next_index = self._host_index + 1
        if next_index >= len(self._host_candidates):
            return False

        old_host = self.host
        self._host_index = next_index
        self.host = self._host_candidates[self._host_index]
        self._switching_host = True
        self._stopping = True
        self.is_authorized = False
        self._app_auth_completed = False
        self._fail_pending_data_requests(f"switching host from {old_host} to {self.host}")

        logger.warning(
            "cTrader app auth failed on %s. Switching to backup host %s:%s",
            old_host,
            self.host,
            self.port,
        )

        try:
            stop_method = getattr(self._client, "stopService", None)
            if callable(stop_method):
                stop_method()
        except Exception:
            logger.exception("Failed to stop cTrader client before host switch")

        self._client = self._create_client(self.host)
        reactor.callLater(0.5, self._finish_host_switch)
        return True

    def _finish_host_switch(self):
        self._stopping = False
        self._switching_host = False
        self._client.startService()

    def start(self):
        self._stopping = False
        self._app_auth_completed = False
        self._client.startService()

    def stop(self):
        self._stopping = True
        self.is_authorized = False
        self._fail_pending_data_requests("stop() called")

        try:
            stop_method = getattr(self._client, "stopService", None)
            if callable(stop_method):
                stop_method()
        except Exception:
            logger.exception("Failed to stop Spotware client")

    def send(self, message, clientMsgId=None, responseTimeoutInSeconds=5, **params):
        timeout_alias = params.pop("timeout", None)
        if timeout_alias is not None:
            responseTimeoutInSeconds = timeout_alias

        # AUDIT FIX (2026-08-17, critical): everything except the auth
        # handshake itself queues here until self.is_authorized is True -
        # see __init__'s comment and _flush_pending_data_requests for the
        # incident this addresses (data requests going out before account
        # auth completed, rejected by cTrader as unauthorized).
        if self.is_authorized or isinstance(message, self._AUTH_HANDSHAKE_TYPES):
            return self._client.send(
                message,
                clientMsgId=clientMsgId,
                responseTimeoutInSeconds=responseTimeoutInSeconds,
                **params,
            )

        # Defense-in-depth cap (2026-08-17, per external consultation): each
        # queued item already self-clears via its own timeout below, and the
        # whole queue is already cleared on disconnect/stop/host-switch, so
        # this ceiling is a belt-and-suspenders guard against some future
        # caller queuing faster than items can time out, not a fix for a
        # reproduced leak.
        if len(self._pending_data_requests) >= SPOTWARE_MAX_PENDING_DATA_REQUESTS:
            logger.error(
                "cTrader auth queue is full (%d pending) - failing %s instead of queuing",
                len(self._pending_data_requests), type(message).__name__,
            )
            outer = Deferred()
            reactor.callLater(0, outer.errback, Exception(
                f"cTrader auth request queue is full ({SPOTWARE_MAX_PENDING_DATA_REQUESTS} pending)"
            ))
            return outer

        logger.info(
            "Queuing %s until cTrader account auth completes (%d already queued)",
            type(message).__name__, len(self._pending_data_requests),
        )
        outer = Deferred()
        entry = [message, clientMsgId, responseTimeoutInSeconds, params, outer]
        self._pending_data_requests.append(entry)

        def _timeout_if_still_queued():
            if entry in self._pending_data_requests:
                self._pending_data_requests.remove(entry)
                if not outer.called:
                    outer.errback(Exception(
                        "cTrader account auth did not complete before this queued "
                        f"request ({type(message).__name__}) timed out"
                    ))

        reactor.callLater(responseTimeoutInSeconds, _timeout_if_still_queued)
        return outer

    def _flush_pending_data_requests(self):
        pending, self._pending_data_requests = self._pending_data_requests, []
        if pending:
            logger.info("cTrader authorized - flushing %d queued request(s)", len(pending))
        for message, clientMsgId, responseTimeoutInSeconds, params, outer in pending:
            if outer.called:
                continue
            inner = self._client.send(
                message,
                clientMsgId=clientMsgId,
                responseTimeoutInSeconds=responseTimeoutInSeconds,
                **params,
            )
            inner.addCallbacks(outer.callback, outer.errback)

    def _fail_pending_data_requests(self, reason: str):
        pending, self._pending_data_requests = self._pending_data_requests, []
        for _, _, _, _, outer in pending:
            if not outer.called:
                outer.errback(Exception(f"cTrader disconnected before this queued request could be sent: {reason}"))

    def _on_connected(self, client):
        logger.info("Connected to cTrader at %s:%s. Waiting 2s before Application Auth...", self.host, self.port)
        reactor.callLater(2.0, self._send_app_auth)

    def _on_disconnected(self, client, reason=None):
        self.is_authorized = False
        self._client.account_id = None
        self._fail_pending_data_requests(f"disconnected: {reason}")

        if self._stopping:
            logger.info("cTrader disconnected during intentional stop")
            return

        logger.warning("cTrader disconnected: %s", reason)
        self.emit("error", "DISCONNECTED")

    def _send_app_auth(self):
        if not self._client_id or not self._client_secret:
            logger.error("Missing cTrader client id/secret")
            self.emit("error", "MISSING_APP_CREDENTIALS")
            return

        logger.info("Step 1: Sending Application Auth...")
        req = ProtoOAApplicationAuthReq(
            clientId=self._client_id,
            clientSecret=self._client_secret,
        )
        self.send(req, responseTimeoutInSeconds=15)

    def _request_account_list(self):
        token = app_state.get_ctrader_access_token()

        if not token:
            logger.warning("Missing cTrader access token. Trying refresh token flow.")
            self._refresh_access_token("missing_access_token")
            return

        logger.info("Step 2: Requesting account list by access token...")
        req = ProtoOAGetAccountListByAccessTokenReq(accessToken=token)
        self.send(req, responseTimeoutInSeconds=15)

    def _authorize_account(self, account_id=None):
        acc_id = account_id or get_demo_account_id()
        token = app_state.get_ctrader_access_token()

        if not acc_id:
            logger.error("Missing cTrader Account ID")
            app_state.set_ctrader_auth_issue("missing_account_id")
            self.emit("error", "MISSING_ACCOUNT_CREDENTIALS")
            return

        if not token:
            logger.warning("Missing cTrader access token. Trying refresh token flow.")
            self._refresh_access_token("missing_access_token")
            return

        logger.info("Step 2: Sending Account Auth...")
        req = ProtoOAAccountAuthReq(
            ctidTraderAccountId=acc_id,
            accessToken=token,
        )
        self.send(req, responseTimeoutInSeconds=15)

    def _refresh_access_token(self, reason: str = "manual"):
        refresh_token = app_state.get_ctrader_refresh_token()
        if not refresh_token:
            logger.error("Missing cTrader refresh token. Cannot refresh access token.")
            app_state.set_ctrader_auth_issue("missing_refresh_token")
            self.emit("error", "MISSING_REFRESH_TOKEN")
            return

        if self._refresh_in_progress:
            logger.info("cTrader token refresh already in progress (%s)", reason)
            return

        self._refresh_in_progress = True
        logger.warning("Refreshing cTrader access token (%s)...", reason)
        app_state.set_ctrader_auth_issue(f"refreshing:{reason}")

        d = deferToThread(self._refresh_access_token_http)
        d.addCallbacks(
            lambda payload: reactor.callFromThread(self._on_refresh_success, payload),
            lambda failure: reactor.callFromThread(self._on_refresh_failure, failure),
        )

    def _refresh_access_token_http(self):
        refresh_token = app_state.get_ctrader_refresh_token()
        return self._oauth_client.refreshToken(refresh_token)

    def _on_refresh_success(self, payload):
        if not isinstance(payload, dict):
            self._refresh_in_progress = False
            logger.error("cTrader refresh flow returned unexpected payload type: %r", type(payload))
            app_state.set_ctrader_auth_issue("refresh_invalid_payload")
            self.emit("error", "REFRESH_INVALID_PAYLOAD")
            return

        error_code = payload.get("errorCode") or payload.get("error")
        if error_code:
            self._refresh_in_progress = False
            description = payload.get("description") or payload.get("error_description") or "unknown error"
            logger.error("cTrader refresh flow failed: %s - %s", error_code, description)
            app_state.set_ctrader_auth_issue(f"{error_code}: {description}")
            self.emit("error", error_code)
            return

        access_token = payload.get("accessToken")
        refresh_token = payload.get("refreshToken")
        expires_in = payload.get("expiresIn")
        if not access_token:
            self._refresh_in_progress = False
            logger.error("cTrader refresh flow succeeded without accessToken")
            app_state.set_ctrader_auth_issue("refresh_missing_access_token")
            self.emit("error", "REFRESH_MISSING_ACCESS_TOKEN")
            return

        self._refresh_in_progress = False
        app_state.set_ctrader_tokens(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        )
        logger.info("cTrader access token refreshed successfully (expires_in=%ss).", expires_in)
        reactor.callLater(0.2, self._authorize_account)

    def _on_refresh_failure(self, failure):
        self._refresh_in_progress = False
        logger.exception("Failed to refresh cTrader access token")
        app_state.set_ctrader_auth_issue("refresh_request_failed")
        self.emit("error", "REFRESH_REQUEST_FAILED")

    def _on_message_received(self, client, message: ProtoMessage):
        pt = message.payloadType

        if pt == ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_RES:
            self._app_auth_completed = True
            logger.info("Step 1 OK. Waiting 1s before requesting account list...")
            reactor.callLater(1.0, self._request_account_list)
            return

        if pt == ProtoOAPayloadType.PROTO_OA_GET_ACCOUNTS_BY_ACCESS_TOKEN_RES:
            res = ProtoOAGetAccountListByAccessTokenRes()
            res.ParseFromString(message.payload)

            requested_account_id = get_demo_account_id()
            selected_account_id = None
            for account in res.ctidTraderAccount:
                candidate = int(account.ctidTraderAccountId)
                if requested_account_id and candidate == int(requested_account_id):
                    selected_account_id = candidate
                    break
                if selected_account_id is None:
                    selected_account_id = candidate

            if not selected_account_id:
                logger.error("cTrader account list is empty for this access token")
                app_state.set_ctrader_auth_issue("account_list_empty")
                self.emit("error", "ACCOUNT_LIST_EMPTY")
                return

            logger.info("Step 2 OK. Using cTrader account %s.", selected_account_id)
            reactor.callLater(0.2, self._authorize_account, selected_account_id)
            return

        if pt == ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES:
            res = ProtoOAAccountAuthRes()
            res.ParseFromString(message.payload)

            self._client.account_id = res.ctidTraderAccountId
            self.is_authorized = True
            app_state.set_ctrader_auth_issue(None)
            self._flush_pending_data_requests()

            logger.info("Step 2 OK. Account %s authorized.", res.ctidTraderAccountId)
            # BUG FIX (2026-09-03): pass self along so a stale/superseded
            # client's "ready" can't be mistaken for the current one's - see
            # the emit("ready", self) at _handle_api_error's ALREADY_LOGGED_IN
            # branch below for the race this closes.
            self.emit("ready", self)
            return

        if pt == ProtoOAPayloadType.PROTO_OA_ERROR_RES:
            self._handle_api_error(message)
            return

        if pt == ProtoOAPayloadType.PROTO_OA_ACCOUNTS_TOKEN_INVALIDATED_EVENT:
            event = ProtoOAAccountsTokenInvalidatedEvent()
            event.ParseFromString(message.payload)
            logger.warning("cTrader token invalidated event received: %s", getattr(event, "reason", "unknown"))
            self._refresh_access_token("token_invalidated_event")
            return

        if pt == ProtoOAPayloadType.PROTO_OA_SPOT_EVENT:
            spot_event = ProtoOASpotEvent()
            spot_event.ParseFromString(message.payload)
            self.emit("spot_event", spot_event)
            return

        if pt == ProtoOAPayloadType.PROTO_OA_EXECUTION_EVENT:
            execution_event = ProtoOAExecutionEvent()
            execution_event.ParseFromString(message.payload)
            self.emit("execution_event", execution_event)
            return

    def _handle_api_error(self, message: ProtoMessage):
        res = ProtoOAErrorRes()
        res.ParseFromString(message.payload)

        if res.errorCode == "ALREADY_LOGGED_IN":
            account_id = get_demo_account_id()
            if account_id:
                self._client.account_id = account_id

            self.is_authorized = True
            self._flush_pending_data_requests()
            logger.info("Account already authorized. Marking as ready.")
            # BUG FIX (2026-09-03, live finding): a disconnect can leave TWO
            # SpotwareConnect instances authenticating in parallel - Twisted's
            # own ClientService auto-reconnects the OLD one at the transport
            # layer while ctrader.py's _do_reconnect() independently builds a
            # NEW one and reassigns app_state.client to it. Both objects still
            # have on_ctrader_ready wired (EventEmitter never unbinds a
            # retired client), so whichever finishes auth SECOND used to
            # trigger _request_symbols() against whatever app_state.client
            # happened to be at that moment - often the OTHER, not-yet-
            # authorized object, producing "Symbols error: No Account ID" and
            # a stuck poll cycle (hit live 2026-09-03, ~7min hang, force-
            # killed by the supervisor). Passing self lets on_ctrader_ready
            # verify the ready client is still the current one before acting.
            self.emit("ready", self)
            return

        if res.errorCode == "BLOCKED_PAYLOAD_TYPE":
            logger.critical("cTrader rate limit. Waiting before reconnect.")
            app_state.set_ctrader_auth_issue("rate_limit_blocked")
            self.emit("error", "RATE_LIMIT_BLOCKED")
            return

        if res.errorCode == "CANT_ROUTE_REQUEST" and not self._app_auth_completed:
            if self._schedule_switch_to_next_host():
                app_state.set_ctrader_auth_issue(f"{res.errorCode}: {res.description}")
                return

        if res.errorCode in {"CH_ACCESS_TOKEN_INVALID", "OA_AUTH_TOKEN_EXPIRED"}:
            logger.warning("cTrader access token is invalid/expired. Trying refresh flow.")
            self._refresh_access_token(res.errorCode)
            return

        if self._refresh_in_progress:
            self._refresh_in_progress = False
            logger.error("cTrader refresh flow failed: %s - %s", res.errorCode, res.description)
            app_state.set_ctrader_auth_issue(f"{res.errorCode}: {res.description}")
            self.emit("error", res.errorCode)
            return

        logger.error("cTrader API Error: %s - %s", res.errorCode, res.description)
        app_state.set_ctrader_auth_issue(f"{res.errorCode}: {res.description}")
        self.emit("error", res.errorCode)

    def get_all_symbols(self):
        if not getattr(self._client, "account_id", None):
            d = Deferred()
            reactor.callLater(0, d.errback, Exception("No Account ID"))
            return d

        req = ProtoOASymbolsListReq(ctidTraderAccountId=self._client.account_id)
        return self.send(req, responseTimeoutInSeconds=20)
