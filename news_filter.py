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
    import google.generativeai as genai
    from google.generativeai.types import (
        GenerationConfig,
        HarmBlockThreshold,
        HarmCategory,
    )
    _GENAI_IMPORT_ERROR = None
except Exception as e:
    genai = None
    GenerationConfig = None
    HarmBlockThreshold = None
    HarmCategory = None
    _GENAI_IMPORT_ERROR = e

_GEMINI_MODEL = "gemini-flash-latest"

_cache: Dict[str, dict] = {}
_cache_lock = threading.RLock()
_model_local = threading.local()

_CACHE_TTL = 600
_ERROR_CACHE_TTL = 30

_PROMPT = """You are a short-term trading news gate.

Asset: {pair}

Check if there are dangerous high-impact news or market-moving events in the next 30 minutes.

Reply with EXACTLY ONE WORD:
GO
or
BLOCK
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


def _build_model():
    if _GENAI_IMPORT_ERROR is not None:
        raise RuntimeError(f"google.generativeai import failed: {_GENAI_IMPORT_ERROR}")

    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    genai.configure(api_key=GEMINI_API_KEY)

    safety_settings = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    model = genai.GenerativeModel(
        model_name=_GEMINI_MODEL,
        safety_settings=safety_settings,
        generation_config=GenerationConfig(
            max_output_tokens=4,
            temperature=0,
            candidate_count=1,
        ),
    )
    return model


def _get_thread_local_model():
    model = getattr(_model_local, "model", None)
    if model is not None:
        return model

    model = _build_model()
    _model_local.model = model
    return model


def _extract_text(response) -> str:
    # 1. Найпростіший шлях
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text.strip()

    # 2. Через candidates/content/parts
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
        logger.exception("Не вдалося витягнути текст із legacy Gemini response")
        return ""


def _log_response_meta(response, pair: str) -> None:
    try:
        prompt_feedback = getattr(response, "prompt_feedback", None)
        candidates = getattr(response, "candidates", None)
        logger.info(
            "Gemini meta for %s: prompt_feedback=%r candidates_count=%s",
            pair,
            prompt_feedback,
            len(candidates or []),
        )
    except Exception:
        logger.exception("Не вдалося залогувати Gemini meta")


def _parse_gemini_payload(raw: str) -> dict:
    cleaned = (raw or "").strip()
    upper = cleaned.upper()

    if re.search(r"\bBLOCK\b", upper):
        return {
            "verdict": "BLOCK",
            "reason": "",
            "source": "gemini_keyword",
            "model": _GEMINI_MODEL,
            "raw": cleaned[:120],
        }

    if re.search(r"\bGO\b", upper):
        return {
            "verdict": "GO",
            "reason": "",
            "source": "gemini_keyword",
            "model": _GEMINI_MODEL,
            "raw": cleaned[:120],
        }

    logger.warning("Gemini malformed/empty response, fallback to GO. Raw=%r", cleaned[:120])

    return {
        "verdict": "GO",
        "reason": "Malformed or empty model output",
        "source": "fallback_malformed",
        "model": _GEMINI_MODEL,
        "raw": cleaned[:120],
    }


def _call_gemini_sync(pair: str) -> dict:
    model = _get_thread_local_model()

    logger.info("Gemini request for %s using legacy SDK model=%s", pair, _GEMINI_MODEL)

    response = model.generate_content(
        _PROMPT.format(pair=pair),
        request_options={"timeout": 20},
    )

    _log_response_meta(response, pair)
    raw = _extract_text(response)

    logger.info("Gemini raw response for %s [%s]: %s", pair, _GEMINI_MODEL, raw)

    # Один повторний шанс, якщо модель повернула порожнечу
    if not raw:
        logger.warning("Gemini empty response for %s. Retry once...", pair)
        response_retry = model.generate_content(
            f"Asset: {pair}\nReply one word only: GO or BLOCK",
            request_options={"timeout": 20},
        )
        _log_response_meta(response_retry, pair)
        raw = _extract_text(response_retry)
        logger.info("Gemini retry raw response for %s [%s]: %s", pair, _GEMINI_MODEL, raw)

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
        ttl = _CACHE_TTL if str(result.get("source", "")).startswith("gemini") else _ERROR_CACHE_TTL
        cached_result = _store_cache(pair, result, ttl)
        logger.info(
            "Gemini [%s]: %s (source=%s, model=%s)",
            pair,
            cached_result["verdict"],
            cached_result.get("source"),
            cached_result.get("model"),
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
            },
            _ERROR_CACHE_TTL,
        )

    try:
        result = _call_gemini_sync(pair)
        ttl = _CACHE_TTL if str(result.get("source", "")).startswith("gemini") else _ERROR_CACHE_TTL
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
        "sdk_ok": _GENAI_IMPORT_ERROR is None,
    }