import unittest
from datetime import datetime
from unittest.mock import patch

import binomo_executor


class _FakePage:
    """Stands in for a Playwright Page in price-feed tests: _read_binomo_price
    only ever calls wait_for_timeout on it. Each call advances the fake clock,
    so polling loops terminate without real sleeping."""

    def __init__(self, clock):
        self._clock = clock

    def wait_for_timeout(self, ms):
        self._clock.advance(ms / 1000.0)


class _FakeClock:
    def __init__(self):
        self.now = 1000.0

    def advance(self, seconds):
        self.now += seconds

    def __call__(self):
        return self.now


class ReadBinomoPriceTest(unittest.TestCase):
    """Covers the guard that stops a tick from the previously-viewed asset
    being recorded as the newly-selected one's price - the failure mode that
    would silently corrupt correlation-check data."""

    def setUp(self):
        self.clock = _FakeClock()
        self.page = _FakePage(self.clock)
        self._orig_map = dict(binomo_executor._asset_ric_map)
        binomo_executor._asset_ric_map.clear()
        # _price_feed_state is module-global; without resetting it a tick
        # left by an earlier test leaks into this one.
        binomo_executor._clear_price_feed_cache()
        self._time_patch = patch.object(binomo_executor.time, "monotonic", self.clock)
        self._time_patch.start()

    def tearDown(self):
        self._time_patch.stop()
        binomo_executor._clear_price_feed_cache()
        binomo_executor._asset_ric_map.clear()
        binomo_executor._asset_ric_map.update(self._orig_map)

    def _set_tick(self, rate, ric):
        with binomo_executor._price_feed_lock:
            binomo_executor._price_feed_state["rate"] = rate
            binomo_executor._price_feed_state["ric"] = ric
            binomo_executor._price_feed_state["received_at"] = self.clock.now

    def test_returns_price_once_ric_settles(self):
        self._set_tick(93000.5, "BTCUSD-OTC")
        price = binomo_executor._read_binomo_price(self.page, "Bitcoin (OTC)")
        self.assertEqual(price, 93000.5)
        self.assertEqual(binomo_executor._asset_ric_map["Bitcoin (OTC)"], "BTCUSD-OTC")

    def test_rejects_price_belonging_to_another_asset(self):
        binomo_executor._asset_ric_map["Ethereum (OTC)"] = "ETHUSD-OTC"
        self._set_tick(93000.5, "BTCUSD-OTC")  # lingering tick from Bitcoin
        price = binomo_executor._read_binomo_price(self.page, "Ethereum (OTC)")
        self.assertIsNone(price)

    def test_returns_none_when_feed_is_silent(self):
        price = binomo_executor._read_binomo_price(self.page, "Bitcoin (OTC)", timeout_seconds=2.0)
        self.assertIsNone(price)

    def test_ignores_stale_tick(self):
        self._set_tick(93000.5, "BTCUSD-OTC")
        self.clock.advance(binomo_executor._PRICE_FEED_STALE_SECONDS + 1)
        price = binomo_executor._read_binomo_price(self.page, "Bitcoin (OTC)", timeout_seconds=2.0)
        self.assertIsNone(price)


class ClearPriceFeedCacheTest(unittest.TestCase):
    def test_clears_tick_but_keeps_learned_ric_map(self):
        with binomo_executor._price_feed_lock:
            binomo_executor._price_feed_state["rate"] = 1.0
            binomo_executor._price_feed_state["ric"] = "X"
            binomo_executor._price_feed_state["received_at"] = 5.0
        binomo_executor._asset_ric_map["Some Asset"] = "X"
        try:
            binomo_executor._clear_price_feed_cache()
            with binomo_executor._price_feed_lock:
                self.assertIsNone(binomo_executor._price_feed_state["rate"])
                self.assertIsNone(binomo_executor._price_feed_state["ric"])
            self.assertEqual(binomo_executor._asset_ric_map.get("Some Asset"), "X")
        finally:
            binomo_executor._asset_ric_map.pop("Some Asset", None)


class LoadAssetMapTest(unittest.TestCase):
    def test_loads_expected_pairs(self):
        asset_map = binomo_executor.load_asset_map()
        self.assertIn("EURUSD", asset_map)
        self.assertEqual(asset_map["EURUSD"]["binomo_name"], "EUR/USD")


class ParseNumericTextTest(unittest.TestCase):
    def test_ukrainian_locale_balance(self):
        # Comma decimal + space thousands separator, as shown live on the
        # Binomo balance display - a naive comma-strip previously produced
        # 35071200.0 instead of 350712.0 (100x too large).
        self.assertEqual(binomo_executor._parse_numeric_text("350 712,00 ₴"), 350712.0)

    def test_plain_integer_amount_field(self):
        self.assertEqual(binomo_executor._parse_numeric_text("₴4000"), 4000.0)

    def test_full_european_format(self):
        self.assertEqual(binomo_executor._parse_numeric_text("1.234,56"), 1234.56)

    def test_empty_or_unparseable_returns_none(self):
        self.assertIsNone(binomo_executor._parse_numeric_text("₴"))


