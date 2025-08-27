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

# --- ПОЧАТОК ЗМІН: Єдине сховище для ID останнього меню ---
# Це потрібно, щоб і сканер, і ручні команди могли видаляти попереднє меню
last_menu_message_id = None
# --- КІНЕЦЬ ЗМІН ---