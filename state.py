# state.py
# Цей файл зберігає глобальний стан для процесу-воркера.

# Клієнт для cTrader API
client = None

# Об'єкт для взаємодії з Telegram Bot API
updater = None

# Кеш для символів, завантажених з cTrader
symbol_cache = {}

# Кеш для кулдаунів сповіщень сканера
scanner_cooldown_cache = {}