class ResolveBinomoAssetNameTest(unittest.TestCase):
    """POLICY (2026-08-11): a Binomo '(OTC)' listing is Binomo's own
    synthetic/generated price series, not a real market feed - never
    select/trade/track a pair under that name. otc_name is therefore never
    used here, regardless of weekday/weekend or whether binomo_name is
    present at all."""

    def test_returns_the_real_market_name_when_present(self):
        entry = {"binomo_name": "EUR/USD", "otc_name": "EUR/USD (OTC)"}
        self.assertEqual(binomo_executor._resolve_binomo_asset_name(entry), "EUR/USD")

    def test_never_falls_back_to_otc_name(self):
        # Matches a live finding (2026-08-10/11): Binomo can list a pair
        # only under its OTC name on an ordinary weekday (USD/CAD, GBP/USD)
        # - must return None, not silently trade the synthetic feed.
        entry = {"binomo_name": None, "otc_name": "USD/CAD (OTC)"}
        self.assertIsNone(binomo_executor._resolve_binomo_asset_name(entry))

    def test_crypto_is_permanently_excluded(self):
        # Crypto has no non-OTC listing on Binomo at all, ever - this must
        # always return None for it, not just situationally.
        entry = {"binomo_name": None, "otc_name": "Bitcoin (OTC)"}
        self.assertIsNone(binomo_executor._resolve_binomo_asset_name(entry))


class IsActiveTest(unittest.TestCase):
    def test_false_when_config_disabled(self):
        with patch.object(binomo_executor.config, "BINOMO_EXECUTOR_ENABLED", False):
            self.assertFalse(binomo_executor.is_active())

    def test_false_when_kill_switch_tripped(self):
        with patch.object(binomo_executor.config, "BINOMO_EXECUTOR_ENABLED", True), \
             patch.object(binomo_executor.db, "get_binomo_runtime_state", return_value={
                 "runtime_enabled": True, "kill_switch_tripped": True, "kill_switch_reason": "x",
             }):
            self.assertFalse(binomo_executor.is_active())

    def test_true_when_enabled_and_not_tripped(self):
        with patch.object(binomo_executor.config, "BINOMO_EXECUTOR_ENABLED", True), \
             patch.object(binomo_executor.db, "get_binomo_runtime_state", return_value={
                 "runtime_enabled": True, "kill_switch_tripped": False, "kill_switch_reason": None,
             }):
            self.assertTrue(binomo_executor.is_active())


class CheckRiskLimitsTest(unittest.TestCase):
    def _patch_db(self, *, trades_today=0, consecutive_losses=0, daily_pnl=0.0):
        return patch.multiple(
            binomo_executor.db,
            count_binomo_trades_today=lambda mode: trades_today,
            get_consecutive_binomo_losses=lambda mode: consecutive_losses,
            get_daily_binomo_pnl=lambda mode: daily_pnl,
        )

    def test_blocks_on_max_trades_per_day(self):
        with patch.object(binomo_executor.config, "BINOMO_MAX_TRADES_PER_DAY", 5), \
             self._patch_db(trades_today=5):
            reason = binomo_executor._check_risk_limits(balance=1000.0)
        self.assertIsNotNone(reason)
        self.assertIn("MAX_TRADES_PER_DAY", reason)

    def test_blocks_and_trips_on_consecutive_losses(self):
        with patch.object(binomo_executor.config, "BINOMO_MAX_TRADES_PER_DAY", 100), \
             patch.object(binomo_executor.config, "BINOMO_MAX_CONSECUTIVE_LOSSES", 3), \
             patch.object(binomo_executor, "_trip_kill_switch") as trip, \
             self._patch_db(consecutive_losses=3):
            reason = binomo_executor._check_risk_limits(balance=1000.0)
        self.assertIsNotNone(reason)
        trip.assert_called_once()

    def test_blocks_and_trips_on_daily_loss(self):
        with patch.object(binomo_executor.config, "BINOMO_MAX_TRADES_PER_DAY", 100), \
             patch.object(binomo_executor.config, "BINOMO_MAX_CONSECUTIVE_LOSSES", 100), \
             patch.object(binomo_executor.config, "BINOMO_MAX_DAILY_LOSS_PERCENT", 5.0), \
             patch.object(binomo_executor, "_trip_kill_switch") as trip, \
             self._patch_db(daily_pnl=-60.0):
            reason = binomo_executor._check_risk_limits(balance=1000.0)  # 5% of 1000 = 50
        self.assertIsNotNone(reason)
        trip.assert_called_once()

    def test_allows_when_within_limits(self):
        with patch.object(binomo_executor.config, "BINOMO_MAX_TRADES_PER_DAY", 100), \
             patch.object(binomo_executor.config, "BINOMO_MAX_CONSECUTIVE_LOSSES", 100), \
             patch.object(binomo_executor.config, "BINOMO_MAX_DAILY_LOSS_PERCENT", 5.0), \
             self._patch_db(trades_today=1, consecutive_losses=0, daily_pnl=10.0):
            reason = binomo_executor._check_risk_limits(balance=1000.0)
        self.assertIsNone(reason)


