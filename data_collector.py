# data_collector.py
import logging
import time
import os
import pandas as pd
import talib
from twisted.internet import reactor
from twisted.internet.defer import Deferred

from spotware_connect import SpotwareConnect
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq, ProtoOAGetTrendbarsRes, ProtoOASymbolsListReq, ProtoOASymbolsListRes
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod as TrendbarPeriod
from config import get_ct_client_id, get_ct_client_secret

# --- Налаштування ---
PAIR_TO_DOWNLOAD = "EURUSD"
TIMEFRAME = "15m"
DAYS_OF_DATA = 365
# --- ПОЧАТОК ЗМІН: Вказуємо правильну папку для збереження ---
OUTPUT_FILE = f"/data/{PAIR_TO_DOWNLOAD}_{TIMEFRAME}_history.csv"
# --- КІНЕЦЬ ЗМІН ---

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("data_collector")

PERIOD_MAP = { "15m": TrendbarPeriod.M15 }
symbol_cache = {}
client = None
final_deferred = Deferred()

def get_market_data_for_period(symbol_id: int, period: str, from_ts: int, to_ts: int) -> Deferred:
    d = Deferred()
    tf_proto = PERIOD_MAP.get(period)
    request = ProtoOAGetTrendbarsReq(
        ctidTraderAccountId=client._client.account_id,
        symbolId=symbol_id,
        period=tf_proto,
        fromTimestamp=from_ts,
        toTimestamp=to_ts
    )
    data_deferred = client.send(request, timeout=120)

    def process_response(message):
        try:
            response = ProtoOAGetTrendbarsRes(); response.ParseFromString(message.payload)
            divisor = 10**5
            bars = [{'ts': pd.to_datetime(bar.utcTimestampInMinutes * 60, unit='s', utc=True),
                     'Open': (bar.low + bar.deltaOpen) / divisor, 'High': (bar.low + bar.deltaHigh) / divisor,
                     'Low': bar.low / divisor, 'Close': (bar.low + bar.deltaClose) / divisor,
                     'Volume': bar.volume} for bar in response.trendbar]
            df = pd.DataFrame(bars); d.callback(df)
        except Exception as e: d.errback(e)

    data_deferred.addCallbacks(process_response, d.errback)
    return d

def on_data_collected(df: pd.DataFrame):
    if df.empty:
        logger.error("No data was downloaded. Exiting.")
        final_deferred.callback(None)
        return

    logger.info(f"Successfully downloaded {len(df)} candles. Calculating features...")
    
    try:
        df['ATR'] = talib.ATR(df['High'], df['Low'], df['Close'], timeperiod=14)
        df['ADX'] = talib.ADX(df['High'], df['Low'], df['Close'], timeperiod=14)
        df['RSI'] = talib.RSI(df['Close'], timeperiod=14)
        df['EMA50'] = talib.EMA(df['Close'], timeperiod=50)
        df['EMA200'] = talib.EMA(df['Close'], timeperiod=200)
    except Exception as e:
        logger.error(f"Failed to calculate features: {e}")
        final_deferred.callback(None)
        return
        
    df.dropna(inplace=True)
    df.reset_index(drop=True, inplace=True)

    logger.info(f"Saving {len(df)} rows of data to {OUTPUT_FILE}...")
    df.to_csv(OUTPUT_FILE, index=False)
    
    logger.info("Data collection complete!")
    final_deferred.callback(True)

def start_download():
    logger.info(f"Looking for symbol '{PAIR_TO_DOWNLOAD}'...")
    symbol_details = symbol_cache.get(PAIR_TO_DOWNLOAD)
    if not symbol_details:
        logger.error(f"Symbol {PAIR_TO_DOWNLOAD} not found!")
        final_deferred.callback(None)
        return
    
    symbol_id = symbol_details.symbolId
    now = int(time.time() * 1000)
    from_ts = now - (DAYS_OF_DATA * 24 * 60 * 60 * 1000)
    
    logger.info(f"Starting data download for {PAIR_TO_DOWNLOAD}...")
    d = get_market_data_for_period(symbol_id, TIMEFRAME, from_ts, now)
    d.addCallbacks(on_data_collected, final_deferred.errback)

def on_symbols_loaded(raw_message):
    global symbol_cache
    try:
        res = ProtoOASymbolsListRes(); res.ParseFromString(raw_message.payload)
        symbol_cache = {s.symbolName.replace("/", ""): s for s in res.symbol}
        logger.info(f"Loaded {len(symbol_cache)} symbols from cTrader.")
        start_download()
    except Exception as e:
        logger.exception("on_symbols_loaded error"); final_deferred.callback(None)

def on_ctrader_ready():
    logger.info("cTrader client ready — requesting symbol list")
    d = client.get_all_symbols()
    d.addCallbacks(on_symbols_loaded, lambda f: final_deferred.callback(None))

def main():
    global client
    client_id = get_ct_client_id(); client_secret = get_ct_client_secret()
    if not all([client_id, client_secret]):
        logger.error("CT_CLIENT_ID or CT_CLIENT_SECRET are not set."); return

    client = SpotwareConnect(client_id, client_secret)
    client.on("ready", on_ctrader_ready)
    final_deferred.addBoth(lambda _: reactor.stop())
    reactor.callWhenRunning(client.start)
    logger.info("Starting data collector...")
    reactor.run()

if __name__ == "__main__":
    main()