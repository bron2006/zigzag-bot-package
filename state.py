# state.py
import queue

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

# Черга для передачі сигналів у веб-додаток
sse_queue = queue.Queue()

# Кеш для результатів аналізу
# Формат: {'EURUSD': {..результат..}, 'GBPUSD': {..результат..}}
latest_analysis_cache = {}