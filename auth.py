# auth.py
import hmac
import hashlib
from urllib.parse import unquote

from config import TELEGRAM_BOT_TOKEN

def is_valid_init_data(init_data_str: str) -> bool:
    """
    Перевіряє, чи є рядок initData, отриманий від Telegram, валідним.
    """
    if not init_data_str:
        return False

    try:
        # Розбиваємо рядок на пари ключ=значення
        params = dict(
            (k, unquote(v)) for k, v in (item.split("=", 1) for item in init_data_str.split("&"))
        )
        
        # Витягуємо хеш, який надіслав Telegram
        received_hash = params.pop("hash", None)
        if not received_hash:
            return False

        # Сортуємо пари ключ=значення за алфавітом
        sorted_params = sorted(params.items())
        
        # Формуємо рядок для перевірки
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted_params)
        
        # Секретний ключ для HMAC
        secret_key = hmac.new("WebAppData".encode(), TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256).digest()
        
        # Розраховуємо наш власний хеш
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        # Порівнюємо хеші
        return calculated_hash == received_hash
    except Exception:
        # Якщо будь-що пішло не так при розборі - вважаємо дані невалідними
        return False