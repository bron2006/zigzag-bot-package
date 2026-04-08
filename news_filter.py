import logging
import re
import threading
import time
from typing import Dict, Optional

from twisted.internet import reactor
from twisted.internet.defer import Deferred, succeed
from twisted.internet.threads import deferToThreadPool

from config import GEMINI_API_KEY
from state import app_state

logger = logging.getLogger("news_filter")

try:
    from google import genai
    from google.genai import types
    _GENAI_IMPORT_ERROR = None
except Exception as e:
    genai = None
    types = None
    _GENAI_IMPORT_ERROR = e

_GEMINI_MODEL = "gemini-flash-latest"
_GEMINI_API_VERSION = "v1beta"

_cache: Dict[str, dict] = {}
_cache_lock = threading.RLock()
_client_local = threading.local()

_CACHE_TTL = 600
_ERROR_CACHE_TTL = 30

# НАВМИСНО МАКСИМАЛЬНО ПРОСТИЙ ПРОМПТ
_PROMPT = """You are a news risk filter for short-term trading.

Asset: {pair}

Check whether there are high-impact news/events in the next 30 minutes that make trading risky.

Reply with EXACTLY ONE WORD ONLY:
GO
or
BLOCK

Do not output JSON.
Do not explain.
Do not add punctuation.
Do not add markdown.
"""


def _blocking_pool():
    return app_state.blocking_pool or reactor.getThreadPool()


def _now() -> float:
    return time.time()


def _normalize_pair(pair: str) -> str:
    return (pair or "").replace("/", "").upper().strip()


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


def _build_client():
    if _GENAI_IMPORT_ERROR is not None:
        raise RuntimeError(f"google-genai import failed: {_GENAI_IMPORT_ERROR}")

    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    return genai.Client(
        api_key=GEMINI_API_KEY,
        http_options=types.HttpOptions(api_version=_GEMINI_API_VERSION),
    )


def _get_thread_local_client():
    client = getattr(_client_local, "client", None)
    if client is not None:
        return client

    client = _build_client()
    _client_local.client = client
    return client


def _extract_text(response) -> str:
    text = getattr(response, "text", None)
    if text:
        return text.strip()

    try:
        candidates = getattr(response, "candidates", None) or []
        chunks = []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) or []
            for part in parts:
                part_text = getattr(part, "text", None)
                if part_text:
                    chunks.append(part_text)
        return "\n".join(chunks).strip()
    except Exception:
        logger.exception("Не вдалося витягнути текст із Gemini response")
        return ""


def _parse_gemini_payload(raw: str) -> dict:
    """
    Максимально толерантний парсер.
    Шукає BLOCK/GO у будь-якому тексті.
    Навіть якщо модель повернула обірваний JSON типу:
    {"verdict": "
    — ми не падаємо.
    """
    cleaned = (raw or "").strip()
    upper = cleaned.upper()

    # 1. Найсуворіше правило: якщо є BLOCK — це BLOCK
    if "BLOCK" in upper:
        return {
            "verdict": "BLOCK",
            "reason": "",
            "source": "gemini_keyword",
            "model": _GEMINI_MODEL,
            "api_version": _GEMINI_API_VERSION,
            "raw": cleaned[:120],
        }

    # 2. Якщо є окреме слово GO — це GO
    if re.search(r"\bGO\b", upper):
        return {
            "verdict": "GO",
            "reason": "",
            "source": "gemini_keyword",
            "model": _GEMINI_MODEL,
            "api_version": _GEMINI_API_VERSION,
            "raw": cleaned[:120],
        }

    # 3. Якщо модель повернула щось дивне/обірване — fail-open, але без сміття в reason
    logger.warning("Gemini malformed response, fallback to GO. Raw=%r", cleaned[:120])

    return {
        "verdict": "GO",
        "reason": "Malformed model output",
        "source": "fallback_malformed",
        "model": _GEMINI_MODEL,
        "api_version": _GEMINI_API_VERSION,
        "raw": cleaned[:120],
    }


def _call_gemini_sync(pair: str) -> dict:
    client = _get_thread_local_client()

    logger.info(
        "Gemini request for %s using model=%s api_version=%s",
        pair,
        _GEMINI_MODEL,
        _GEMINI_API_VERSION,
    )

    response = client.models.generate_content(
        model=_GEMINI_MODEL,
        contents=_PROMPT.format(pair=pair),
        config=types.GenerateContentConfig(
            max_output_tokens=8,
            temperature=0,
        ),
    )

    raw = _extract_text(response)
    logger.info("Gemini raw response for %s [%s]: %s", pair, _GEMINI_MODEL, raw)

    return _parse_gemini_payload(raw)


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
            {
                "verdict": "GO",
                "reason": "GEMINI_API_KEY не налаштований",
                "source": "fallback_no_key",
                "model": _GEMINI_MODEL,
                "api_version": _GEMINI_API_VERSION,
            },
            _ERROR_CACHE_TTL,
        )
        return succeed(result)

    d = deferToThreadPool(
        reactor,
        _blocking_pool(),
        _call_gemini_sync,
        pair,
    )

    def _cache_success(result: dict):
        ttl = _CACHE_TTL if result.get("source", "").startswith("gemini") else _ERROR_CACHE_TTL
        cached_result = _store_cache(pair, result, ttl)
        logger.info(
            "Gemini [%s]: %s (source=%s, model=%s, api_version=%s)",
            pair,
            cached_result["verdict"],
            cached_result.get("source"),
            cached_result.get("model"),
            cached_result.get("api_version"),
        )
        return cached_result

    def _on_error(failure):
        logger.error("Gemini error for %s: %s", pair, failure.getErrorMessage())
        return _store_cache(
            pair,
            {
                "verdict": "GO",
                "reason": "API error — temporary fail-open",
                "source": "fallback_error",
                "model": _GEMINI_MODEL,
                "api_version": _GEMINI_API_VERSION,
            },
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
            {
                "verdict": "GO",
                "reason": "GEMINI_API_KEY не налаштований",
                "source": "fallback_no_key",
                "model": _GEMINI_MODEL,
                "api_version": _GEMINI_API_VERSION,
            },
            _ERROR_CACHE_TTL,
        )

    try:
        result = _call_gemini_sync(pair)
        ttl = _CACHE_TTL if result.get("source", "").startswith("gemini") else _ERROR_CACHE_TTL
        return _store_cache(pair, result, ttl)
    except Exception as e:
        logger.error("Gemini sync error for %s: %s", pair, e)
        return _store_cache(
            pair,
            {
                "verdict": "GO",
                "reason": "API error — temporary fail-open",
                "source": "fallback_error",
                "model": _GEMINI_MODEL,
                "api_version": _GEMINI_API_VERSION,
            },
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
        "sdk_ok": _GENAI_IMPORT_ERROR is None,
    }