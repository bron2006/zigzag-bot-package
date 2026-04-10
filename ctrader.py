# ctrader.py
import logging
import time
from twisted.internet import reactor

import config
import scanner
from config import STOCK_TICKERS, get_ct_client_id, get_ct_client_secret
from notifier import notify_admin
from spotware_connect import SpotwareConnect
from state import app_state
from price_utils import resolve_price_divisor
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOASymbolsListRes, 
    ProtoOASubscribeSpotsReq, 
    ProtoOASpotEvent
)

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
    except Exception:
        logger.exception("Failed to initialize cTrader client")

def _handle_error(reason):
    global _reconnect_attempt
    logger.error(f"cTrader error handler: {reason}")
    
    # Якщо бан — чекаємо 5 хвилин
    delay = 300 if reason == "RATE_LIMIT_BLOCKED" else 30
    _schedule_reconnect(delay)

def _schedule_reconnect(delay):
    global _reconnect_scheduled, _reconnect_attempt
    if _reconnect_scheduled: return
    _reconnect_scheduled = True
    _reconnect_attempt += 1
    logger.warning(f"Reconnecting in {delay}s (Attempt {_reconnect_attempt})")
    reactor.callLater(delay, _do_reconnect)

def _do_reconnect():
    if app_state.client:
        try: app_state.client.stop()
        except: pass
    app_state.SYMBOLS_LOADED = False
    start_ctrader_client()

def on_ctrader_ready():
    global _reconnect_attempt
    _reconnect_attempt = 0
    logger.info("Account authorized! Loading symbols...")
    # ПАУЗА перед запитом символів
    reactor.callLater(1.0, _request_symbols)

def _request_symbols():
    if not app_state.client: return
    d = app_state.client.get_all_symbols()
    d.addCallbacks(_on_symbols_loaded, lambda e: logger.error(f"Symbols error: {e}"))

def _on_symbols_loaded(msg):
    try:
        res = ProtoOASymbolsListRes()
        res.ParseFromString(msg.payload)
        # Зберігаємо символи
        app_state.symbol_cache = {s.symbolName.replace("/", ""): s for s in res.symbol}
        app_state.symbol_id_map = {s.symbolId: s.symbolName.replace("/", "") for s in res.symbol}
        app_state.SYMBOLS_LOADED = True
        logger.info(f"✅ Loaded {len(app_state.symbol_cache)} symbols. Pairs are ready.")
        start_price_subscriptions()
    except Exception as e:
        logger.error(f"Error parsing symbols: {e}")

def start_price_subscriptions():
    if not app_state.SYMBOLS_LOADED: return
    assets = sorted(list(set(scanner._collect_assets_to_scan() + STOCK_TICKERS)))
    logger.info(f"Subscribing to {len(assets)} assets...")
    for i, pair in enumerate(assets):
        reactor.callLater(i * 0.5, _subscribe_pair, pair.replace("/", "").upper())

def _subscribe_pair(pair):
    if pair not in app_state.symbol_cache: return
    sid = app_state.symbol_cache[pair].symbolId
    req = ProtoOASubscribeSpotsReq(ctidTraderAccountId=app_state.client._client.account_id, symbolId=[sid])
    app_state.client.send(req)

def _on_spot_event(event):
    if not (event.HasField("bid") or event.HasField("ask")): return
    name = app_state.symbol_id_map.get(event.symbolId)
    if not name or name not in app_state.symbol_cache: return
    
    # Використовуємо правильний дільник для ціни
    div = resolve_price_divisor(app_state.symbol_cache[name])
    bid = event.bid / div if event.HasField("bid") else 0
    app_state.live_prices[name] = {"mid": bid, "ts": time.time()}