class KillSwitchEndToEndTest(unittest.TestCase):
    """CheckRiskLimitsTest above mocks get_consecutive_binomo_losses
    directly, which only proves the logic is correct GIVEN a loss count -
    it never proves a real loss actually produces that count. That gap is
    exactly what let read_trade_result reach production completely unable
    to ever report "loss" (see ReadTradeResultTest) while this exact test
    class would have passed the whole time. This one runs the real
    pipeline: read_trade_result (now fixed) parses an actual loss-row
    string, db.resolve_binomo_trade persists it, db.get_consecutive_
    binomo_losses counts it back out, _check_risk_limits trips the real
    (DB-persisted, process-shared) kill switch, and a subsequent
    _handle_signal call is confirmed to stop before ever touching the
    browser. Only the Playwright page/DOM layer is faked.

    The kill-switch flag itself is a single global row shared with the
    real system (not scoped per account_mode, unlike the trade-count
    queries below) - setUp/tearDown save and restore whatever was there
    before, so this test can never leave real demo trading unable to
    place trades because a test run tripped the switch and didn't clean
    up after itself."""

    # account_mode is VARCHAR(8) in the real schema (only "demo"/"live"
    # are ever written in production) - kept short and clearly-fake so it
    # both fits the column and can never collide with real trade history.
    ACCOUNT_MODE = "e2etest"

    class _FakeRow:
        def __init__(self, text):
            self._text = text

        def inner_text(self):
            return self._text

    class _FakePage:
        def __init__(self, rows):
            self._rows = rows

        def click(self, *args, **kwargs):
            pass

        def wait_for_selector(self, selector, timeout=None, state=None):
            # These tests are about row-matching, not panel-opening
            # kinetics (see OpenTradeHistoryPanelTest for that) - always
            # report the panel as already open.
            return object()

        def query_selector_all(self, selector):
            return self._rows

    def setUp(self):
        state = binomo_executor.db.get_binomo_runtime_state()
        self._was_tripped = state["kill_switch_tripped"]
        binomo_executor.db.clear_binomo_kill_switch()
        self._trade_ids = []
        self._purge_synthetic_trades()

    def tearDown(self):
        self._purge_synthetic_trades()
        binomo_executor.db.clear_binomo_kill_switch()
        if self._was_tripped:
            binomo_executor.db.trip_binomo_kill_switch("restored after KillSwitchEndToEndTest")

    def _purge_synthetic_trades(self):
        # Defensive, not just "delete what this run created": if an
        # earlier run of this test crashed before tearDown, leftover rows
        # under this account_mode would silently inflate the next run's
        # loss streak. Scoped to ACCOUNT_MODE, so this can't touch real
        # demo trade history.
        with binomo_executor.db.get_db() as session:
            if session is None:
                return
            rows = session.query(binomo_executor.db.BinomoTrade).filter(
                binomo_executor.db.BinomoTrade.account_mode == self.ACCOUNT_MODE
            ).all()
            for row in rows:
                session.delete(row)
            session.commit()

    def _place_and_lose(self, pair: str, asset: str) -> None:
        trade_id = binomo_executor.db.create_binomo_trade(
            asset=asset, pair=pair, direction="up", amount=100.0,
            expiry_seconds=300, account_mode=self.ACCOUNT_MODE,
        )
        self.assertIsNotNone(trade_id)
        self._trade_ids.append(trade_id)

        # Real settled-loss row text confirmed live 2026-08-12
        # ("AUD/JPY80%+ 0,00 ₴ 16:00:00 · 12 сер 1 396,00 ₴") - goes
        # through the actual fixed parser, not a hand-built result dict.
        # 16:00:00 GMT+3 on 12 сер = 13:00:00 UTC, so entered_after must
        # match that for the (now entered_after-aware) row-matching to
        # accept this row as the one to resolve.
        row_text = f"{asset}80%+ 0,00 ₴ 16:00:00 · 12 сер 100,00 ₴"
        page = self._FakePage([self._FakeRow(row_text)])
        with patch.object(binomo_executor, "_safe_find", side_effect=[object(), object()]), \
             patch.object(binomo_executor, "_safe_click", return_value=True):
            outcome = binomo_executor.read_trade_result(page, asset, datetime(2026, 8, 12, 13, 0, 0))
        self.assertEqual(outcome["result"], "loss")

        resolved = binomo_executor.db.resolve_binomo_trade(
            trade_id, result=outcome["result"], payout_amount=outcome["payout_amount"]
        )
        self.assertTrue(resolved)

    def test_consecutive_losses_trip_kill_switch_and_block_next_trade(self):
        with patch.object(binomo_executor.config, "BINOMO_ACCOUNT_MODE", self.ACCOUNT_MODE), \
             patch.object(binomo_executor.config, "BINOMO_MAX_CONSECUTIVE_LOSSES", 3), \
             patch.object(binomo_executor.config, "BINOMO_MAX_TRADES_PER_DAY", 1000), \
             patch.object(binomo_executor.config, "BINOMO_MAX_DAILY_LOSS_PERCENT", 1000.0), \
             patch.object(binomo_executor.config, "BINOMO_EXECUTOR_ENABLED", True):

            self.assertTrue(binomo_executor.is_active(), "must start clean, not already tripped")

            self._place_and_lose("EURUSD", "EUR/USD")
            self._place_and_lose("EURUSD", "EUR/USD")
            self.assertTrue(
                binomo_executor.is_active(),
                "2 losses with a limit of 3 must not trip the switch yet",
            )

            self._place_and_lose("EURUSD", "EUR/USD")

            # Mirrors production: the switch trips when the NEXT signal is
            # evaluated, not the instant the 3rd losing trade resolves.
            reason = binomo_executor._check_risk_limits(balance=10000.0)
            self.assertIsNotNone(reason)
            self.assertIn("MAX_CONSECUTIVE_LOSSES", reason)

            # Prove it's a real, persisted flag - read it back fresh rather
            # than trusting _check_risk_limits' own return value.
            state = binomo_executor.db.get_binomo_runtime_state()
            self.assertTrue(state["kill_switch_tripped"])
            self.assertFalse(binomo_executor.is_active())

            # And prove the actual consequence: a brand new signal on this
            # pair is refused before it ever touches the browser.
            with patch.object(binomo_executor, "get_account_balance") as mock_balance, \
                 patch.object(binomo_executor, "place_binary_trade") as mock_place:
                binomo_executor._handle_signal(
                    page=object(),
                    asset_map={"EURUSD": {"binomo_name": "EUR/USD", "otc_name": None}},
                    signal={"pair": "EURUSD", "verdict_text": "BUY", "price": 1.1, "timeframe": "5m"},
                )
                mock_balance.assert_not_called()
                mock_place.assert_not_called()


