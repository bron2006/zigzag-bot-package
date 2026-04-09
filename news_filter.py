import logging
import threading
import time
from typing import Dict, Optional

import requests as _requests
from twisted.internet import reactor
from twisted.internet.defer import Deferred, succeed
from twisted.internet.threads import deferToThreadPool

from config import GEMINI_API_KEY
from state import app_state

logger = logging.getLogger("news_filter")

# Стабільні моделі в порядку пріоритету
_MODELS = [
    "gemini-1.5-flash-8b",
    "gemini-1.5-flash",
    "gemini-2.0-flash-lite",
]

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

_cache: Dict[str, dict] = {}
_cache_lock = threading.RLock()

_CACHE_TTL = 600
_ERROR_CACHE_TTL = 60

_PROMPT = (
    "Is there a major economic news event or release in the NEXT 30 MINUTES for {pair}? "
    "Reply with exactly one word: GO or BLOCK"
)


def _blocking_pool():
    return app_state.blocking_pool or reactor.getThreadPool()


def _normalize_pair(pair: str) -> str:
    return (pair or "").replace("/", "").upper().strip()


def _now() -> float:
    return time.time()


def _mask_key(value: Optional[str]) -> str:
    if not value:
        return "<empty>"
    if len(value) < 10:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _get_api_key() -> str:
    return (GEMINI_API_KEY or "").strip()


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


def _success(verdict: str, *, model: str, raw: str = "") -> dict:
    return {
        "verdict": verdict,
        "reason": "",
        "available": True,
        "source": "gemini",
        "model": model,
        "http_status": 200,
        "raw": (raw or "")[:120],
    }


def _fallback(reason: str, *, source: str, model: Optional[str] = None, http_status: Optional[int] = None, raw: str = "") -> dict:
    return {
        "verdict": "GO",
        "reason": reason,
        "available": False,
        "source": source,
        "model": model,
        "http_status": http_status,
        "raw": (raw or "")[:120],
    }


def _extract_text_from_json(data: dict) -> str:
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
        logger.exception("Не вдалося витягнути текст із Gemini response JSON")
        return ""


def _parse_text_to_verdict(text: str, model: str) -> dict:
    upper = (text or "").strip().upper()

    if "BLOCK" in upper:
        return _success("BLOCK", model=model, raw=text)

    if "GO" in upper:
        return _success("GO", model=model, raw=text)

    return _fallback(
        "empty_or_unrecognized_response",
        source="fallback_malformed",
        model=model,
        http_status=200,
        raw=text,
    )


def _call_model_once(model: str, pair: str, prompt: str, timeout: int = 15) -> dict:
    api_key = _get_api_key()
    if not api_key:
        return _fallback("no_api_key", source="fallback_no_key", model=model)

    url = _BASE_URL.format(model=model)
    params = {"key": api_key}
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 10,
            "temperature": 0,
            "candidateCount": 1,
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ],
    }

    resp = _requests.post(url, params=params, json=body, timeout=timeout)
    logger.info(
        "Gemini [%s] model=%s status=%s key=%s",
        pair,
        model,
        resp.status_code,
        _mask_key(api_key),
    )

    if resp.status_code != 200:
        return _fallback(
            f"http_{resp.status_code}",
            source="fallback_http_error",
            model=model,
            http_status=resp.status_code,
            raw=resp.text[:200],
        )

    try:
        data = resp.json()
    except Exception:
        return _fallback(
            "invalid_json_response",
            source="fallback_invalid_json",
            model=model,
            http_status=200,
            raw=resp.text[:200],
        )

    text = _extract_text_from_json(data)
    logger.info("Gemini raw response for %s [%s]: %s", pair, model, text)

    return _parse_text_to_verdict(text, model)


