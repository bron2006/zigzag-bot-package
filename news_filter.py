# news_filter.py
import json
import logging
import os
import threading
import time
from typing import Dict, Optional

from google import genai
from google.genai import types
from twisted.internet import reactor
from twisted.internet.defer import Deferred, succeed
from twisted.internet.threads import deferToThreadPool

from config import GEMINI_API_KEY
from state import app_state

logger = logging.getLogger("news_filter")

_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

_cache: Dict[str, dict] = {}
_cache_lock = threading.RLock()
_client_local = threading.local()

_CACHE_TTL = 600
_ERROR_CACHE_TTL = 30

_PROMPT = """You are a financial news risk filter for short-term trading.
Asset: {pair}
Task: Check if there are any high-impact news events, economic releases, or market events in the NEXT 30 MINUTES that would make trading this asset RISKY.

Respond ONLY with valid JSON, no markdown, no explanation outside JSON:
{{"verdict": "GO", "reason": "No major events expected"}}
or
{{"verdict": "BLOCK", "reason": "NFP report in 15 minutes, high volatility expected"}}

verdict must be exactly GO or BLOCK.
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


def _get_thread_local_client():
    client = getattr(_client_local, "client", None)
    if client is not None:
        return client

    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    client = genai.Client(api_key=GEMINI_API_KEY)
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
    cleaned = (raw or "").strip()
    cleaned = cleaned.replace("```json", "").replace("```", "").strip()

    if not cleaned:
        return {"verdict": "GO", "reason": "Empty model response", "source": "fallback"}

    try:
        data = json.loads(cleaned)
        verdict = str(data.get("verdict", "GO")).upper().strip()
        reason = str(data.get("reason", "")).strip()
        verdict = "BLOCK" if verdict == "BLOCK" else "GO"
        return {"verdict": verdict, "reason": reason, "source": "gemini"}
    except json.JSONDecodeError:
        upper = cleaned.upper()
        verdict = "BLOCK" if "BLOCK" in upper else "GO"
        return {
            "verdict": verdict,
            "reason": cleaned[:240],
            "source": "fallback_parse",
        }


def _call_gemini_sync(pair: str) -> dict:
    client = _get_thread_local_client()

    response = client.models.generate_content(
        model=_GEMINI_MODEL,
        contents=_PROMPT.format(pair=pair),
        config=types.GenerateContentConfig(
            max_output_tokens=120,
            temperature=0,
        ),
    )

    raw = _extract_text(response)
    logger.info(f"Gemini raw response for {pair}: {raw}")
    return _parse_gemini_payload(raw)


def get_latest_news_sentiment(pair: str) -> str:
    result = _get_cached_or_fresh_sync(pair)
    return result["verdict"]


def get_latest_news_sentiment_async(pair: str) -> Deferred:
    pair = _normalize_pair(pair)
    cached = _get_cached(pair)
    if cached:
        logger.debug(
            f"news_filter cache hit for {pair} "
            f"(age={_now() - cached.get('ts', 0):.0f}s, source={cached.get('source')})"
        )
        return succeed(cached)

    if not GEMINI_API_KEY:
        result = _store_cache(
            pair,
            {
                "verdict": "GO",
                "reason": "GEMINI_API_KEY не налаштований",
                "source": "fallback_no_key",
            },
            _ERROR_CACHE_TTL,
        )
        return succeed(result)

    logger.info(f"Gemini async запит для {pair} через blocking pool...")

    d = deferToThreadPool(
        reactor,
        _blocking_pool(),
        _call_gemini_sync,
        pair,
    )
    d.addTimeout(20, reactor)

    def _cache_success(result: dict):
        ttl = _CACHE_TTL if result.get("source") == "gemini" else _ERROR_CACHE_TTL
        cached = _store_cache(pair, result, ttl)
        logger.info(
            f"Gemini [{pair}]: {cached['verdict']} — {cached.get('reason', '')} "
            f"(source={cached.get('source')})"
        )
        return cached

    def _on_error(failure):
        logger.error(f"Gemini error for {pair}: {failure.getErrorMessage()}")
        return _store_cache(
            pair,
            {
                "verdict": "GO",
                "reason": "API error — temporary fail-open",
                "source": "fallback_error",
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
            },
            _ERROR_CACHE_TTL,
        )

    try:
        result = _call_gemini_sync(pair)
        ttl = _CACHE_TTL if result.get("source") == "gemini" else _ERROR_CACHE_TTL
        return _store_cache(pair, result, ttl)
    except Exception as e:
        logger.error(f"Gemini sync error for {pair}: {e}")
        return _store_cache(
            pair,
            {
                "verdict": "GO",
                "reason": "API error — temporary fail-open",
                "source": "fallback_error",
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
    }