class StakeWeightForPairTest(unittest.TestCase):
    """Not martingale: weight is chosen from a fresh 30-day win-rate
    snapshot every time, never from this pair's own preceding win/loss -
    see config.py's BINOMO_STAKE_WEIGHT_* comment for why that distinction
    matters here."""

    def _weight_for(self, *, resolved, win_rate):
        with patch.object(
            binomo_executor.db, "get_pair_signal_outcome_stats",
            return_value={"resolved": resolved, "win_rate": win_rate},
        ):
            return binomo_executor._stake_weight_for_pair("EURUSD")

    def test_high_winrate_gets_full_weight(self):
        self.assertEqual(self._weight_for(resolved=50, win_rate=85.0), 1.0)

    def test_mid_winrate_gets_reduced_weight(self):
        self.assertEqual(self._weight_for(resolved=50, win_rate=70.0), 0.7)

    def test_breakeven_band_gets_small_weight(self):
        self.assertEqual(self._weight_for(resolved=50, win_rate=60.0), 0.4)

    def test_below_breakeven_gets_zero_weight(self):
        self.assertEqual(self._weight_for(resolved=50, win_rate=45.0), 0.0)

    def test_boundary_values_use_the_higher_tier(self):
        self.assertEqual(self._weight_for(resolved=50, win_rate=80.0), 1.0)
        self.assertEqual(self._weight_for(resolved=50, win_rate=65.0), 0.7)
        self.assertEqual(self._weight_for(resolved=50, win_rate=55.6), 0.4)

    def test_too_few_trades_gets_default_weight_even_with_great_winrate(self):
        self.assertEqual(self._weight_for(resolved=5, win_rate=100.0), 0.5)

    def test_no_data_gets_default_weight(self):
        self.assertEqual(self._weight_for(resolved=0, win_rate=None), 0.5)


class SignalStreamUrlTest(unittest.TestCase):
    def test_raises_without_admin_token(self):
        with patch.object(binomo_executor.config, "get_admin_access_token", return_value=None):
            with self.assertRaises(RuntimeError):
                binomo_executor._signal_stream_url()

    def test_builds_url_with_token(self):
        with patch.object(binomo_executor.config, "get_admin_access_token", return_value="tok123"), \
             patch.object(binomo_executor.config, "get_public_base_url", return_value="https://example.fly.dev"):
            url = binomo_executor._signal_stream_url()
        self.assertEqual(url, "https://example.fly.dev/api/signal-stream?admin_token=tok123")


