# news_filter.py
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import requests
from twisted.internet import reactor
from twisted.internet.defer import Deferred, succeed
from twisted.internet.threads import deferToThreadPool

from locales import localize_reason, normalize_lang
from state import app_state

logger = logging.getLogger("news_filter")

_cache: Dict[str, dict] = {}
_cache_lock = threading.RLock()

_CACHE_TTL = 600
_ERROR_CACHE_TTL = 60
_CALENDAR_CACHE_TTL = 300


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except (TypeError, ValueError):
        logger.warning("%s має некоректне значення, використовую %s", name, default)
        return default


# 2026-08-10: tool.forex replaced its server-rendered <div class="event-row">
# markup with an Astro/client-hydrated page that fetches a JSON API
# (`/api/calendar?from=YYYY-MM-DD&to=YYYY-MM-DD`) and renders `<li aria-
# label="...">` client-side. The old regex-based HTML parser silently
# returned 0 events for 10+ hours because none of its expected class names
# exist anymore - and thanks to fail-open, that looked identical to "no
# relevant news" rather than "the filter is broken". Switched to calling
# the JSON API directly instead of scraping rendered HTML - see
# _parse_calendar_events().
_CALENDAR_URL = (
    os.environ.get("NEWS_CALENDAR_URL")
    or "https://tool.forex/api/calendar"
).strip()
_NEWS_BLOCK_BEFORE_MINUTES = _env_int("NEWS_BLOCK_BEFORE_MINUTES", 15)
_NEWS_BLOCK_AFTER_MINUTES = _env_int("NEWS_BLOCK_AFTER_MINUTES", 30)
_NEWS_BLOCK_IMPACTS = {
    item.strip().upper()
    for item in (os.environ.get("NEWS_BLOCK_IMPACTS") or "HIGH").split(",")
    if item.strip()
}

# tool.forex's `importance` field is documented (in its own frontend JS) as
# a 0-3 scale ("", "★", "★★", "★★★"), but live-checked against a 90-day
# window (2026-08-10) every single event - including Non-Farm Payrolls and
# FOMC Minutes - came back importance=1; 2 and 3 never appeared. Mapping
# only 2/3 to HIGH would make _NEWS_BLOCK_IMPACTS={"HIGH"} match nothing
# against real data, silently reproducing the same "filter does nothing"
# failure this fix addresses. Until tool.forex is observed actually
# varying this field, treat any returned event (importance>=1) as HIGH.
_CALENDAR_IMPORTANCE_TO_IMPACT = {0: "LOW", 1: "HIGH", 2: "HIGH", 3: "HIGH"}

_calendar_cache: dict = {"ts": 0.0, "events": [], "error": None}

# If the calendar keeps returning zero parsed events for this long despite
# successful HTTP fetches, that's more likely a broken scraper (site markup
# changed) than a genuinely quiet calendar, so alert an admin.
_CALENDAR_ZERO_EVENT_ALERT_SECONDS = _env_int("NEWS_CALENDAR_ZERO_EVENT_ALERT_SECONDS", 6 * 3600)
# Separate, much shorter threshold for flipping the filter itself to
# fail-CLOSED (blocking trades) rather than just alerting an admin - a
# missed good signal for half an hour is a far smaller cost than trading
# blind next to news for hours because nobody's read the alert yet.
_CALENDAR_ZERO_EVENT_FAILCLOSED_SECONDS = _env_int("NEWS_CALENDAR_ZERO_EVENT_FAILCLOSED_SECONDS", 30 * 60)
_calendar_zero_event_streak_since: Optional[float] = None


def _blocking_pool():
    return app_state.blocking_pool or reactor.getThreadPool()


def _normalize_pair(pair: str) -> str:
    return (pair or "").replace("/", "").upper().strip()


def _now() -> float:
    return time.time()


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


def _localized_result(result: dict, lang: str | None = None) -> dict:
    if lang is None:
        return dict(result or {})

    payload = dict(result or {})
    payload["reason"] = localize_reason(payload.get("reason", ""), normalize_lang(lang))
    return payload


