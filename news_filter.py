import logging
import re
import threading
import time
from typing import Dict, Optional

import requests
from twisted.internet import reactor
from twisted.internet.defer import Deferred, succeed
from twisted.internet.threads import deferToThreadPool

from config import GEMINI_API_KEY
from state import app_state

logger = logging.getLogger("news_filter")

_GEMINI_MODEL = "gemini-flash-latest"
_GEMINI_API_VERSION = "v1beta"
_GEMINI_ENDPOINT = (
    f"https://generativelanguage.googleapis.com/{_GEMINI_API_VERSION}/"
    f"models/{_GEMINI_MODEL}:generateContent"
)

_cache: Dict[str, dict] = {}
_cache_lock = threading.RLock()

_CACHE_TTL = 600
_ERROR_CACHE_TTL = 60

_PROMPT = """You are a short-term trading news gate.

Asset: {pair}

Check if there are dangerous high-impact news or market-moving events in the next 30 minutes.

Reply with EXACTLY ONE WORD:
GO
or
BLOCK
"""

# Робимо адекватний timeout на рівні requests, а не Deferred timeout зверху
_REQUEST_TIMEOUT = (5, 8)  # connect, read
_RETRY_REQUEST_TIMEOUT = (5, 5)


def _blocking_pool():
    return app_state.blocking_pool or reactor.getThreadPool()


def _now() -> float:
    return time.time()


def _normalize_pair(pair: str) -> str:
    return (pair or "").replace("/", "").upper().strip()


def _mask_key(value: Optional[str]) -> str:
    if not value:
        return "<empty>"
    if len(value) < 10:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _get_cached(pair: str) -> Optional[dict]:
    key = _normalize_pair(pair)
    with _cache_lock:
        cached = _cache.get(key)

    if not cached:
        return None

    ttl = cached.get("_ttl", _CACHE_TTL)
    if (_now() - cached.get("ts", 0)) < ttl:
        return dict(cached)

    return None


def _store_cache(pair: str, result: dict, ttl: int) -> dict:
    key = _normalize_pair(pair)
    payload = dict(result)
    payload["ts"] = _now()
    payload["_ttl"] = ttl

    with _cache_lock:
        _cache[key] = payload

    return dict(payload)


def _build_payload(prompt_text: str) -> dict:
    return {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt_text
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 4,
            "candidateCount": 1,
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ],
    }


def _extract_text_from_response_json(data: dict) -> str:
    try:
        candidates = data.get("candidates") or []
        chunks = []

        for candidate in candidates:
            content = candidate.get("content") or {}
            parts = content.get("parts") or []
            for part in parts:
                text = part.get("text")
                if text:
                    chunks.append(text)

        return "\n".join(chunks).strip()
    except Exception:
        logger.exception("Не вдалося витягнути текст із Gemini REST response")
        return ""


def _success_result(verdict: str, raw: str, source: str, http_status: int = 200) -> dict:
    return {
        "verdict": verdict,
        "reason": "",
        "source": source,
        "model": _GEMINI_MODEL,
        "api_version": _GEMINI_API_VERSION,
        "raw": (raw or "")[:120],
        "available": True,
        "http_status": http_status,
    }


def _fallback_result(reason: str, source: str, http_status: Optional[int] = None, raw: str = "") -> dict:
    return {
        "verdict": "GO",
        "reason": reason,
        "source": source,
        "model": _GEMINI_MODEL,
        "api_version": _GEMINI_API_VERSION,
        "raw": (raw or "")[:120],
        "available": False,
        "http_status": http_status,
    }


def _parse_gemini_payload(raw: str) -> dict:
    cleaned = (raw or "").strip()
    upper = cleaned.upper()

    if re.search(r"\bBLOCK\b", upper):
        return _success_result("BLOCK", cleaned, "gemini_keyword")

    if re.search(r"\bGO\b", upper):
        return _success_result("GO", cleaned, "gemini_keyword")

    if not cleaned:
        logger.warning("Gemini empty response")
        return _fallback_result(
            reason="Порожня відповідь від Gemini",
            source="fallback_empty",
            http_status=200,
            raw="",
        )

    logger.warning("Gemini malformed response. Raw=%r", cleaned[:120])
    return _fallback_result(
        reason="Некоректний формат відповіді Gemini",
        source="fallback_malformed",
        http_status=200,
        raw=cleaned,
    )


def _rest_call(prompt_text: str, timeout_value) -> tuple[int, str, dict]:
    response = requests.post(
        _GEMINI_ENDPOINT,
        params={"key": GEMINI_API_KEY},
        json=_build_payload(prompt_text),
        timeout=timeout_value,
    )

    body_text = response.text[:500]
    try:
        body_json = response.json()
    except Exception:
        body_json = {}

    return response.status_code, body_text, body_json