class ClassifyOrUnknownTest(unittest.TestCase):
    def test_up_and_down(self):
        self.assertEqual(binomo_executor._classify_or_unknown(100.0, 101.0), "up")
        self.assertEqual(binomo_executor._classify_or_unknown(100.0, 99.0), "down")

    def test_unknown_when_price_missing(self):
        self.assertEqual(binomo_executor._classify_or_unknown(None, 101.0), "unknown")
        self.assertEqual(binomo_executor._classify_or_unknown(100.0, None), "unknown")


class CorrelationLogTest(unittest.TestCase):
    def test_writes_header_once_then_appends(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            log_path = binomo_executor.Path(tmp) / "correlation.csv"
            with patch.object(binomo_executor, "CORRELATION_LOG_PATH", log_path):
                row = {field: "x" for field in binomo_executor.CORRELATION_LOG_FIELDS}
                binomo_executor._append_correlation_log(row)
                binomo_executor._append_correlation_log(row)

            content = log_path.read_text(encoding="utf-8")
            lines = [line for line in content.splitlines() if line]
            self.assertEqual(len(lines), 3)  # header + 2 rows
            self.assertEqual(lines[0].split(",")[0], "logged_at")


class ReadTradeResultTest(unittest.TestCase):
    """Live-observed deal rows (2026-08-12) have no "win"/"lose"/"виграш"/
    "програш" word anywhere - a settled win looks like "Bitcoin (OTC)80%+
    72,00 ₴ 09:15:00 · 10 сер 40,00 ₴" and a settled loss like "AUD/JPY80%+
    0,00 ₴ 16:00:00 · 12 сер 1 396,00 ₴". The old text-search parser always
    fell through to "unknown", so every real trade would have retried
    forever. Distinguishing signals confirmed live: a settled row has an
    absolute timestamp ("HH:MM:SS · DD мон"), an open one a countdown
    ("00гXXхвYYс"); and per no push/flat on Binomo, a settled credited
    amount of exactly 0 is a loss, anything positive is a win.

    Binomo's timestamp is GMT+3 with no year - "09:15:00 · 10 сер" is
    2026-08-10 09:15:00 local = 2026-08-10 06:15:00 UTC, which is what
    entered_after is expressed in (matching how entry_ts is stored)."""

    class _FakeRow:
        def __init__(self, text):
            self._text = text

        def inner_text(self):
            return self._text

    class _FakePage:
        def __init__(self, rows):
            self._rows = rows

        def click(self, *args, **kwargs):
            pass

        def wait_for_selector(self, selector, timeout=None, state=None):
            # These tests are about row-matching, not panel-opening
            # kinetics (see OpenTradeHistoryPanelTest for that) - always
            # report the panel as already open.
            return object()

        def query_selector_all(self, selector):
            return self._rows

    def _read(self, row_texts, entered_after):
        rows = [self._FakeRow(t) for t in row_texts]
        page = self._FakePage(rows)
        # Two _safe_find calls in the real flow: trade_history_tab, then
        # the existence-check on row_selector before the real per-row scan.
        with patch.object(binomo_executor, "_safe_find", side_effect=[object(), object()]), \
             patch.object(binomo_executor, "_safe_click", return_value=True):
            return binomo_executor.read_trade_result(page, "irrelevant", entered_after)

    def test_settled_win_row(self):
        result = self._read(
            ["Bitcoin (OTC)80%+ 72,00 ₴ 09:15:00 · 10 сер 40,00 ₴"],
            entered_after=datetime(2026, 8, 10, 6, 15, 0),
        )
        self.assertEqual(result["result"], "win")
        self.assertEqual(result["payout_amount"], 72.0)

    def test_settled_loss_row(self):
        result = self._read(
            ["AUD/JPY80%+ 0,00 ₴ 16:00:00 · 12 сер 1 396,00 ₴"],
            entered_after=datetime(2026, 8, 12, 13, 0, 0),
        )
        self.assertEqual(result["result"], "loss")
        self.assertEqual(result["payout_amount"], 0.0)

    def test_still_open_row_is_unknown_not_misparsed_as_loss(self):
        # This is the exact shape that used to reach the parser and get
        # silently mis-marked "unknown" for the wrong reason (no win/loss
        # word) rather than the right one (not settled yet).
        result = self._read(
            ["EUR/SGD80%+ 0,00 ₴ 00г11хв01с1 754,00 ₴"],
            entered_after=datetime(2026, 8, 12, 9, 44, 15),
        )
        self.assertEqual(result["result"], "unknown")
        self.assertIsNone(result["payout_amount"])

    def test_picks_the_row_matching_entered_after_not_the_first_one(self):
        # The exact collision confirmed live 2026-08-12: two EUR/SGD trades
        # pending at once. Both rows settled here; entered_after belongs to
        # the SECOND one (a loss) - the old code would have returned
        # whichever row Playwright listed first (the win) for both trades.
        result = self._read(
            [
                "EUR/SGD80%+ 1 754,00 ₴ 09:44:15 · 12 сер 1 000,00 ₴",  # win, trade #1
                "EUR/SGD80%+ 0,00 ₴ 09:50:10 · 12 сер 1 000,00 ₴",       # loss, trade #3
            ],
            entered_after=datetime(2026, 8, 12, 6, 50, 10),  # matches the SECOND row (09:50:10 GMT+3)
        )
        self.assertEqual(result["result"], "loss")

    def test_still_open_row_for_a_different_trade_on_same_asset_is_skipped(self):
        # One trade on this asset has settled (and matches entered_after);
        # another is still open. The open one must never be mistaken for a
        # match just because it shares the asset name.
        result = self._read(
            [
                "EUR/SGD80%+ 0,00 ₴ 00г11хв01с1 754,00 ₴",              # still open, different trade
                "EUR/SGD80%+ 1 754,00 ₴ 09:44:15 · 12 сер 1 000,00 ₴",  # settled win, our trade
            ],
            entered_after=datetime(2026, 8, 12, 6, 44, 15),
        )
        self.assertEqual(result["result"], "win")

    def test_settled_row_far_outside_tolerance_is_not_matched(self):
        # A settled row for this asset exists, but from a different day
        # entirely - must not be guessed as "close enough".
        result = self._read(
            ["EUR/SGD80%+ 1 754,00 ₴ 09:44:15 · 10 сер 1 000,00 ₴"],
            entered_after=datetime(2026, 8, 12, 6, 44, 15),  # 2 days later
        )
        self.assertEqual(result["result"], "unknown")


class ScreenshotTest(unittest.TestCase):
    """Bug found live 2026-08-12: an unsanitized "/" in the tag (e.g. from
    a forex asset name like "EUR/SGD") made Playwright create a
    "..._EUR" directory containing "SGD_up.png" instead of one flat file -
    invisible to _prune_screenshots' non-recursive glob, so it would
    accumulate forever on a live-trading run."""

    class _FakePage:
        def __init__(self):
            self.screenshot_paths = []

        def screenshot(self, path):
            self.screenshot_paths.append(path)
            # A real Playwright screenshot() creates any missing parent
            # directories, which is exactly what turned the bug into a
            # silently-created directory instead of a loud failure.
            from pathlib import Path
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"")

    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmp = tempfile.TemporaryDirectory()
        self._dir_patch = patch.object(binomo_executor, "SCREENSHOT_DIR", Path(self._tmp.name))
        self._dir_patch.start()

    def tearDown(self):
        self._dir_patch.stop()
        self._tmp.cleanup()

    def test_slash_in_tag_does_not_create_a_subdirectory(self):
        page = self._FakePage()
        result = binomo_executor._screenshot(page, "before_amount_EUR/SGD_up")
        self.assertIsNotNone(result)

        from pathlib import Path
        saved = Path(result)
        self.assertTrue(saved.is_file())
        self.assertEqual(saved.parent, binomo_executor.SCREENSHOT_DIR)

    def test_other_path_separators_are_also_sanitized(self):
        page = self._FakePage()
        result = binomo_executor._screenshot(page, r'weird:name<>with|bad*chars?"here')
        self.assertIsNotNone(result)

        from pathlib import Path
        self.assertTrue(Path(result).is_file())
        self.assertEqual(Path(result).parent, binomo_executor.SCREENSHOT_DIR)


