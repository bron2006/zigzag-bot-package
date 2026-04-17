import hashlib
import hmac
import json
import logging
import time
from urllib.parse import parse_qs, parse_qsl

from config import DEV_USER_ID, IS_DEV_MODE, TELEGRAM_BOT_TOKEN

logger = logging.getLogger("auth")

_MAX_INIT_DATA_AGE_SECONDS = 24 * 60 * 60


def _parse_init_data(init_data_str: str) -> dict[str, str]:
    if not init_data_str:
        return {}

    return dict(parse_qsl(init_data_str, keep_blank_values=True))


def _is_fresh(auth_date: str | None) -> bool:
    if not auth_date:
        return False

    try:
        auth_ts = int(auth_date)
    except (TypeError, ValueError):
        return False

    return 0 <= (time.time() - auth_ts) <= _MAX_INIT_DATA_AGE_SECONDS


def is_valid_init_data(init_data_str: str) -> bool:
    if IS_DEV_MODE:
        logger.debug("DEV MODE is ON. Bypassing Telegram initData validation.")
        return True

    if not init_data_str:
        logger.warning("Telegram initData validation failed: empty initData")
        return False

    token = TELEGRAM_BOT_TOKEN
    if not token:
        logger.error("Telegram initData validation failed: TELEGRAM_BOT_TOKEN is not set")
        return False

    try:
        params = _parse_init_data(init_data_str)
        received_hash = params.pop("hash", None)

        if not received_hash:
            logger.warning("Telegram initData validation failed: missing hash")
            return False

        if not _is_fresh(params.get("auth_date")):
            logger.warning("Telegram initData validation failed: stale or missing auth_date")
            return False

        data_check_string = "\n".join(
            f"{key}={value}" for key, value in sorted(params.items())
        )

        secret_key = hmac.new(
            b"WebAppData",
            token.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        is_valid = hmac.compare_digest(calculated_hash, received_hash)
        if not is_valid:
            logger.warning("Telegram initData validation failed: hash mismatch")

        return is_valid

    except Exception:
        logger.exception("Telegram initData validation failed unexpectedly")
        return False


def get_user_id_from_init_data(init_data_str: str) -> int | None:
    if IS_DEV_MODE and not init_data_str:
        return DEV_USER_ID

    if not init_data_str:
        return None

    try:
        params = parse_qs(init_data_str)
        user_json_str = params.get("user", [None])[0]
        if not user_json_str:
            return None

        user_data = json.loads(user_json_str)
        user_id = user_data.get("id")
        return int(user_id) if user_id is not None else None

    except Exception:
        logger.debug("Could not parse Telegram user id from initData", exc_info=True)
        return None
