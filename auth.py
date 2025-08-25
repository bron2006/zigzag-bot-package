import hmac
import hashlib
import json
from urllib.parse import unquote, parse_qs

from config import TELEGRAM_BOT_TOKEN, IS_DEV_MODE

def is_valid_init_data(init_data_str: str) -> bool:
    """
    Перевіряє, чи є рядок initData, отриманий від Telegram, валідним.
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

# --- ПОЧАТОК ЗМІН: Нова функція для отримання даних користувача ---
def get_user_id_from_init_data(init_data_str: str) -> int | None:
    """Безпечно витягує user_id з рядка initData."""
    if not init_data_str:
        return None
    try:
        params = parse_qs(init_data_str)
        user_json_str = params.get("user", [None])[0]
        if user_json_str:
            user_data = json.loads(user_json_str)
            return user_data.get("id")
    except Exception:
        return None
    return None
# --- КІНЕЦЬ ЗМІН ---