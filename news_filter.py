import json
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
_ERROR_CACHE_TTL = 30

_PROMPT = """You are a short-term trading news gate.

Asset: {pair}

Check if there are dangerous high-impact news or market-moving events in the next 30 minutes.

Reply with EXACTLY ONE WORD:
GO
or
BLOCK
"""

_REQUEST_TIMEOUT = 20


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


def _build_payload(pair: str) -> dict:
    return {
        "contents": [
            {
                "parts": [
                    {
                        "text": _PROMPT.format(pair=pair)
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 4,
            "candidateCount": 1,
            "responseMimeType": "text/plain",
        },
        "safetySettings": [
            {
                "category": "HARM_CATEGORY_HARASSMENT",
                "threshold": "BLOCK_NONE",
            },
            {
                "category": "HARM_CATEGORY_HATE_SPEECH",
                "threshold": "BLOCK_NONE",
            },
            {
                "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "threshold": "BLOCK_NONE",
            },
            {
                "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                "threshold": "BLOCK_NONE",
            },
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


def _parse_gemini_payload(raw: str) -> dict:
    cleaned = (raw or "").strip()
    upper = cleaned.upper()

    if re.search(r"\bBLOCK\b", upper):
        return {
            "verdict": "BLOCK",
            "reason": "",
            "source": "gemini_keyword",
            "model": _GEMINI_MODEL,
            "api_version": _GEMINI_API_VERSION,
            "raw": cleaned[:120],
        }

    if re.search(r"\bGO\b", upper):
        return {
            "verdict": "GO",
            "reason": "",
            "source": "gemini_keyword",
            "model": _GEMINI_MODEL,
            "api_version": _GEMINI_API_VERSION,
            "raw": cleaned[:120],
        }

    logger.warning("Gemini malformed/empty response, fallback to GO. Raw=%r", cleaned[:120])
    return {
        "verdict": "GO",
        "reason": "Malformed or empty model output",
        "source": "fallback_malformed",
        "model": _GEMINI_MODEL,
        "api_version": _GEMINI_API_VERSION,
        "raw": cleaned[:120],
    }


def _do_rest_call(pair: str) -> dict:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    payload = _build_payload(pair)

    logger.info(
        "Gemini REST request for %s using model=%s api_version=%s",
        pair,
        _GEMINI_MODEL,
        _GEMINI_API_VERSION,
    )

    response = requests.post(
        _GEMINI_ENDPOINT,
        params={"key": GEMINI_API_KEY},
        json=payload,
        timeout=_REQUEST_TIMEOUT,
    )

    if not response.ok:
        logger.error(
            "Gemini REST HTTP error for %s: %s %s",
            pair,
            response.status_code,
            response.text[:500],
        )
        response.raise_for_status()

    data = response.json()
    raw = _extract_text_from_response_json(data)

    logger.info(
        "Gemini raw response for %s [%s]: %s",
        pair,
        _GEMINI_MODEL,
        raw,
    )

    if not raw:
        logger.warning("Gemini returned empty text for %s. Retrying with shorter prompt...", pair)

        retry_payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": f"Asset: {pair}\nReply exactly one word: GO or BLOCK"
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 4,
                "candidateCount": 1,
                "responseMimeType": "text/plain",
            },
            "safetySettings": payload["safetySettings"],
        }

        retry_response = requests.post(
            _GEMINI_ENDPOINT,
            params={"key": GEMINI_API_KEY},
            json=retry_payload,
            timeout=_REQUEST_TIMEOUT,
        )

        if retry_response.ok:
            retry_data = retry_response.json()
            raw = _extract_text_from_response_json(retry_data)
            logger.info(
                "Gemini retry raw response for %s [%s]: %s",
                pair,
                _GEMINI_MODEL,
                raw,
            )
        else:
            logger.error(
                "Gemini retry HTTP error for %s: %s %s",
                pair,
                retry_response.status_code,
                retry_response.text[:500],
            )

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
        _do_rest_call,
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
        result = _do_rest_call(pair)
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
    }