class ParsePayoutPercentTest(unittest.TestCase):
    def test_parses_plain_percent(self):
        self.assertEqual(binomo_executor._parse_payout_percent("80%"), 80.0)

    def test_strips_surrounding_whitespace(self):
        self.assertEqual(binomo_executor._parse_payout_percent(" 83% "), 83.0)

    def test_unparseable_returns_none(self):
        self.assertIsNone(binomo_executor._parse_payout_percent("n/a"))


class RefreshWatchlistByPayoutTest(unittest.TestCase):
    """Covers the add/remove decision logic only - get_available_binomo_assets
    itself is mocked out here since it needs a real DOM, and is exercised by
    hand against the live site (see the module docstring's payout section)."""

    def setUp(self):
        self.asset_map = {
            "EURUSD": {"binomo_name": "EUR/USD", "otc_name": "EUR/USD (OTC)"},
            "GBPUSD": {"binomo_name": "GBP/USD", "otc_name": "GBP/USD (OTC)"},
            "XAUUSD": {"binomo_name": "Gold", "otc_name": None},
        }
        self.added = []
        self.removed = []

    def _run(self, *, live_assets, current_watchlist, min_payout=80.0):
        with patch.object(binomo_executor.config, "get_chat_id", return_value=42), \
             patch.object(binomo_executor.config, "BINOMO_MIN_PAYOUT_PERCENT", min_payout), \
             patch.object(binomo_executor, "get_available_binomo_assets", return_value=live_assets), \
             patch.object(binomo_executor.db, "get_watchlist", return_value=list(current_watchlist)), \
             patch.object(binomo_executor.db, "add_to_watchlist", side_effect=lambda uid, p: self.added.append(p) or True), \
             patch.object(binomo_executor.db, "remove_from_watchlist", side_effect=lambda uid, p: self.removed.append(p) or True):
            binomo_executor.refresh_watchlist_by_payout(page=object(), asset_map=self.asset_map)

    def test_adds_pair_that_newly_qualifies(self):
        self._run(
            live_assets=[{"name": "EUR/USD", "payout_percent": 82.0}],
            current_watchlist=[],
        )
        self.assertEqual(self.added, ["EURUSD"])

    def test_otc_only_listing_never_qualifies(self):
        # POLICY (2026-08-11): a Binomo OTC listing is Binomo's own
        # synthetic price series, not a real market feed - never counts
        # toward watchlist qualification, no matter how good its payout.
        # Matches a live finding (2026-08-10/11): USD/CAD and GBP/USD were
        # only listed under "(OTC)" on an ordinary weekday night.
        self.asset_map = {"USDCAD": {"binomo_name": "USD/CAD", "otc_name": "USD/CAD (OTC)"}}
        self._run(
            live_assets=[{"name": "USD/CAD (OTC)", "payout_percent": 90.0}],
            current_watchlist=["USDCAD"],
        )
        self.assertEqual(self.added, [])
        self.assertEqual(self.removed, ["USDCAD"])

    def test_otc_only_pair_never_added(self):
        # Crypto has no non-OTC listing on Binomo at all - must never
        # qualify, regardless of payout or how the pair is currently listed.
        self.asset_map = {"BTCUSD": {"binomo_name": None, "otc_name": "Bitcoin (OTC)"}}
        self._run(
            live_assets=[{"name": "Bitcoin (OTC)", "payout_percent": 95.0}],
            current_watchlist=[],
        )
        self.assertEqual(self.added, [])
        self.assertEqual(self.removed, [])

    def test_removes_pair_that_dropped_below_threshold(self):
        # Matches the live snapshot that motivated this feature: GBP/USD and
        # Gold sitting at 70%/60% while everything else nearby was >=80%.
        self._run(
            live_assets=[{"name": "GBP/USD", "payout_percent": 70.0}],
            current_watchlist=["GBPUSD"],
        )
        self.assertEqual(self.removed, ["GBPUSD"])
        self.assertEqual(self.added, [])

    def test_leaves_qualifying_pair_already_present_untouched(self):
        self._run(
            live_assets=[{"name": "EUR/USD", "payout_percent": 82.0}],
            current_watchlist=["EURUSD"],
        )
        self.assertEqual(self.added, [])
        self.assertEqual(self.removed, [])

    def test_pair_missing_from_live_snapshot_is_removed_not_guessed(self):
        # XAUUSD isn't in live_assets at all (e.g. currently untradeable) -
        # must be treated as not qualifying, not left alone or added.
        self._run(
            live_assets=[{"name": "EUR/USD", "payout_percent": 82.0}],
            current_watchlist=["XAUUSD"],
        )
        self.assertEqual(self.removed, ["XAUUSD"])

    def test_does_not_touch_pairs_outside_asset_map(self):
        # A hand-added watchlist entry for a pair this map doesn't manage
        # must survive a refresh untouched, even though EUR/USD (which IS
        # managed and newly qualifies) is correctly added alongside it.
        self._run(
            live_assets=[{"name": "EUR/USD", "payout_percent": 82.0}],
            current_watchlist=["SOMEOTHERPAIR"],
        )
        self.assertNotIn("SOMEOTHERPAIR", self.removed)
        self.assertEqual(self.added, ["EURUSD"])


