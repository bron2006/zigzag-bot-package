# ctrader.py
import logging
import time
from twisted.internet import reactor

import config
import scanner
from config import STOCK_TICKERS, get_ct_client_id, get_ct_client_secret
from spotware_connect import SpotwareConnect
from state import app_state
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOASymbolsListRes,
    ProtoOASubscribeSpotsReq,
    ProtoOASpotEvent,
)
from price_utils import resolve_price_divisor

logger = logging.getLogger("ctrader")

_RECONNECT_BASE_DELAY = 5
_RECONNECT_MAX_DELAY = 120
_RECONNECT_MAX_TRIES = 10

_STALE_THRESHOLD = 300
_STALE_CHECK_INTERVAL = 60
_BOOTSTRAP_GRACE_SECONDS = 180

_reconnect_attempt = 0
_reconnect_scheduled = False
_reconnect_call = None
_stale_check_call = None
_connection_ready_ts = 0.0
_subscribed_symbols = set()

_SYMBOL_ALIASES = {
    "US100": ["USTEC", "NAS100", "US100", "US100USD", "USTECH"],
    "US30": ["US30", "DJ30", "DJI30", "WALLSTREET"],
    "SPX500": ["US500", "SPX500", "SP500", "US500USD"],
    "GER40": ["GER40", "DE40", "DAX40", "DE30"],
    "DE30": ["DE30", "GER40", "DE40", "DAX40"],