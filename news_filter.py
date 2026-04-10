# news_filter.py
import logging
import os
import re
import threading
import time
from typing import Dict, Optional

import requests
from twisted.internet import reactor
from twisted.internet.defer import Deferred, succeed
from twisted.internet.threads import deferToThreadPool

from state import app_state

logger = logging.getLogger("news_filter")

_OPENROUTER_API_KEY = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_MODELS = [
    (os.environ.get("OPENROUTER_MODEL_PRIMARY") or "google/gemini-2.0-flash-001").strip(),
    (os.environ.get("OPENROUTER_MODEL_FALLBACK") or "openai/gpt-4o-mini").strip(),
]

_cache: Dict[str, dict] = {}
_cache_lock = threading.RLock()

_CACHE_TTL = 600
_ERROR_CACHE_TTL = 60

_REQUEST_TIMEOUT = (5, 15)
_RETRY_TIMEOUT = (5, 10)

_SYSTEM_PROMPT = (
    "You are a short-term trading news gate. "
    "Reply with EXACTLY ONE WORD only: GO or BLOCK."
)

_USER_PROMPT = (
    "Asset: {pair}\n"
    "Check if there are dangerous high-impact news or market-moving events "
    "in the next 30 minutes.\n"
    "Reply exactly one word: GO or BLOCK."
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


def _success(verdict: str, *, model: str, raw: str = "", http_status: int = 200) -> dict:
    return {
        "verdict": verdict,
        "reason": "",
        "available": True,
        "source": "openrouter",
        "model": model,
        "http_status": http_status,
        "raw": (raw or "")[:200],
    }


def _fallback(reason: str, *, source: str, model: Optional[str] = None, http_status: Optional[int] = None, raw: str = "") -> dict:
    return {
        "verdict": "GO",
        "reason": reason,
        "available": False,
        "source": source,
        "model": model,
        "http_status": http_status,
        "raw": (raw or "")[:200],
    }


def _extract_text_from_openrouter(data: dict) -> str:
    try:
        choices = data.get("choices") or []
        if not choices:
            return ""

        message = choices[0].get("message") or {}
        content = message.get("content", "")

        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            chunks = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if text:
                        chunks.append(text)
            return "\n".join(chunks).strip()

        return ""
    except Exception:
        logger.exception("Не вдалося витягнути текст із OpenRouter response")
        return ""


def _parse_verdict(text: str, model: str) -> dict:
    cleaned = (text or "").strip()
    upper = cleaned.upper()

    if re.search(r"\bBLOCK\b", upper):
        return _success("BLOCK", model=model, raw=cleaned)

    if re.search(r"\bGO\b", upper):
        return _success("GO", model=model, raw=cleaned)

    if not cleaned:
        logger.warning("OpenRouter returned empty response")
        return _fallback(
            "Порожня відповідь від моделі",
            source="fallback_empty",
            model=model,
            http_status=200,
        )

    logger.warning("OpenRouter malformed response: %r", cleaned[:200])
    return _fallback(
        "Некоректний формат відповіді моделі",
        source="fallback_malformed",
        model=model,
        http_status=200,
        raw=cleaned,
    )


def _call_model_once(model: str, pair: str, prompt: str, timeout_value) -> dict:
    if not _OPENROUTER_API_KEY:
        return _fallback(
            "OPENROUTER_API_KEY не налаштований",
            source="fallback_no_key",
            model=model,
        )

    headers = {
        "Authorization": f"Bearer {_OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://zigzag-bot-package.fly.dev",
        "X-Title": "zigzag-bot",
    }

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": 4,
    }

    response = requests.post(
        _OPENROUTER_URL,
        headers=headers,
        json=body,
        timeout=timeout_value,
    )

    logger.info(
        "OpenRouter [%s] model=%s status=%s key=%s",
        pair,
        model,
        response.status_code,
        _mask_key(_OPENROUTER_API_KEY),
    )

    body_text = response.text[:500]

    if response.status_code != 200:
        return _fallback(
            f"http_{response.status_code}",
            source="fallback_http_error",
            model=model,
            http_status=response.status_code,
            raw=body_text,
        )

    try:
        data = response.json()
    except Exception:
        return _fallback(
            "invalid_json_response",
            source="fallback_invalid_json",
            model=model,
            http_status=200,
            raw=body_text,
        )

    text = _extract_text_from_openrouter(data)
    logger.info("OpenRouter raw response for %s [%s]: %s", pair, model, text)

    return _parse_verdict(text, model)