class DismissBlockingOverlayTest(unittest.TestCase):
    """Escape was confirmed live (2026-08-12) to close this app's Angular
    overlays generically, including the picker itself - used here instead
    of hardcoding a close-button selector for whatever promo modal
    (confirmed: a "Стати VIP-трейдером" popup) happens to be showing."""

    class _FakePage:
        def __init__(self, raise_on_press=False):
            self.pressed = []
            self._raise = raise_on_press
            self.keyboard = self

        def press(self, key):
            if self._raise:
                raise RuntimeError("boom")
            self.pressed.append(key)

    def test_presses_escape(self):
        page = self._FakePage()
        binomo_executor._dismiss_blocking_overlay(page)
        self.assertEqual(page.pressed, ["Escape"])

    def test_does_not_raise_when_press_fails(self):
        page = self._FakePage(raise_on_press=True)
        binomo_executor._dismiss_blocking_overlay(page)  # must not raise


class SafeClickTest(unittest.TestCase):
    """_safe_click was rewritten 2026-08-12 to click via a fresh
    page.locator(selector) instead of an ElementHandle a caller found
    earlier (typically via _safe_find's page.wait_for_selector). See
    OpenTradeHistoryPanelTest / _open_trade_history_panel's docstring for
    the live bug this eliminates: an ElementHandle click that reports
    success but silently lands on a node Angular has already replaced."""

    class _FakeLocator:
        def __init__(self, page, selector):
            self._page = page
            self._selector = selector

        def click(self, timeout=None):
            self._page.click_calls.append(self._selector)
            if self._page.raise_on_click:
                raise TimeoutError("element not found or not clickable")

    class _FakePage:
        def __init__(self, raise_on_click=False):
            self.click_calls = []
            self.raise_on_click = raise_on_click

        def locator(self, selector):
            return SafeClickTest._FakeLocator(self, selector)

        def screenshot(self, path):
            from pathlib import Path

            Path(path).write_bytes(b"")

    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmp = tempfile.TemporaryDirectory()
        self._dir_patch = patch.object(binomo_executor, "SCREENSHOT_DIR", Path(self._tmp.name))
        self._dir_patch.start()

    def tearDown(self):
        self._dir_patch.stop()
        self._tmp.cleanup()

    def test_clicks_via_a_fresh_locator_for_the_given_selector(self):
        page = self._FakePage()
        result = binomo_executor._safe_click(page, "#foo", description="foo")
        self.assertTrue(result)
        self.assertEqual(page.click_calls, ["#foo"])

    def test_click_failure_screenshots_logs_and_alerts_without_raising(self):
        page = self._FakePage(raise_on_click=True)
        with patch.object(binomo_executor, "notify_admin") as mock_notify:
            result = binomo_executor._safe_click(page, "#foo", description="foo")
        self.assertFalse(result)
        mock_notify.assert_called_once()


