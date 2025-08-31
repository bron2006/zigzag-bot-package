# state.py
import threading

# Цей файл зберігає глобальний стан додатку,
# щоб різні модулі мали доступ до спільних об'єктів.

# Клієнт для cTrader API
client = None

# Об'єкт для взаємодії з Telegram Bot API
updater = None

# Кеш для символів, завантажених з cTrader
symbol_cache = {}
all_symbol_names = []
SYMBOLS_LOADED = False

# Кеш для сканера ринку
scanner_cooldown_cache = {}

# Прапорець стану сканера
SCANNER_ENABLED = True

# Об'єкт блокування для безпечного доступу до SCANNER_ENABLED
scanner_lock = threading.Lock()

# MODIFIED: Замість черги тепер використовуємо простий список
# для зберігання активних підключень до SSE.
sse_clients = []

# --- ПОЧАТОК ЗМІН: Кеш для результатів аналізу ---
# Тут сканер буде зберігати останні дані по кожній парі.
# Формат: {'EURUSD': {..результат..}, 'GBPUSD': {..результат..}}
latest_analysis_cache = {}
# --- КІНЕЦЬ ЗМІН ---