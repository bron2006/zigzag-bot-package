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

# --- ПОЧАТОК ЗМІН: Прапорець стану сканера ---
# True - сканер працює, False - вимкнено
SCANNER_ENABLED = True
# --- КІНЕЦЬ ЗМІН ---