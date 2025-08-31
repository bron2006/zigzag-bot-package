# state.py

# NEW: Прапорець, який показує, чи готовий додаток до роботи
# (тобто, чи завантажено список символів з cTrader)
SYSTEM_READY = False

# Клієнт для cTrader API
client = None

# Об'єкт для взаємодії з Telegram Bot API
updater = None

# Кеш для символів, завантажених з cTrader
symbol_cache = {}

# Кеш для кулдаунів сповіщень сканера
scanner_cooldown_cache = {}