def _safe_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_calendar_time(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _pair_currencies(pair: str) -> set[str]:
    norm = _normalize_pair(pair)

    if len(norm) >= 6 and norm[:6].isalpha():
        return {norm[:3], norm[3:6]}

    mapping = {
        "US30": {"USD"},
        "US500": {"USD"},
        "UK100": {"GBP"},
        "XAUUSD": {"USD"},
        "XAGUSD": {"USD"},
        "BTCUSD": {"USD"},
        "ETHUSD": {"USD"},
        "XRPUSD": {"USD"},
        "LTCUSD": {"USD"},
        "BCHUSD": {"USD"},
        "ADAUSD": {"USD"},
        "SOLUSD": {"USD"},
        "BNBUSD": {"USD"},
    }
    return mapping.get(norm, set())


def _parse_calendar_events(raw_events: list) -> list[dict]:
    """Transforms tool.forex's /api/calendar JSON `events` array into this
    module's internal event shape. Kept as a separate function (rather than
    inlined into _load_calendar_events) specifically so the live canary
    test in tests/test_news_filter.py can call it directly against a real
    API response."""
    events = []

    for item in raw_events or []:
        if not isinstance(item, dict):
            continue

        currency = str(item.get("currency") or "").strip().upper()
        name = str(item.get("title") or "").strip()
        event_time = _parse_calendar_time(item.get("date"))
        impact = _CALENDAR_IMPORTANCE_TO_IMPACT.get(item.get("importance"), "LOW")

        if not currency or not name or event_time is None:
            continue

        events.append(
            {
                "currency": currency,
                "impact": impact,
                "name": name,
                "time_utc": event_time,
                "all_day": False,
                "source": "tool.forex",
            }
        )

    return events


def _calendar_api_url(now: datetime) -> str:
    frm = (now - timedelta(days=1)).date().isoformat()
    to = (now + timedelta(days=2)).date().isoformat()
    return f"{_CALENDAR_URL}?from={frm}&to={to}"


def _load_calendar_events() -> tuple[list[dict], Optional[str]]:
    now = _now()

    with _cache_lock:
        if now - _calendar_cache.get("ts", 0) < _CALENDAR_CACHE_TTL:
            return list(_calendar_cache.get("events") or []), _calendar_cache.get("error")

    global _calendar_zero_event_streak_since

    try:
        response = requests.get(
            _calendar_api_url(datetime.now(timezone.utc)),
            headers={"User-Agent": "Mozilla/5.0 ZigZagBot/1.0"},
            timeout=(5, 20),
        )
        response.raise_for_status()
        payload = response.json()
        raw_events = (payload or {}).get("events") or []
        events = _parse_calendar_events(raw_events)

        if events:
            error = None
            with _cache_lock:
                _calendar_zero_event_streak_since = None
            logger.info("Календар новин завантажено: %s подій із %s", len(events), _CALENDAR_URL)
        else:
            error = "календар не містить подій"
            logger.info("Календар новин завантажено без подій із %s", _CALENDAR_URL)
            _note_zero_event_fetch(now)
    except Exception as exc:
        events = []
        error = f"календар недоступний: {exc}"
        logger.warning("Не вдалося завантажити календар новин: %s", exc)
        # A network/HTTP failure isn't evidence the HTML parser broke, so it
        # doesn't count towards the zero-events-despite-success streak.
        with _cache_lock:
            _calendar_zero_event_streak_since = None

    with _cache_lock:
        _calendar_cache.update({"ts": now, "events": events, "error": error})

    return list(events), error


def _zero_event_streak_seconds(now: float) -> float:
    with _cache_lock:
        since = _calendar_zero_event_streak_since
    return (now - since) if since is not None else 0.0


def _is_calendar_parser_suspected_broken(now: float) -> bool:
    """True once the zero-events-despite-successful-fetch streak crosses
    the (short) fail-closed threshold - see _CALENDAR_ZERO_EVENT_FAILCLOSED_
    SECONDS. Used by _calendar_verdict to block trades rather than trade
    blind, well before the separate (longer) admin-alert threshold fires."""
    return _zero_event_streak_seconds(now) >= _CALENDAR_ZERO_EVENT_FAILCLOSED_SECONDS


def _note_zero_event_fetch(now: float) -> None:
    """Track successful-but-empty calendar fetches and alert if the streak
    looks like a broken parser rather than a genuinely quiet calendar."""
    global _calendar_zero_event_streak_since

    with _cache_lock:
        if _calendar_zero_event_streak_since is None:
            _calendar_zero_event_streak_since = now
        streak_seconds = now - _calendar_zero_event_streak_since

    if streak_seconds < _CALENDAR_ZERO_EVENT_ALERT_SECONDS:
        return

    try:
        from notifier import notify_admin

        notify_admin(
            "⚠️ Календар новин: успішні запити повертають 0 подій "
            f"вже {int(streak_seconds // 3600)}г. Схоже, парсер зламався "
            "(сайт міг змінити розмітку), а не що подій справді немає. "
            "Фільтр новин зараз блокує угоди (fail-closed, спрацювало "
            f"раніше за {_CALENDAR_ZERO_EVENT_FAILCLOSED_SECONDS // 60} хв "
            f"стріку) — перевірте {_CALENDAR_URL}.",
            alert_key="news_calendar_parser_suspected_broken",
        )
    except Exception:
        logger.debug("Could not notify admin about suspected calendar parser breakage", exc_info=True)


def _format_event_time_utc(event_time: datetime) -> str:
    return event_time.astimezone(timezone.utc).strftime("%H:%M UTC")


def _calendar_verdict(pair: str) -> dict:
    pair = _normalize_pair(pair)
    currencies = _pair_currencies(pair)

    if not currencies:
        return _fallback(
            "валюти для календаря не визначені",
            source="calendar_unsupported_pair",
            model=None,
        )

    events, error = _load_calendar_events()
    if error and not events:
        if _is_calendar_parser_suspected_broken(_now()):
            # Fail-CLOSED: a sustained streak of successful-but-empty
            # fetches looks like a broken parser (site markup/API changed
            # under us again), not a genuinely quiet calendar - see
            # _note_zero_event_fetch. Blocking trades near-blind is safer
            # than trusting a filter that can no longer see anything.
            return {
                "verdict": "BLOCK",
                "reason": "фільтр новин недоступний (підозра на несправність парсера)",
                "available": False,
                "source": "calendar_unavailable_failclosed",
                "model": None,
                "http_status": None,
                "raw": error[:200],
            }
        return _fallback(error, source="calendar_unavailable", model=None)

    now = datetime.now(timezone.utc)
    before_seconds = _safe_int(str(_NEWS_BLOCK_BEFORE_MINUTES), 15) * 60
    after_seconds = _safe_int(str(_NEWS_BLOCK_AFTER_MINUTES), 30) * 60

    relevant = []
    for event in events:
        if event.get("all_day"):
            continue
        if event.get("currency") not in currencies:
            continue
        if event.get("impact") not in _NEWS_BLOCK_IMPACTS:
            continue

        event_time = event.get("time_utc")
        if not isinstance(event_time, datetime):
            continue

        delta_seconds = (event_time - now).total_seconds()
        if -before_seconds <= delta_seconds <= after_seconds:
            relevant.append((abs(delta_seconds), event))

    if relevant:
        relevant.sort(key=lambda item: item[0])
        event = relevant[0][1]
        reason = (
            f"{event['currency']} {event['name']} о "
            f"{_format_event_time_utc(event['time_utc'])}"
        )
        return {
            "verdict": "BLOCK",
            "reason": reason,
            "available": True,
            "source": "calendar",
            "model": None,
            "http_status": 200,
            "raw": reason[:200],
            "event": {
                "currency": event["currency"],
                "impact": event["impact"],
                "name": event["name"],
                "time_utc": event["time_utc"].isoformat(),
                "source": event["source"],
            },
        }

    return {
        "verdict": "GO",
        "reason": "подій високої важливості поруч немає",
        "available": True,
        "source": "calendar",
        "model": None,
        "http_status": 200,
        "raw": "",
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


def get_latest_news_sentiment_async(pair: str, lang: str | None = None):
    pair = _normalize_pair(pair)

    cached = _get_cached(pair)
    if cached:
        logger.debug(
            "news_filter cache hit for %s (age=%ss, source=%s)",
            pair,
            int(_now() - cached.get("ts", 0)),
            cached.get("source"),
        )
        return succeed(_localized_result(cached, lang))

    def _store(result: dict):
        ttl = _CACHE_TTL if result.get("available") else _ERROR_CACHE_TTL
        return _localized_result(_store_cache(pair, result, ttl), lang)

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
        return _localized_result(_store_cache(pair, fallback, _ERROR_CACHE_TTL), lang)

    d = deferToThreadPool(
        reactor,
        _blocking_pool(),
        _calendar_verdict,
        pair,
    )
    d.addCallback(_store)
    d.addErrback(_on_error)
    return d


def get_latest_news_sentiment(pair: str, lang: str | None = None) -> str:
    pair = _normalize_pair(pair)

    cached = _get_cached(pair)
    if cached:
        return _localized_result(cached, lang)["verdict"]

    result = _calendar_verdict(pair)
    ttl = _CACHE_TTL if result.get("available") else _ERROR_CACHE_TTL
    return _localized_result(_store_cache(pair, result, ttl), lang)["verdict"]


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

    with _cache_lock:
        zero_streak_since = _calendar_zero_event_streak_since

    zero_streak_seconds = int(now - zero_streak_since) if zero_streak_since else 0

    return {
        "fresh": len(fresh),
        "stale": len(stale),
        "total": len(items),
        "calendar_url": _CALENDAR_URL,
        "calendar_block_impacts": sorted(_NEWS_BLOCK_IMPACTS),
        "calendar_window_minutes": {
            "before": _NEWS_BLOCK_BEFORE_MINUTES,
            "after": _NEWS_BLOCK_AFTER_MINUTES,
        },
        "calendar_zero_event_streak_seconds": zero_streak_seconds,
    }