def _do_rest_call(pair: str) -> dict:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    prompt_text = _PROMPT.format(pair=pair)

    logger.info(
        "Gemini REST request for %s using model=%s api_version=%s",
        pair,
        _GEMINI_MODEL,
        _GEMINI_API_VERSION,
    )

    try:
        status_code, body_text, body_json = _rest_call(prompt_text, _REQUEST_TIMEOUT)
    except requests.exceptions.Timeout:
        logger.warning("Gemini timeout for %s on first request", pair)
        return _fallback_result(
            reason="Таймаут Gemini",
            source="fallback_timeout",
            http_status=None,
        )
    except requests.exceptions.RequestException as e:
        logger.error("Gemini network error for %s: %s", pair, e)
        return _fallback_result(
            reason="Мережева помилка Gemini",
            source="fallback_network_error",
            http_status=None,
        )

    logger.info(
        "Gemini HTTP for %s: status=%s key=%s",
        pair,
        status_code,
        _mask_key(GEMINI_API_KEY),
    )

    if status_code != 200:
        logger.error(
            "Gemini REST HTTP error for %s: %s %s",
            pair,
            status_code,
            body_text,
        )
        return _fallback_result(
            reason=f"HTTP {status_code} від Gemini",
            source="fallback_http_error",
            http_status=status_code,
            raw=body_text,
        )

    raw = _extract_text_from_response_json(body_json)

    logger.info(
        "Gemini raw response for %s [%s]: %s",
        pair,
        _GEMINI_MODEL,
        raw,
    )

    if raw:
        return _parse_gemini_payload(raw)

    logger.warning("Gemini returned empty text for %s. Retrying with shorter prompt...", pair)

    retry_prompt = f"Asset: {pair}\nReply exactly one word: GO or BLOCK"

    try:
        retry_status, retry_body_text, retry_body_json = _rest_call(retry_prompt, _RETRY_REQUEST_TIMEOUT)
    except requests.exceptions.Timeout:
        logger.warning("Gemini retry timeout for %s", pair)
        return _fallback_result(
            reason="Таймаут Gemini при повторі",
            source="fallback_retry_timeout",
            http_status=None,
        )
    except requests.exceptions.RequestException as e:
        logger.error("Gemini retry network error for %s: %s", pair, e)
        return _fallback_result(
            reason="Мережева помилка Gemini при повторі",
            source="fallback_retry_network_error",
            http_status=None,
        )

    logger.info(
        "Gemini HTTP for %s: status=%s key=%s",
        pair,
        retry_status,
        _mask_key(GEMINI_API_KEY),
    )

    if retry_status != 200:
        logger.error(
            "Gemini retry HTTP error for %s: %s %s",
            pair,
            retry_status,
            retry_body_text,
        )
        return _fallback_result(
            reason=f"HTTP {retry_status} від Gemini при повторі",
            source="fallback_retry_http_error",
            http_status=retry_status,
            raw=retry_body_text,
        )

    retry_raw = _extract_text_from_response_json(retry_body_json)
    logger.info(
        "Gemini retry raw response for %s [%s]: %s",
        pair,
        _GEMINI_MODEL,
        retry_raw,
    )

    return _parse_gemini_payload(retry_raw)


def get_latest_news_sentiment(pair: str) -> str:
    result = _get_cached_or_fresh_sync(pair)
    return result["verdict"]


def get_latest_news_sentiment_async(pair: str) -> Deferred:
    pair = _normalize_pair(pair)

    cached = _get_cached(pair)
    if cached:
        logger.debug(
            "news_filter cache hit for %s (age=%ss, source=%s)",
            pair,
            int(_now() - cached.get("ts", 0)),
            cached.get("source"),
        )
        return succeed(cached)

    if not GEMINI_API_KEY:
        result = _store_cache(
            pair,
            _fallback_result(
                reason="GEMINI_API_KEY не налаштований",
                source="fallback_no_key",
                http_status=None,
            ),
            _ERROR_CACHE_TTL,
        )
        return succeed(result)

    d = deferToThreadPool(
        reactor,
        _blocking_pool(),
        _do_rest_call,
        pair,
    )

    def _cache_success(result: dict):
        ttl = _CACHE_TTL if result.get("available") else _ERROR_CACHE_TTL
        cached_result = _store_cache(pair, result, ttl)
        logger.info(
            "Gemini [%s]: verdict=%s available=%s source=%s status=%s",
            pair,
            cached_result["verdict"],
            cached_result.get("available"),
            cached_result.get("source"),
            cached_result.get("http_status"),
        )
        return cached_result

    def _on_error(failure):
        logger.error("Gemini error for %s: %s", pair, failure.getErrorMessage())
        return _store_cache(
            pair,
            _fallback_result(
                reason="Помилка запиту до Gemini",
                source="fallback_error",
                http_status=None,
            ),
            _ERROR_CACHE_TTL,
        )

    d.addCallbacks(_cache_success, _on_error)
    return d


def _get_cached_or_fresh_sync(pair: str) -> dict:
    pair = _normalize_pair(pair)

    cached = _get_cached(pair)
    if cached:
        return cached

    if not GEMINI_API_KEY:
        return _store_cache(
            pair,
            _fallback_result(
                reason="GEMINI_API_KEY не налаштований",
                source="fallback_no_key",
                http_status=None,
            ),
            _ERROR_CACHE_TTL,
        )

    try:
        result = _do_rest_call(pair)
        ttl = _CACHE_TTL if result.get("available") else _ERROR_CACHE_TTL
        return _store_cache(pair, result, ttl)
    except Exception as e:
        logger.error("Gemini sync error for %s: %s", pair, e)
        return _store_cache(
            pair,
            _fallback_result(
                reason="Помилка запиту до Gemini",
                source="fallback_error",
                http_status=None,
            ),
            _ERROR_CACHE_TTL,
        )


def get_cache_stats() -> dict:
    now = _now()
    with _cache_lock:
        items = dict(_cache)

    fresh = {
        k: v for k, v in items.items()
        if now - v.get("ts", 0) < v.get("_ttl", _CACHE_TTL)
    }
    stale = {
        k: v for k, v in items.items()
        if now - v.get("ts", 0) >= v.get("_ttl", _CACHE_TTL)
    }

    return {
        "fresh": len(fresh),
        "stale": len(stale),
        "total": len(items),
        "model": _GEMINI_MODEL,
        "api_version": _GEMINI_API_VERSION,
        "has_api_key": bool(GEMINI_API_KEY),
        "masked_key": _mask_key(GEMINI_API_KEY),
    }