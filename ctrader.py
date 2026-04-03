# ctrader.py
import logging
import time
from twisted.internet import reactor
from state import app_state
import config
from config import STOCK_TICKERS, get_ct_client_id, get_ct_client_secret
from spotware_connect import SpotwareConnect
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOASymbolsListRes, ProtoOASubscribeSpotsReq, ProtoOASpotEvent
)
import scanner
from price_utils import resolve_price_divisor

logger = logging.getLogger("ctrader")

def _on_spot_event(event: ProtoOASpotEvent):
    try:
        if not (event.HasField("bid") or event.HasField("ask")): return
        name = app_state.symbol_id_map.get(event.symbolId)
        if not name: return
        details = app_state.symbol_cache.get(name)
        div = resolve_price_divisor(details)
        
        bid = event.bid / div if event.HasField("bid") else None
        ask = event.ask / div if event.HasField("ask") else None
        mid = (bid + ask) / 2.0 if bid and ask else None
        app_state.live_prices[name] = {"bid": bid, "ask": ask, "mid": mid, "ts": time.time()}
    except Exception: logger.exception("Error in spot event")

def start_price_subscriptions():
    assets = sorted(list(set(scanner._collect_assets_to_scan() + STOCK_TICKERS)))
    for i, p in enumerate(assets):
        def sub(pair):
            details = app_state.symbol_cache.get(pair.replace("/", ""))
            if details:
                req = ProtoOASubscribeSpotsReq(
                    ctidTraderAccountId=app_state.client._client.account_id, 
                    symbolId=[details.symbolId]
                )
                app_state.client.send(req)
        reactor.callLater(i * 0.1, sub, p)

def _on_symbols_loaded(raw):
    res = ProtoOASymbolsListRes()
    res.ParseFromString(raw.payload)
    for s in res.symbol:
        app_state.symbol_cache[s.symbolName] = s
        app_state.symbol_id_map[s.symbolId] = s.symbolName
    app_state.SYMBOLS_LOADED = True
    start_price_subscriptions()

def on_ctrader_ready():
    app_state.client.get_all_symbols().addCallback(_on_symbols_loaded)

def start_ctrader_client():
    client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
    app_state.client = client
    client.on("ready", on_ctrader_ready)
    client.on("spot_event", _on_spot_event)
    reactor.callWhenRunning(client.start)