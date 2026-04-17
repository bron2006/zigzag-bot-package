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


if __name__ == "__main__":
    unittest.main()
