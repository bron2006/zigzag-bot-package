# ctrader.py
import logging
import time

from twisted.internet import reactor

from config import STOCK_TICKERS, get_ct_client_id, get_ct_client_secret
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOASpotEvent,
    ProtoOASubscribeSpotsReq,
    ProtoOASymbolsListRes,
)
from notifier import notify_admin
from price_utils import resolve_price_divisor
from spotware_connect import SpotwareConnect
from state import app_state

logger = logging.getLogger("ctrader")

_reconnect_attempt = 0
_reconnect_scheduled = False


def start_ctrader_client():
    global _reconnect_scheduled

    _reconnect_scheduled = False

    try:
        client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
        app_state.client = client

        client.on("ready", on_ctrader_ready)
        client.on("spot_event", _on_spot_event)
        client.on("error", _handle_error)

        client.start()
        logger.info("cTrader client started")
        return client

    except Exception:
        logger.exception("Failed to initialize cTrader client")
        notify_admin("cTrader client не стартував", alert_key="ctrader_start_failed")
        return None


def _handle_error(reason):
    logger.error("cTrader error handler: %s", reason)

    delay = 300 if reason == "RATE_LIMIT_BLOCKED" else 30
    _schedule_reconnect(delay)


def _schedule_reconnect(delay):
    global _reconnect_scheduled, _reconnect_attempt

    if _reconnect_scheduled:
        return

    _reconnect_scheduled = True
    _reconnect_attempt += 1

    logger.warning("Reconnecting cTrader in %ss (attempt %s)", delay, _reconnect_attempt)
    reactor.callLater(delay, _do_reconnect)


def _do_reconnect():
    if app_state.client:
        try:
            app_state.client.stop()
        except Exception:
            logger.exception("Failed to stop cTrader client before reconnect")

    app_state.clear_symbol_state()
    start_ctrader_client()


def on_ctrader_ready():
    global _reconnect_attempt

    _reconnect_attempt = 0
    logger.info("cTrader account authorized. Loading symbols...")
    reactor.callLater(1.0, _request_symbols)


def _request_symbols():
    if not app_state.client:
        logger.warning("Cannot request symbols: app_state.client is empty")
        return

    d = app_state.client.get_all_symbols()
    d.addCallbacks(_on_symbols_loaded, _on_symbols_error)


def _on_symbols_error(failure):
    logger.error("Symbols error: %s", failure.getErrorMessage())
    _schedule_reconnect(30)
    return None


def _on_symbols_loaded(msg):
    try:
        res = ProtoOASymbolsListRes()
        res.ParseFromString(msg.payload)

        symbol_cache = {}
        symbol_id_map = {}
        all_names = []

        for symbol in res.symbol:
            name = symbol.symbolName.replace("/", "").upper()
            symbol_cache[name] = symbol
            symbol_id_map[symbol.symbolId] = name
            all_names.append(name)

        with app_state._state_lock:
            app_state.symbol_cache = symbol_cache
            app_state.symbol_id_map = symbol_id_map
            app_state.all_symbol_names = sorted(all_names)
            app_state.SYMBOLS_LOADED = True

        logger.info("Loaded %s cTrader symbols. Pairs are ready.", len(symbol_cache))
        start_price_subscriptions()

    except Exception:
        logger.exception("Error parsing symbols")
        _schedule_reconnect(30)


def start_price_subscriptions():
    if not app_state.SYMBOLS_LOADED:
        logger.info("Symbols are not loaded yet. Price subscriptions skipped.")
        return

    try:
        import scanner

        assets = sorted(set(scanner._collect_assets_to_scan() + STOCK_TICKERS))
    except Exception:
        logger.exception("Failed to collect assets for subscriptions")
        assets = sorted(set(STOCK_TICKERS))

    if not assets:
        logger.info("No assets selected for price subscriptions")
        return

    logger.info("Subscribing to %s assets...", len(assets))

    for i, pair in enumerate(assets):
        norm = pair.replace("/", "").upper()
        reactor.callLater(i * 0.5, _subscribe_pair, norm)


def _subscribe_pair(pair):
    if not app_state.client:
        return

    symbol = app_state.symbol_cache.get(pair)
    if symbol is None:
        logger.debug("Symbol %s not found in cTrader cache. Subscription skipped.", pair)
        return

    account_id = getattr(app_state.client._client, "account_id", None)
    if not account_id:
        logger.warning("No Account ID. Cannot subscribe to %s", pair)
        return

    try:
        req = ProtoOASubscribeSpotsReq(
            ctidTraderAccountId=account_id,
            symbolId=[symbol.symbolId],
        )
        app_state.client.send(req, responseTimeoutInSeconds=10)
        logger.debug("Subscribed to %s", pair)

    except Exception:
        logger.exception("Failed to subscribe to %s", pair)


def _value_from_event(event: ProtoOASpotEvent, field: str, divisor: float):
    if event.HasField(field):
        return getattr(event, field) / divisor
    return None


def _on_spot_event(event: ProtoOASpotEvent):
    if not (event.HasField("bid") or event.HasField("ask")):
        return

    name = app_state.symbol_id_map.get(event.symbolId)
    if not name:
        return

    symbol = app_state.symbol_cache.get(name)
    if symbol is None:
        return

    try:
        divisor = resolve_price_divisor(symbol)
        bid = _value_from_event(event, "bid", divisor)
        ask = _value_from_event(event, "ask", divisor)

        if bid is not None and ask is not None:
            mid = (bid + ask) / 2
        else:
            mid = bid if bid is not None else ask

        ts = time.time()
        payload = {
            "type": "price",
            "pair": name,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "ts": ts,
        }

        app_state.update_live_price(name, payload)
        app_state.publish_price_sse(payload)

    except Exception:
        logger.exception("Failed to process spot event for symbolId=%s", event.symbolId)
