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

# --- ПОЧАТОК ЗМІН: Додано стан для сканера ---
# Кеш для "охолодження" сповіщень
scanner_cooldown_cache = {}
# Прапорець стану сканера
SCANNER_ENABLED = True
# --- КІНЕЦЬ ЗМІН ---