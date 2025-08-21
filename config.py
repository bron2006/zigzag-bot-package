# config.py
import os


def _getenv(name: str, default=None, required: bool = False):
    """
    Витягує значення змінної оточення.

    Args:
        name (str): назва змінної оточення.
        default: значення за замовчуванням, якщо змінна не задана.
        required (bool): якщо True і змінна відсутня → викликає RuntimeError.

    Returns:
        str | None: значення змінної оточення або default.
    """
    value = os.getenv(name, default)
    if required and (value is None or value == ""):
        raise RuntimeError(f"Missing required env var: {name}")
    return value


# ---------- Базові параметри ----------
# Порт, на якому запускається веб-сервер (наприклад для webhook)
PORT = int(_getenv("PORT", "8080"))

# Ім'я додатку у Fly.io, використовується для побудови URL webhook
FLY_APP_NAME = _getenv("FLY_APP_NAME")


# ---------- Telegram ----------
# Токен Telegram-бота (обов’язковий параметр)
TELEGRAM_BOT_TOKEN = _getenv("TELEGRAM_BOT_TOKEN", required=True)

# Основний ID чату для сповіщень
CHAT_ID = _getenv("CHAT_ID")

# Особистий ID користувача для приватних повідомлень від бота
MY_TELEGRAM_ID = _getenv("MY_TELEGRAM_ID")

# Секретний ключ для перевірки запитів вебхука
WEBHOOK_SECRET = _getenv("WEBHOOK_SECRET", "dev")


# ---------- cTrader API ----------
# Ідентифікатор застосунку в cTrader
CT_CLIENT_ID = _getenv("CT_CLIENT_ID")

# Секрет застосунку в cTrader
CT_CLIENT_SECRET = _getenv("CT_CLIENT_SECRET")

# Access та refresh токени для інтеграції з cTrader
CTRADER_ACCESS_TOKEN = _getenv("CTRADER_ACCESS_TOKEN")
CTRADER_REFRESH_TOKEN = _getenv("CTRADER_REFRESH_TOKEN")

# Ідентифікатор демо-рахунку (отримується з env)
DEMO_ACCOUNT_ID_ENV = _getenv("DEMO_ACCOUNT_ID")


def get_demo_account_id() -> int:
    """
    Повертає DEMO_ACCOUNT_ID як int.

    Використовується для сумісності з analysis.py.
    Якщо значення не знайдено або не є числом → викликає помилку.

    Returns:
        int: ідентифікатор демо-рахунку
    """
    if not DEMO_ACCOUNT_ID_ENV:
        raise RuntimeError("Missing required env var: DEMO_ACCOUNT_ID")
    try:
        return int(str(DEMO_ACCOUNT_ID_ENV).strip())
    except ValueError as e:
        raise RuntimeError("DEMO_ACCOUNT_ID must be an integer") from e


# ---------- API для ринкових даних ----------
# Ключі для доступу до біржових API (опціональні)
FINNHUB_API_KEY = _getenv("FINNHUB_API_KEY")
TWELVEDATA_API_KEY = _getenv("TWELVEDATA_API_KEY")


# ---------- Legacy (сумісність зі старим кодом) ----------
TOKEN = _getenv("TOKEN")


# ---------- База даних ----------
# Ім’я або шлях до SQLite бази (за замовчуванням /data/zigzag.sqlite3)
DB_NAME = _getenv("DB_NAME", "/data/zigzag.sqlite3")


def get_db_name() -> str:
    """
    Повертає шлях до бази даних.

    Returns:
        str: шлях до SQLite файлу
    """
    return DB_NAME
