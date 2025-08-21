# state.py
# Глобальний стан, який буде доступний для всіх модулів програми.

client = None         # Екземпляр клієнта cTrader
symbol_cache = {}   # Кеш для завантажених символів
updater = None        # Екземпляр Telegram Updater
SYMBOLS_LOADED = False # Прапорець, що символи завантажено