def _call_gemini_sync(pair: str) -> dict:
    api_key = _get_api_key()
    if not api_key:
        logger.warning("GEMINI_API_KEY не встановлений — повертаємо GO")
        return _fallback("no_api_key", source="fallback_no_key", model=None)

    pair = _normalize_pair(pair)
    prompt = _PROMPT.format(pair=pair)

    last_nonfatal_result = None

    for model in _MODELS:
        for attempt in range(3):
            try:
                result = _call_model_once(model, pair, prompt, timeout=15)

                # Успішна відповідь із verdict
                if result.get("available"):
                    logger.info(
                        "Gemini [%s]: %s (model=%s)",
                        pair,
                        result["verdict"],
                        model,
                    )
                    return result

                status = result.get("http_status")
                reason = result.get("reason", "")

                # Якщо 429/503 — retry/backoff
                if status in (429, 503):
                    wait = 2 ** attempt
                    logger.warning(
                        "Gemini [%s] model=%s status=%s reason=%s wait=%ss attempt=%s/3",
                        pair,
                        model,
                        status,
                        reason,
                        wait,
                        attempt + 1,
                    )
                    last_nonfatal_result = result
                    time.sleep(wait)
                    continue

                # Якщо 200, але порожньо/криво — пробуємо іншу модель
                if status == 200 and reason in ("empty_or_unrecognized_response", "invalid_json_response"):
                    logger.warning(
                        "Gemini [%s] model=%s returned unusable 200 response: %s",
                        pair,
                        model,
                        reason,
                    )
                    last_nonfatal_result = result
                    break

                # Інші HTTP-помилки — наступна модель
                logger.warning(
                    "Gemini [%s] model=%s fallback result: status=%s reason=%s",
                    pair,
                    model,
                    status,
                    reason,
                )
                last_nonfatal_result = result
                break

            except _requests.exceptions.Timeout:
                wait = 2 ** attempt
                logger.warning(
                    "Gemini [%s] model=%s timeout wait=%ss attempt=%s/3",
                    pair,
                    model,
                    wait,
                    attempt + 1,
                )
                last_nonfatal_result = _fallback(
                    "timeout",
                    source="fallback_timeout",
                    model=model,
                    http_status=None,
                )
                time.sleep(wait)
                continue

            except Exception as e:
                logger.error("Gemini [%s] model=%s exception: %s", pair, model, e)
                last_nonfatal_result = _fallback(
                    str(e),
                    source="fallback_exception",
                    model=model,
                    http_status=None,
                )
                break

    logger.warning("Gemini [%s]: всі моделі недоступні — fallback GO", pair)
    return last_nonfatal_result or _fallback(
        "all_models_unavailable",
        source="fallback_all_models_unavailable",
        model=None,
        http_status=None,
    )


def get_latest_news_sentiment_async(pair: str):
    pair = _normalize_pair(pair)

    cached = _get_cached(pair)
    if cached:
        logger.debug("news_filter cache hit for %s", pair)
        return succeed(cached)

    def _store(result: dict):
        ttl = _CACHE_TTL if result.get("available") else _ERROR_CACHE_TTL
        return _store_cache(pair, result, ttl)

    def _on_error(failure):
        logger.error(
            "deferToThreadPool Gemini error for %s: %s",
            pair,
            failure.getErrorMessage(),
        )
        fallback = _fallback(
            "thread_error",
            source="fallback_thread_error",
            model=None,
            http_status=None,
        )
        return _store_cache(pair, fallback, _ERROR_CACHE_TTL)

    d = deferToThreadPool(
        reactor,
        _blocking_pool(),
        _call_gemini_sync,
        pair,
    )
    d.addCallback(_store)
    d.addErrback(_on_error)
    return d


def get_latest_news_sentiment(pair: str) -> str:
    pair = _normalize_pair(pair)

    cached = _get_cached(pair)
    if cached:
        return cached["verdict"]

    result = _call_gemini_sync(pair)
    ttl = _CACHE_TTL if result.get("available") else _ERROR_CACHE_TTL
    _store_cache(pair, result, ttl)
    return result["verdict"]


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
        "models": list(_MODELS),
        "has_api_key": bool(_get_api_key()),
        "masked_key": _mask_key(_get_api_key()),
    }