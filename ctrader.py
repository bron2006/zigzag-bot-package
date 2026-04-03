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
        if not (event.HasField("bid") or event.HasField("ask")):
            return
        symbol_name = app_state.symbol_id_map.get(event.symbolId)
        if not symbol_name:
            return
            
        symbol_details = app_state.symbol_cache.get(symbol_name)
        divisor = resolve_price_divisor(symbol_details)
        
        bid = event.bid / divisor if event.HasField("bid") else None
        ask = event.ask / divisor if event.HasField("ask") else None
        mid = (bid + ask) / 2.0 if bid and ask else None
        
        app_state.live_prices[symbol_name] = {"bid": bid, "ask": ask, "mid": mid, "ts": time.time()}
        logger.debug(f"Tick {symbol_name}: Mid Price = {mid}")
    except Exception:
        logger.exception("Error processing spot event")

def start_price_subscriptions():
    if config.APP_MODE == "light":
        logger.info("APP_MODE is 'light'. Skipping automatic price subscriptions at startup.")
        return
    
    logger.info("Starting price subscriptions for all scannable assets...")
    assets_to_subscribe = scanner._collect_assets_to_scan()
    assets_to_subscribe.extend(STOCK_TICKERS)
    assets_to_subscribe = sorted(list(set(assets_to_subscribe)))

    for i, pair in enumerate(assets_to_subscribe):
        def subscribe_pair(p):
            try:
                pair_norm = p.replace("/", "")
                symbol_details = app_state.symbol_cache.get(pair_norm)
                if symbol_details:
                    req = ProtoOASubscribeSpotsReq(
                        ctidTraderAccountId=app_state.client._client.account_id,
                        symbolId=[symbol_details.symbolId]
                    )
                    app_state.client.send(req)
            except Exception:
                logger.exception(f"Error subscribing to {p}")
        
        reactor.callLater(i * 0.1, subscribe_pair, pair)

def _on_symbols_loaded(raw_message):
    try:
        res = ProtoOASymbolsListRes()
        res.ParseFromString(raw_message.payload)
        for s in res.symbol:
            app_state.symbol_cache[s.symbolName] = s
            app_state.symbol_id_map[s.symbolId] = s.symbolName
        
        logger.info(f"Loaded {len(res.symbol)} symbols from cTrader.")
        app_state.SYMBOLS_LOADED = True
        start_price_subscriptions()
    except Exception:
        logger.exception("on_symbols_loaded error")

def _on_symbols_error(failure):
    msg = failure.getErrorMessage() if hasattr(failure, "getErrorMessage") else str(failure)
    logger.error(f"Failed to load symbols: {msg}")
    app_state.SYMBOLS_LOADED = False

def on_ctrader_ready():
    logger.info("cTrader client ready — requesting symbol list")
    try:
        d = app_state.client.get_all_symbols()
        d.addCallbacks(_on_symbols_loaded, _on_symbols_error)
    except Exception:
        logger.exception("on_ctrader_ready error")

def start_ctrader_client():
    try:
        client = SpotwareConnect(get_ct_client_id(), get_ct_client_secret())
        app_state.client = client
        client.on("ready", on_ctrader_ready)
        client.on("spot_event", _on_spot_event) 
        reactor.callWhenRunning(client.start)
        logger.info("cTrader client scheduled to start")
    except Exception:
        logger.exception("Failed to initialize cTrader client")