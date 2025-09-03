# state.py
import queue

client = None
updater = None
symbol_cache = {}
all_symbol_names = []
SYMBOLS_LOADED = False
scanner_cooldown_cache = {}

SCANNER_ENABLED = True # Старий стан залишається для сумісності
# --- ПОЧАТОК ЗМІН ---
# Додаємо нову структуру для майбутніх сканерів
SCANNER_STATE = {
    "forex": False,
    "crypto": False,
    "commodities": False
}
# --- КІНЕЦЬ ЗМІН ---

sse_queue = queue.Queue()
latest_analysis_cache = {}