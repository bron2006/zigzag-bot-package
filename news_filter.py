# news_filter.py
#
# ВИПРАВЛЕННЯ 1: Gemini викликається в окремому потоці (deferToThread)
#                щоб не блокувати Twisted reactor.
# ВИПРАВЛЕННЯ 2: Кеш з TTL 10 хвилин — не викликаємо Gemini частіше
#                ніж раз на 10 хв для одного символу.
# ВИПРАВЛЕННЯ 3: Gemini повертає JSON з verdict + reason,
#                щоб трейдер бачив пояснення.

import os
import json
import time
import logging
from twisted.internet.threads import deferToThread
from google import genai
from google.genai import types

logger = logging.getLogger("news_filter")

_gemini_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# ---------------------------------------------------------------------------
# Кеш результатів: { "EURUSD": {"verdict": "GO", "reason": "...", "ts": 1234} }
# ---------------------------------------------------------------------------
_cache: dict = {}
_CACHE_TTL   = 600   # 10 хвилин

_PROMPT = """You are a financial news risk filter for short-term trading.
Asset: {pair}
Task: Check if there are any high-impact news events, economic releases, or market events in the NEXT 30 MINUTES that would make trading this asset RISKY.

Respond ONLY with valid JSON, no markdown, no explanation outside JSON:
{{"verdict": "GO", "reason": "No major events expected"}}
or
{{"verdict": "BLOCK", "reason": "NFP report in 15 minutes, high volatility expected"}}

verdict must be exactly GO or BLOCK."""


def _call_gemini_sync(pair: str) -> dict:
    """
    Синхронний виклик Gemini — запускається в окремому потоці через deferToThread.
    Повертає dict: {"verdict": "GO"|"BLOCK", "reason": str}
    """
    try:
        response = _gemini_client.models.generate_content(
            model="gemini-flash-latest",
            contents=_PROMPT.format(pair=pair),
            config=types.GenerateContentConfig(
                max_output_tokens=80,
                temperature=0,
            )
        )
        raw = response.text.strip()
        logger.info(f"Gemini raw response for {pair}: {raw}")

        # Чистимо markdown-огорожі якщо є
        raw = raw.replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)

        verdict = str(data.get("verdict", "GO")).upper()
        reason  = str(data.get("reason", ""))
        verdict = "BLOCK" if "BLOCK" in verdict else "GO"

        return {"verdict": verdict, "reason": reason}

    except json.JSONDecodeError:
        # Gemini повернув не-JSON — fallback до простого парсингу
        text = response.text.strip().upper() if 'response' in dir() else ""
        verdict = "BLOCK" if "BLOCK" in text else "GO"
        logger.warning(f"Gemini returned non-JSON for {pair}: {text!r}, using verdict={verdict}")
        return {"verdict": verdict, "reason": ""}

    except Exception as e:
        logger.error(f"Gemini error for {pair}: {e}")
        return {"verdict": "GO", "reason": "API error — defaulting to GO"}


def get_latest_news_sentiment(pair: str):
    """
    ЗАСТАРІЛИЙ синхронний інтерфейс — залишений для сумісності з ручним запитом.
    Для автосканера використовуй get_latest_news_sentiment_async().

    Повертає рядок "GO" або "BLOCK" (зворотна сумісність з analysis.py).
    """
    result = _get_cached_or_fresh_sync(pair)
    return result["verdict"]


def get_latest_news_sentiment_async(pair: str):
    """
    Async версія для автосканера.
    Повертає Deferred → {"verdict": "GO"|"BLOCK", "reason": str}

    Якщо результат є в кеші — повертає одразу без HTTP запиту.
    """
    cached = _cache.get(pair)
    if cached and (time.time() - cached["ts"]) < _CACHE_TTL:
        logger.debug(f"news_filter cache hit for {pair} (age={time.time()-cached['ts']:.0f}s)")
        from twisted.internet.defer import succeed
        return succeed(cached)

    logger.info(f"Gemini async запит для {pair}...")

    def _cache_and_return(result: dict):
        result["ts"] = time.time()
        _cache[pair] = result
        logger.info(f"Gemini [{pair}]: {result['verdict']} — {result['reason']}")
        return result

    def _on_error(failure):
        logger.error(f"deferToThread Gemini error for {pair}: {failure.getErrorMessage()}")
        fallback = {"verdict": "GO", "reason": "API error — defaulting to GO", "ts": time.time()}
        _cache[pair] = fallback
        return fallback

    d = deferToThread(_call_gemini_sync, pair)
    d.addCallback(_cache_and_return)
    d.addErrback(_on_error)
    return d


def _get_cached_or_fresh_sync(pair: str) -> dict:
    """Синхронна версія з кешем — для ручних запитів з Telegram."""
    cached = _cache.get(pair)
    if cached and (time.time() - cached["ts"]) < _CACHE_TTL:
        return cached
    result = _call_gemini_sync(pair)
    result["ts"] = time.time()
    _cache[pair] = result
    return result


def get_cache_stats() -> dict:
    """Для /health endpoint — скільки записів у кеші і які застаріли."""
    now   = time.time()
    fresh = {k: v for k, v in _cache.items() if now - v["ts"] < _CACHE_TTL}
    stale = {k: v for k, v in _cache.items() if now - v["ts"] >= _CACHE_TTL}
    return {"fresh": len(fresh), "stale": len(stale), "total": len(_cache)}
