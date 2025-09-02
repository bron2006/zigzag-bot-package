# state.py
import queue

client = None
updater = None
symbol_cache = {}
all_symbol_names = []
SYMBOLS_LOADED = False
scanner_cooldown_cache = {}
SCANNER_ENABLED = True # Старий стан, який скоро видалимо
SCANNER_STATE = {
    "forex": False,
    "crypto": False,
    "commodities": False
}

# --- ПОЧАТОК ЗМІН ---
live_price_cache = {}
active_subscriptions = set()
symbol_id_to_name_map = {}
# --- КІНЕЦЬ ЗМІН ---

sse_queue = queue.Queue()
latest_analysis_cache = {}