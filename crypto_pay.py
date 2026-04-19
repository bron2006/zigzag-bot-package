import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import requests

from config import (
    CRYPTO_PAY_API_URL,
    CRYPTO_PAY_TOKEN,
    SUBSCRIPTION_DAYS,
    SUBSCRIPTION_PRICE_AMOUNT,
    SUBSCRIPTION_PRICE_ASSET,
)

logger = logging.getLogger("crypto_pay")


class CryptoPayError(RuntimeError):
    pass


def _token() -> str:
    token = CRYPTO_PAY_TOKEN or ""
    if not token:
        raise CryptoPayError("CRYPTO_PAY_TOKEN is not configured")
    return token


def _headers() -> dict:
    return {
        "Crypto-Pay-API-Token": _token(),
        "Content-Type": "application/json",
    }


def create_subscription_invoice(user_id: int, *, language: str = "uk") -> dict:
    days = int(SUBSCRIPTION_DAYS or 30)
    amount = str(SUBSCRIPTION_PRICE_AMOUNT)
    asset = (SUBSCRIPTION_PRICE_ASSET or "USDT").upper()
    payload = {
        "kind": "subscription",
        "user_id": int(user_id),
        "days": days,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    body = {
        "asset": asset,
        "amount": amount,
        "description": f"ZigZag Bot PRO на {days} днів",
        "hidden_message": "Оплату отримано. PRO-доступ активується автоматично.",
        "payload": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        "allow_comments": False,
        "allow_anonymous": False,
        "expires_in": 3600,
    }

    try:
        response = requests.post(
            f"{CRYPTO_PAY_API_URL}/createInvoice",
            headers=_headers(),
            json=body,
            timeout=15,
        )
    except requests.RequestException as exc:
        raise CryptoPayError(f"Crypto Pay request failed: {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise CryptoPayError("Crypto Pay returned non-JSON response") from exc

    if not response.ok or not data.get("ok"):
        error = data.get("error") or response.text[:200]
        raise CryptoPayError(f"Crypto Pay invoice error: {error}")

    invoice = data.get("result") or {}
    invoice_url = (
        invoice.get("bot_invoice_url")
        or invoice.get("pay_url")
        or invoice.get("mini_app_invoice_url")
        or invoice.get("web_app_invoice_url")
    )
    if not invoice_url:
        raise CryptoPayError("Crypto Pay invoice URL is missing")

    invoice["invoice_url"] = invoice_url
    invoice["subscription_days"] = days
    invoice["subscription_amount"] = amount
    invoice["subscription_asset"] = asset
    return invoice


def verify_webhook_signature(raw_body: bytes, signature: str | None) -> bool:
    if not signature:
        return False

    try:
        secret = hashlib.sha256(_token().encode("utf-8")).digest()
    except CryptoPayError:
        return False

    digest = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature)


def parse_invoice_payload(invoice: dict) -> dict:
    raw_payload = invoice.get("payload") if isinstance(invoice, dict) else None
    if not raw_payload:
        return {}

    if isinstance(raw_payload, dict):
        return raw_payload

    try:
        payload = json.loads(raw_payload)
    except (TypeError, ValueError):
        logger.warning("Invalid Crypto Pay invoice payload: %r", raw_payload)
        return {}

    return payload if isinstance(payload, dict) else {}