class OpenTradeHistoryPanelTest(unittest.TestCase):
    """Regression test for the exact class of bug found live 2026-08-12: a
    click that reports success (no exception) but whose effect isn't
    actually visible yet, because Angular hadn't finished re-rendering
    (real symptom: 15+ consecutive "successful" clicks on #qa_historyButton
    that never opened the panel). This can't replay a real DOM re-render
    without a browser, so it simulates the observable shape of the bug
    instead: the click always "succeeds", but the post-click visibility
    probe (page.wait_for_selector(..., state="visible")) only starts
    succeeding after a controlled number of clicks - proving the retry
    logic recovers from a late-arriving effect, and that it fails safe
    (screenshot + alert, no infinite loop) when the effect never arrives
    within the retry budget."""

    class _FakePage:
        def __init__(self, *, opens_after_clicks):
            self.click_calls = 0
            self._opens_after_clicks = opens_after_clicks

        def screenshot(self, path):
            from pathlib import Path

            Path(path).write_bytes(b"")

        def wait_for_selector(self, selector, timeout=None, state=None):
            if self.click_calls < self._opens_after_clicks:
                raise TimeoutError("panel not visible yet")
            return object()

    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmp = tempfile.TemporaryDirectory()
        self._dir_patch = patch.object(binomo_executor, "SCREENSHOT_DIR", Path(self._tmp.name))
        self._dir_patch.start()

    def tearDown(self):
        self._dir_patch.stop()
        self._tmp.cleanup()

    @staticmethod
    def _counting_click(page):
        def _click(page_arg, selector, *, description):
            page.click_calls += 1
            return True
        return _click

    def test_opens_on_the_first_click_when_the_panel_opens_immediately(self):
        page = self._FakePage(opens_after_clicks=1)
        with patch.object(binomo_executor, "_safe_click", side_effect=self._counting_click(page)):
            self.assertTrue(binomo_executor._open_trade_history_panel(page))
        self.assertEqual(page.click_calls, 1)

    def test_retries_once_when_the_first_click_lands_on_a_stale_render(self):
        # Models the live symptom: the click itself never raises, but the
        # panel doesn't become visible until a second click.
        page = self._FakePage(opens_after_clicks=2)
        with patch.object(binomo_executor, "_safe_click", side_effect=self._counting_click(page)):
            self.assertTrue(binomo_executor._open_trade_history_panel(page))
        self.assertEqual(page.click_calls, 2)

    def test_gives_up_and_alerts_after_exhausting_the_retry_budget(self):
        page = self._FakePage(opens_after_clicks=99)  # never opens within budget
        with patch.object(binomo_executor, "_safe_click", side_effect=self._counting_click(page)), \
             patch.object(binomo_executor, "notify_admin") as mock_notify:
            self.assertFalse(binomo_executor._open_trade_history_panel(page))
        mock_notify.assert_called_once()
        self.assertEqual(page.click_calls, binomo_executor._TRADE_HISTORY_PANEL_OPEN_ATTEMPTS)

    def test_returns_false_immediately_if_the_click_itself_fails(self):
        page = self._FakePage(opens_after_clicks=1)
        with patch.object(binomo_executor, "_safe_click", return_value=False):
            self.assertFalse(binomo_executor._open_trade_history_panel(page))


if __name__ == "__main__":
    unittest.main()
