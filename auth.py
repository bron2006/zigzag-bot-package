# auth.py
import hmac
import hashlib
import json
import logging
from urllib.parse import unquote, parse_qs
from config import TELEGRAM_BOT_TOKEN, IS_DEV_MODE, DEV_USER_ID

# Створюємо спеціальний логгер для діагностики
logger = logging.getLogger("auth_debugger")
logger.setLevel(logging.INFO)

def is_valid_init_data(init_data_str: str) -> bool:
    logger.info("--- Starting initData Validation ---")
    
    if IS_DEV_MODE:
        logger.info("DEV MODE is ON. Bypassing validation.")
        return True

    if not init_data_str:
        logger.warning("initData string is EMPTY. Validation failed.")
        return False

    try:
        # Показуємо, який токен використовується (частково, для безпеки)
        token = TELEGRAM_BOT_TOKEN
        if token:
            logger.info(f"Using TELEGRAM_BOT_TOKEN starting with '{token[:5]}' and ending with '{token[-5:]}'")
        else:
            logger.error("TELEGRAM_BOT_TOKEN is NOT SET in environment. Validation failed.")
            return False

        params = dict(
            (k, unquote(v)) for k, v in (item.split("=", 1) for item in init_data_str.split("&"))
        )
        received_hash = params.pop("hash", None)
        
        if not received_hash:
            logger.warning("No 'hash' found in initData. Validation failed.")
            return False
        
        logger.info(f"Received hash: {received_hash}")

        sorted_params = sorted(params.items())
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted_params)
        
        secret_key = hmac.new("WebAppData".encode(), token.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        logger.info(f"Calculated hash: {calculated_hash}")
        
        is_valid = calculated_hash == received_hash
        logger.info(f"Validation result: {is_valid}")
        logger.info("--- Finished initData Validation ---")
        
        return is_valid
    except Exception as e:
        logger.error(f"An exception occurred during validation: {e}", exc_info=True)
        return False

def get_user_id_from_init_data(init_data_str: str) -> int | None:
    if IS_DEV_MODE and not init_data_str:
        return DEV_USER_ID

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