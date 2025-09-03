# state.py
import queue

# cTrader
client = None
symbol_cache = {}
all_symbol_names = []
SYMBOLS_LOADED = False
symbol_id_to_name_map = {}

# Scanner
scanner_cooldown_cache = {}
SCANNER_STATE = {
    "forex": False,
    "crypto": False,
    "commodities": False
}

# Web App
sse_queue = queue.Queue()
latest_analysis_cache = {}

# Price Streaming & Analysis
live_price_cache = {}
active_subscriptions = set()
# --- ПОЧАТОК ЗМІН ---
# Сховище для буферів свічок, буде використовуватись в Redis
candle_buffers = {}
# --- КІНЕЦЬ ЗМІН ---