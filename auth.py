# auth.py
import hmac
import hashlib
from urllib.parse import unquote

from config import TELEGRAM_BOT_TOKEN, IS_DEV_MODE

def is_valid_init_data(init_data_str: str) -> bool:
    """
    Перевіряє, чи є рядок initData, отриманий від Telegram, валідним.
    Якщо увімкнено режим розробника (IS_DEV_MODE), перевірка пропускається.
    """
    if IS_DEV_MODE:
        return True

    if not init_data_str:
        return False

    try:
        params = dict(
            (k, unquote(v)) for k, v in (item.split("=", 1) for item in init_data_str.split("&"))
        )
        
        received_hash = params.pop("hash", None)
        if not received_hash:
            return False

        sorted_params = sorted(params.items())
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted_params)
        
        secret_key = hmac.new("WebAppData".encode(), TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        return calculated_hash == received_hash
    except Exception:
        return False