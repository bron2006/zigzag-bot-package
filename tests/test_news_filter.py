import unittest
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

try:
    import twisted  # noqa: F401
except ModuleNotFoundError:
    twisted_mod = types.ModuleType("twisted")
    internet_mod = types.ModuleType("twisted.internet")
    defer_mod = types.ModuleType("twisted.internet.defer")
    threads_mod = types.ModuleType("twisted.internet.threads")
    defer_mod.Deferred = object
    defer_mod.succeed = lambda value=None: value
    threads_mod.deferToThreadPool = lambda *args, **kwargs: None
    internet_mod.reactor = object()
    internet_mod.defer = defer_mod
    sys.modules.setdefault("twisted", twisted_mod)
    sys.modules.setdefault("twisted.internet", internet_mod)
    sys.modules.setdefault("twisted.internet.defer", defer_mod)
    sys.modules.setdefault("twisted.internet.threads", threads_mod)

if "state" not in sys.modules:
    state_mod = types.ModuleType("state")

    class _AppState:
        blocking_pool = None

    state_mod.app_state = _AppState()
    sys.modules["state"] = state_mod

import news_filter


class NewsCalendarFilterTest(unittest.TestCase):
    def test_calendar_blocks_relevant_high_impact_event(self):
        event_time = datetime.now(timezone.utc) + timedelta(minutes=10)

        with patch.object(
            news_filter,
            "_load_calendar_events",
            return_value=(
                [
                    {
                        "currency": "NZD",
                        "impact": "HIGH",
                        "name": "Trade Balance",
                        "time_utc": event_time,
                        "all_day": False,
                        "source": "tool.forex",
                    }
                ],
                None,
            ),
        ):
            result = news_filter._calendar_verdict("NZDJPY")

        self.assertEqual(result["verdict"], "BLOCK")
        self.assertIn("NZD Trade Balance", result["reason"])
        self.assertEqual(result["source"], "calendar")

    def test_calendar_ignores_unrelated_currency_event(self):
        event_time = datetime.now(timezone.utc) + timedelta(minutes=10)

        with patch.object(
            news_filter,
            "_load_calendar_events",
            return_value=(
                [
                    {
                        "currency": "CAD",
                        "impact": "HIGH",
                        "name": "CPI",
                        "time_utc": event_time,
                        "all_day": False,
                        "source": "tool.forex",
                    }
                ],
                None,
            ),
        ):
            result = news_filter._calendar_verdict("NZDJPY")

        self.assertEqual(result["verdict"], "GO")
        self.assertIn("подій високої важливості", result["reason"])

    def test_calendar_fails_closed_after_sustained_zero_event_streak(self):
        with patch.object(
            news_filter, "_load_calendar_events", return_value=([], "календар не містить подій")
        ), patch.object(news_filter, "_is_calendar_parser_suspected_broken", return_value=True):
            result = news_filter._calendar_verdict("EURUSD")

        self.assertEqual(result["verdict"], "BLOCK")
        self.assertFalse(result["available"])

    def test_calendar_stays_open_on_brief_zero_event_blip(self):
        with patch.object(
            news_filter, "_load_calendar_events", return_value=([], "календар не містить подій")
        ), patch.object(news_filter, "_is_calendar_parser_suspected_broken", return_value=False):
            result = news_filter._calendar_verdict("EURUSD")

        self.assertEqual(result["verdict"], "GO")
        self.assertFalse(result["available"])


class LiveCalendarParserSmokeTest(unittest.TestCase):
    """Canary test against the REAL tool.forex API - deliberately not
    mocked. On 2026-08-10 tool.forex silently replaced its HTML markup
    with a JSON API without any error; the old regex-based parser kept
    returning "success" with 0 events for 10+ hours, and fail-open meant
    that looked identical to "no relevant news" in production the whole
    time. This test exists so the next markup/API-shape change fails a CI
    run instead of failing silently in prod for hours.

    Skips (doesn't fail) on network/HTTP errors, since those aren't
    evidence the parser itself is broken - only a reachable response
    that _parse_calendar_events can't get any events out of should fail."""

    def test_real_calendar_api_returns_events(self):
        import requests

        url = news_filter._calendar_api_url(datetime.now(timezone.utc))
        try:
            response = requests.get(
                url, headers={"User-Agent": "Mozilla/5.0 ZigZagBot/1.0"}, timeout=15
            )
        except requests.RequestException as exc:
            self.skipTest(f"tool.forex unreachable ({exc}) - not a parser signal")

        if response.status_code != 200:
            self.skipTest(f"tool.forex returned HTTP {response.status_code} - not a parser signal")

        try:
            payload = response.json()
        except ValueError:
            self.fail("tool.forex response wasn't valid JSON - API shape likely changed")

        raw_events = (payload or {}).get("events") or []
        events = news_filter._parse_calendar_events(raw_events)

        self.assertGreater(
            len(events), 0,
            "Парсер tool.forex повернув 0 подій на реальному API - "
            "можливо, розмітка/схема JSON знову змінились",
        )
        sample = events[0]
        for key in ("currency", "impact", "name", "time_utc"):
            self.assertIn(key, sample)
        self.assertIsInstance(sample["time_utc"], datetime)


if __name__ == "__main__":
    unittest.main()