def _call_openrouter_sync(pair: str) -> dict:
    pair = _normalize_pair(pair)

    if not _OPENROUTER_API_KEY:
        logger.warning("OPENROUTER_API_KEY не встановлений — fallback GO")
        return _fallback(
            "OPENROUTER_API_KEY не налаштований",
            source="fallback_no_key",
            model=None,
        )

    prompt = _USER_PROMPT.format(pair=pair)
    last_result = None

    for model in [m for m in _MODELS if m]:
        for attempt in range(3):
            try:
                timeout_value = _REQUEST_TIMEOUT if attempt == 0 else _RETRY_TIMEOUT
                result = _call_model_once(model, pair, prompt, timeout_value)

                if result.get("available"):
                    logger.info(
                        "OpenRouter [%s]: %s (model=%s)",
                        pair,
                        result["verdict"],
                        model,
                    )
                    return result

                status = result.get("http_status")
                reason = result.get("reason", "")
                last_result = result

                if status in (429, 500, 502, 503, 504):
                    wait = 2 ** attempt
                    logger.warning(
                        "OpenRouter [%s] model=%s status=%s reason=%s wait=%ss attempt=%s/3",
                        pair,
                        model,
                        status,
                        reason,
                        wait,
                        attempt + 1,
                    )
                    time.sleep(wait)
                    continue

                if status == 200 and reason in (
                    "Порожня відповідь від моделі",
                    "Некоректний формат відповіді моделі",
                    "invalid_json_response",
                ):
                    logger.warning(
                        "OpenRouter [%s] model=%s returned unusable 200 response: %s",
                        pair,
                        model,
                        reason,
                    )
                    break

                logger.warning(
                    "OpenRouter [%s] model=%s fallback result: status=%s reason=%s",
                    pair,
                    model,
                    status,
                    reason,
                )
                break

            except requests.exceptions.Timeout:
                wait = 2 ** attempt
                logger.warning(
                    "OpenRouter [%s] model=%s timeout wait=%ss attempt=%s/3",
                    pair,
                    model,
                    wait,
                    attempt + 1,
                )
                last_result = _fallback(
                    "timeout",
                    source="fallback_timeout",
                    model=model,
                    http_status=None,
                )
                time.sleep(wait)
                continue

            except Exception as e:
                logger.error("OpenRouter [%s] model=%s exception: %s", pair, model, e)
                last_result = _fallback(
                    str(e),
                    source="fallback_exception",
                    model=model,
                    http_status=None,
                )
                break

    logger.warning("OpenRouter [%s]: всі моделі недоступні — fallback GO", pair)
    return last_result or _fallback(
        "all_models_unavailable",
        source="fallback_all_models_unavailable",
        model=None,
        http_status=None,
    )


def get_latest_news_sentiment_async(pair: str):
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

    def _store(result: dict):
        ttl = _CACHE_TTL if result.get("available") else _ERROR_CACHE_TTL
        return _store_cache(pair, result, ttl)

    def _on_error(failure):
        logger.error(
            "deferToThreadPool OpenRouter error for %s: %s",
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
        _call_openrouter_sync,
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

    result = _call_openrouter_sync(pair)
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
        "has_api_key": bool(_OPENROUTER_API_KEY),
        "masked_key": _mask_key(_OPENROUTER_API_KEY),
    }