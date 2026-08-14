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
    def _patch_db(self, *, trades_today=0, consecutive_losses=0, daily_pnl=0.0, kill_switch_cleared_at=None):
        return patch.multiple(
            binomo_executor.db,
            count_binomo_trades_today=lambda mode: trades_today,
            get_consecutive_binomo_losses=lambda mode, since=None: consecutive_losses,
            get_daily_binomo_pnl=lambda mode: daily_pnl,
            get_binomo_runtime_state=lambda: {
                "runtime_enabled": True, "kill_switch_tripped": False, "kill_switch_reason": None,
                "kill_switch_cleared_at": kill_switch_cleared_at,
            },
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

    def test_passes_kill_switch_cleared_at_as_since_to_the_loss_query(self):
        # Regression for the live incident (2026-08-14): the streak query
        # used to ignore any prior kill-switch clear entirely, so this
        # plumbing must actually reach get_consecutive_binomo_losses, not
        # just exist on get_binomo_runtime_state's returned dict.
        cleared_at = datetime(2026, 8, 14, 12, 0, 0)
        captured = {}

        def _fake_losses(mode, since=None):
            captured["since"] = since
            return 0

        with patch.object(binomo_executor.config, "BINOMO_MAX_TRADES_PER_DAY", 100), \
             patch.multiple(
                 binomo_executor.db,
                 count_binomo_trades_today=lambda mode: 0,
                 get_consecutive_binomo_losses=_fake_losses,
                 get_daily_binomo_pnl=lambda mode: 0.0,
                 get_binomo_runtime_state=lambda: {
                     "runtime_enabled": True, "kill_switch_tripped": False, "kill_switch_reason": None,
                     "kill_switch_cleared_at": cleared_at,
                 },
             ):
            binomo_executor._check_risk_limits(balance=1000.0)

        self.assertEqual(captured["since"], cleared_at)


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
        # 16:00:00 GMT+3 on 12 сер = 13:00:00 UTC is the row's SETTLEMENT
        # time (see _read_settled_result's THIRD BUG) - entered_after must
        # be the ENTRY time, i.e. settlement minus the 300s expiry used
        # above: 12:55:00 UTC.
        row_text = f"{asset}80%+ 0,00 ₴ 16:00:00 · 12 сер 100,00 ₴"
        page = self._FakePage([self._FakeRow(row_text)])
        with patch.object(binomo_executor, "_safe_find", side_effect=[object(), object()]), \
             patch.object(binomo_executor, "_safe_click", return_value=True):
            outcome = binomo_executor.read_trade_result(page, asset, datetime(2026, 8, 12, 12, 55, 0), 300)
        self.assertEqual(outcome["result"], "loss")

        resolved = binomo_executor.db.resolve_binomo_trade(
            trade_id, result=outcome["result"], payout_amount=outcome["payout_amount"]
        )
        self.assertTrue(resolved)

    def test_consecutive_losses_trip_kill_switch_and_block_next_trade(self):
        # BUG found live 2026-08-13: this test calls the real
        # _check_risk_limits below, which on tripping calls the real
        # _trip_kill_switch - and that sends a genuine Telegram alert via
        # notify_admin. The DB flag it sets is correctly scoped/restored by
        # setUp/tearDown, but notify_admin has no such test-mode guard, so
        # every run of this test was paging the user's real phone with a
        # false "BINOMO KILL SWITCH" alarm (confirmed live: two duplicate
        # alerts from two separate test runs during today's session).
        # notify_admin must stay mocked for this whole test.
        with patch.object(binomo_executor.config, "BINOMO_ACCOUNT_MODE", self.ACCOUNT_MODE), \
             patch.object(binomo_executor.config, "BINOMO_MAX_CONSECUTIVE_LOSSES", 3), \
             patch.object(binomo_executor.config, "BINOMO_MAX_TRADES_PER_DAY", 1000), \
             patch.object(binomo_executor.config, "BINOMO_MAX_DAILY_LOSS_PERCENT", 1000.0), \
             patch.object(binomo_executor.config, "BINOMO_EXECUTOR_ENABLED", True), \
             patch.object(binomo_executor, "notify_admin") as mock_notify:

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

            # The alert still fires (proving _trip_kill_switch's own logic
            # runs) - just mocked, so it never reaches the user's real phone.
            mock_notify.assert_called_once()

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

    def test_clearing_after_a_trip_does_not_immediately_re_trip_with_no_new_trades(self):
        # BUG found live 2026-08-14: get_consecutive_binomo_losses recomputed
        # the streak from raw trade history with no memory of a kill-switch
        # clear, so clearing after a genuine losing streak changed nothing -
        # the very next _check_risk_limits call, with zero new trades placed,
        # saw the same losses and tripped it right back (confirmed live:
        # re-tripped about a minute after a manual clear). This runs the
        # real trip -> real clear -> real re-check sequence against the real
        # DB and proves the second check no longer trips.
        with patch.object(binomo_executor.config, "BINOMO_ACCOUNT_MODE", self.ACCOUNT_MODE), \
             patch.object(binomo_executor.config, "BINOMO_MAX_CONSECUTIVE_LOSSES", 3), \
             patch.object(binomo_executor.config, "BINOMO_MAX_TRADES_PER_DAY", 1000), \
             patch.object(binomo_executor.config, "BINOMO_MAX_DAILY_LOSS_PERCENT", 1000.0), \
             patch.object(binomo_executor, "notify_admin"):

            self._place_and_lose("EURUSD", "EUR/USD")
            self._place_and_lose("EURUSD", "EUR/USD")
            self._place_and_lose("EURUSD", "EUR/USD")

            reason = binomo_executor._check_risk_limits(balance=10000.0)
            self.assertIsNotNone(reason, "3 losses with a limit of 3 must trip")
            self.assertTrue(binomo_executor.db.get_binomo_runtime_state()["kill_switch_tripped"])

            binomo_executor.db.set_binomo_runtime_enabled(True)
            binomo_executor.db.clear_binomo_kill_switch()

            # No new trade was placed since the clear - the same 3 old
            # losses are still the most recent resolved trades. Before the
            # fix, this second call would trip it again immediately.
            reason_after_clear = binomo_executor._check_risk_limits(balance=10000.0)
            self.assertIsNone(reason_after_clear)
            self.assertFalse(binomo_executor.db.get_binomo_runtime_state()["kill_switch_tripped"])


class GetDailyBinomoPnlTest(unittest.TestCase):
    """BUG found live 2026-08-14: get_daily_binomo_pnl used to just sum
    payout_amount, which is the GROSS amount credited on a win (stake +
    profit) and 0 on a loss - it never subtracted the stake wagered on
    either outcome. A real day of 27 wins / 23 losses (70,065 staked,
    69,633 credited back on the wins - a true net of -432) came back as
    +69,633: every loss counted as "0 change" instead of "-stake", and
    every win counted its full gross return instead of just the profit.
    MAX_DAILY_LOSS_PERCENT is built on this number, so it could essentially
    never trip - a real net loss would almost always still look like a
    large apparent profit. This runs against the real DB, not a mock, so
    it exercises the actual SQL sum, not just the Python arithmetic."""

    ACCOUNT_MODE = "e2etest3"

    def setUp(self):
        self._purge()

    def tearDown(self):
        self._purge()

    def _purge(self):
        with binomo_executor.db.get_db() as session:
            if session is None:
                return
            rows = session.query(binomo_executor.db.BinomoTrade).filter(
                binomo_executor.db.BinomoTrade.account_mode == self.ACCOUNT_MODE
            ).all()
            for row in rows:
                session.delete(row)
            session.commit()

    def _resolved_trade(self, *, amount: float, result: str, payout_amount: float) -> None:
        trade_id = binomo_executor.db.create_binomo_trade(
            asset="EUR/USD", pair="EURUSD", direction="up", amount=amount,
            expiry_seconds=300, account_mode=self.ACCOUNT_MODE,
        )
        self.assertIsNotNone(trade_id)
        resolved = binomo_executor.db.resolve_binomo_trade(trade_id, result=result, payout_amount=payout_amount)
        self.assertTrue(resolved)

    def test_a_losing_day_reports_a_negative_net_not_a_positive_gross(self):
        # Mirrors the live incident's shape: more winning trades than
        # losing ones by count, but a real net loss once stakes are
        # accounted for (a 100-stake, 80%-payout win only nets +80, not the
        # full 180 credited back).
        self._resolved_trade(amount=1000.0, result="win", payout_amount=1800.0)  # net +800
        self._resolved_trade(amount=1000.0, result="loss", payout_amount=0.0)  # net -1000
        self._resolved_trade(amount=1000.0, result="loss", payout_amount=0.0)  # net -1000

        pnl = binomo_executor.db.get_daily_binomo_pnl(self.ACCOUNT_MODE)
        self.assertAlmostEqual(pnl, -1200.0)

    def test_a_profitable_day_reports_a_smaller_net_than_the_old_gross_sum(self):
        self._resolved_trade(amount=1000.0, result="win", payout_amount=1800.0)  # net +800
        self._resolved_trade(amount=1000.0, result="win", payout_amount=1800.0)  # net +800
        self._resolved_trade(amount=1000.0, result="loss", payout_amount=0.0)  # net -1000

        pnl = binomo_executor.db.get_daily_binomo_pnl(self.ACCOUNT_MODE)
        self.assertAlmostEqual(pnl, 600.0)  # old buggy version would have reported 3600.0


class UpdateBinomoTradeEntryTsTest(unittest.TestCase):
    """Regression test for the live incident found 2026-08-12: not one real
    trade resolved successfully all day despite settled winning rows
    plainly visible in the UI, because entry_ts (stamped by
    create_binomo_trade when the DB row is first created, BEFORE
    place_binary_trade's real click sequence even runs) could be minutes
    off from when the trade actually started on Binomo's side whenever
    placement itself was slow - confirmed live via a real trade whose
    placement took ~9m45s end to end, while read_trade_result's own
    matching tolerance is a deliberately tight 60s. Runs against the real
    DB (only the Playwright/DOM layer would be faked, and this function
    doesn't touch that layer at all) - same account_mode-scoping pattern
    as KillSwitchEndToEndTest so it can never affect real demo trade
    history."""

    ACCOUNT_MODE = "e2etest2"

    def setUp(self):
        self._purge()

    def tearDown(self):
        self._purge()

    def _purge(self):
        with binomo_executor.db.get_db() as session:
            if session is None:
                return
            rows = session.query(binomo_executor.db.BinomoTrade).filter(
                binomo_executor.db.BinomoTrade.account_mode == self.ACCOUNT_MODE
            ).all()
            for row in rows:
                session.delete(row)
            session.commit()

    def test_updates_entry_ts_on_a_pending_trade(self):
        trade_id = binomo_executor.db.create_binomo_trade(
            asset="EUR/USD", pair="EURUSD", direction="up", amount=100.0,
            expiry_seconds=300, account_mode=self.ACCOUNT_MODE,
        )
        self.assertIsNotNone(trade_id)

        corrected = datetime(2026, 8, 12, 14, 45, 0)
        self.assertTrue(binomo_executor.db.update_binomo_trade_entry_ts(trade_id, corrected))

        trade = binomo_executor.db.get_binomo_trade(trade_id)
        self.assertEqual(trade["entry_ts"], corrected)

    def test_does_nothing_to_an_already_resolved_trade(self):
        # A resolved/errored trade's entry_ts is no longer load-bearing for
        # anything - refusing to touch it (same guard resolve_binomo_trade
        # itself uses) avoids a confusing late write racing a concurrent
        # resolution.
        trade_id = binomo_executor.db.create_binomo_trade(
            asset="EUR/USD", pair="EURUSD", direction="up", amount=100.0,
            expiry_seconds=300, account_mode=self.ACCOUNT_MODE,
        )
        self.assertIsNotNone(trade_id)
        binomo_executor.db.resolve_binomo_trade(trade_id, result="win", payout_amount=80.0)
        original = binomo_executor.db.get_binomo_trade(trade_id)["entry_ts"]

        self.assertFalse(
            binomo_executor.db.update_binomo_trade_entry_ts(trade_id, datetime(2020, 1, 1))
        )
        trade = binomo_executor.db.get_binomo_trade(trade_id)
        self.assertEqual(trade["entry_ts"], original)


class UpdateBinomoTradeExpirySecondsTest(unittest.TestCase):
    """Regression test for the live incident found 2026-08-13: Binomo's
    expiry stepper has no fixed per-click step size (confirmed live,
    read-only test session - consecutive clicks from the same baseline
    advanced by 2 minutes, then 1 minute), so a request for 300s can land
    real trades anywhere from ~5 to ~17 minutes actual duration. Runs
    against the real DB, same account_mode-scoping pattern as
    UpdateBinomoTradeEntryTsTest."""

    ACCOUNT_MODE = "e2etest2"

    def setUp(self):
        self._purge()

    def tearDown(self):
        self._purge()

    def _purge(self):
        with binomo_executor.db.get_db() as session:
            if session is None:
                return
            rows = session.query(binomo_executor.db.BinomoTrade).filter(
                binomo_executor.db.BinomoTrade.account_mode == self.ACCOUNT_MODE
            ).all()
            for row in rows:
                session.delete(row)
            session.commit()

    def test_updates_expiry_seconds_on_a_pending_trade(self):
        trade_id = binomo_executor.db.create_binomo_trade(
            asset="EUR/USD", pair="EURUSD", direction="up", amount=100.0,
            expiry_seconds=300, account_mode=self.ACCOUNT_MODE,
        )
        self.assertIsNotNone(trade_id)

        self.assertTrue(binomo_executor.db.update_binomo_trade_expiry_seconds(trade_id, 1020))

        trade = binomo_executor.db.get_binomo_trade(trade_id)
        self.assertEqual(trade["expiry_seconds"], 1020)

    def test_does_nothing_to_an_already_resolved_trade(self):
        trade_id = binomo_executor.db.create_binomo_trade(
            asset="EUR/USD", pair="EURUSD", direction="up", amount=100.0,
            expiry_seconds=300, account_mode=self.ACCOUNT_MODE,
        )
        self.assertIsNotNone(trade_id)
        binomo_executor.db.resolve_binomo_trade(trade_id, result="win", payout_amount=80.0)

        self.assertFalse(binomo_executor.db.update_binomo_trade_expiry_seconds(trade_id, 1020))
        trade = binomo_executor.db.get_binomo_trade(trade_id)
        self.assertEqual(trade["expiry_seconds"], 300)


class HandleSignalEntryTsTest(unittest.TestCase):
    """Covers _handle_signal's use of the entry_ts and expiry_seconds
    corrections with the DB/Playwright layers mocked out -
    UpdateBinomoTradeEntryTsTest above covers the DB functions themselves
    against the real database."""

    def _asset_map(self):
        return {"EURUSD": {"binomo_name": "EUR/USD", "otc_name": None}}

    def _signal(self):
        return {"pair": "EURUSD", "verdict_text": "BUY", "price": 1.1, "timeframe": "5m"}

    def test_corrects_entry_ts_after_a_successful_placement(self):
        with patch.object(binomo_executor, "is_active", return_value=True), \
             patch.object(binomo_executor, "_stake_weight_for_pair", return_value=1.0), \
             patch.object(binomo_executor, "get_account_balance", return_value=10000.0), \
             patch.object(binomo_executor, "_check_risk_limits", return_value=None), \
             patch.object(binomo_executor.db, "create_binomo_trade", return_value=42), \
             patch.object(
                 binomo_executor, "place_binary_trade",
                 return_value={"success": True, "error": None, "actual_expiry_seconds": 300},
             ), \
             patch.object(binomo_executor.db, "update_binomo_trade_entry_ts") as mock_update, \
             patch.object(binomo_executor.db, "update_binomo_trade_expiry_seconds"), \
             patch.object(binomo_executor, "notify_admin"):
            binomo_executor._handle_signal(page=object(), asset_map=self._asset_map(), signal=self._signal())

        mock_update.assert_called_once()
        called_trade_id = mock_update.call_args.args[0]
        self.assertEqual(called_trade_id, 42)

    def test_does_not_touch_entry_ts_when_placement_fails(self):
        with patch.object(binomo_executor, "is_active", return_value=True), \
             patch.object(binomo_executor, "_stake_weight_for_pair", return_value=1.0), \
             patch.object(binomo_executor, "get_account_balance", return_value=10000.0), \
             patch.object(binomo_executor, "_check_risk_limits", return_value=None), \
             patch.object(binomo_executor.db, "create_binomo_trade", return_value=42), \
             patch.object(
                 binomo_executor, "place_binary_trade",
                 return_value={"success": False, "error": "boom", "actual_expiry_seconds": None},
             ), \
             patch.object(binomo_executor.db, "mark_binomo_trade_error") as mock_error, \
             patch.object(binomo_executor.db, "update_binomo_trade_entry_ts") as mock_update, \
             patch.object(binomo_executor.db, "update_binomo_trade_expiry_seconds") as mock_expiry, \
             patch.object(binomo_executor, "notify_admin"):
            binomo_executor._handle_signal(page=object(), asset_map=self._asset_map(), signal=self._signal())

        mock_update.assert_not_called()
        mock_expiry.assert_not_called()
        mock_error.assert_called_once()

    def test_persists_the_actual_expiry_seconds_reached_not_the_requested_one(self):
        # Regression for the live incident (2026-08-13): the expiry
        # stepper's per-click step size isn't fixed, so a request for 300s
        # can land anywhere - real production trades landed at up to ~17
        # minutes actual duration. The DB must record what actually
        # happened, not what was asked for.
        with patch.object(binomo_executor, "is_active", return_value=True), \
             patch.object(binomo_executor, "_stake_weight_for_pair", return_value=1.0), \
             patch.object(binomo_executor, "get_account_balance", return_value=10000.0), \
             patch.object(binomo_executor, "_check_risk_limits", return_value=None), \
             patch.object(binomo_executor.db, "create_binomo_trade", return_value=42), \
             patch.object(
                 binomo_executor, "place_binary_trade",
                 return_value={"success": True, "error": None, "actual_expiry_seconds": 1020},  # overshot to 17min
             ), \
             patch.object(binomo_executor.db, "update_binomo_trade_entry_ts"), \
             patch.object(binomo_executor.db, "update_binomo_trade_expiry_seconds") as mock_expiry, \
             patch.object(binomo_executor, "notify_admin"):
            binomo_executor._handle_signal(page=object(), asset_map=self._asset_map(), signal=self._signal())

        mock_expiry.assert_called_once_with(42, 1020)


class SetExpiryTimeTest(unittest.TestCase):
    """_set_expiry_time picks an exact time from Binomo's expiry time-picker
    popover (opened by clicking the time input) rather than blind stepper
    clicks - see its docstring for the 2026-08-13 live incident (unpredictable
    per-click step size on the old stepper approach) and the live DOM
    verification (div.option.analytics-time, nested inside
    #qa_trading_dealTimeInput) that replaced it.

    Also regression-covers a SECOND live incident the same day: the first
    version of this picker-based rewrite used a field value read BEFORE
    opening the popover as its "elapsed 0" reference - confirmed live to be
    unreliable (the popover's own first/soonest option is sometimes that
    same value +0, sometimes +1, depending on exactly when within the
    current minute the click lands), which could make a 5-minute request
    jump to an unrelated quarter-hour mark (confirmed live: an 18-minute
    real trade for a 300s request). The fix anchors entirely on the
    popover's own first option instead - these fakes never expose a
    separately-read field value to the anchor logic at all, matching that
    fix."""

    class _FakeLocator:
        def input_value(self, timeout=None):
            return "00:00"  # value_before_click - only used to detect change, not for time math

    class _FakeOption:
        def __init__(self, text):
            self._text = text

        def inner_text(self):
            return self._text

    class _FakePage:
        def __init__(self, option_texts):
            self.option_texts = option_texts

        def locator(self, selector):
            return SetExpiryTimeTest._FakeLocator()

        def query_selector_all(self, selector):
            return [SetExpiryTimeTest._FakeOption(text) for text in self.option_texts]

        def wait_for_function(self, *args, **kwargs):
            pass

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

    def _run(self, option_texts, expiry_seconds, *, picker_opens=True, time_input_found=True):
        page = self._FakePage(option_texts)

        def _find(page_arg, selector, *, description, **kwargs):
            if description == "time_input":
                return object() if time_input_found else None
            if description == "time_picker_option":
                return object() if (picker_opens and option_texts) else None
            return object()

        def _click(page_arg, selector, *, description, **kwargs):
            return True

        with patch.object(binomo_executor, "_safe_find", side_effect=_find), \
             patch.object(binomo_executor, "_safe_click", side_effect=_click), \
             patch.object(binomo_executor, "notify_admin"):
            return binomo_executor._set_expiry_time(page, expiry_seconds)

    def test_picks_the_in_block_option_when_the_anchor_is_a_minute_ahead_of_now(self):
        # Anchor (options[0]) = "20:52" - the common case where the popover's
        # own soonest offer is ~1 minute from now (see class docstring).
        result = self._run(["20:52", "20:53", "20:54", "20:55", "20:56", "21:00", "21:15"], expiry_seconds=300)
        self.assertEqual(result, 300)

    def test_regression_anchor_being_now_itself_no_longer_overshoots_to_a_quarter_hour_mark(self):
        # Regression for the live incident (2026-08-13): when options[0] IS
        # "now" (elapsed 0, not +1), the near-term block only spans 0..4 -
        # the old field-baseline version had to jump all the way to the next
        # :15 mark for a 5-minute request (an ~18-minute real trade). Must
        # now land on the closest in-block option (21:04) instead.
        result = self._run(["21:00", "21:01", "21:02", "21:03", "21:04", "21:15", "21:30"], expiry_seconds=300)
        self.assertEqual(result, 300)

    def test_falls_through_to_a_coarser_option_when_the_target_exceeds_the_near_term_block(self):
        # anchor=17:13, target_relative=19; smallest elapsed>=19 among the
        # available options (0,1,2,17,32) is 32 (17:45).
        result = self._run(["17:13", "17:14", "17:15", "17:30", "17:45"], expiry_seconds=1200)
        self.assertEqual(result, 33 * 60)

    def test_returns_none_when_the_time_input_is_not_found(self):
        result = self._run(["17:14"], expiry_seconds=60, time_input_found=False)
        self.assertIsNone(result)

    def test_returns_none_when_the_picker_never_opens(self):
        result = self._run([], expiry_seconds=60, picker_opens=False)
        self.assertIsNone(result)

    def test_returns_none_when_no_option_is_parseable(self):
        result = self._run(["garbage", "??"], expiry_seconds=60)
        self.assertIsNone(result)


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
    2026-08-10 09:15:00 local = 2026-08-10 06:15:00 UTC. That's the row's
    SETTLEMENT time, not entered_after (see _read_settled_result's THIRD
    BUG) - entered_after in these tests is always that settlement time
    minus the expiry_seconds passed alongside it, matching how production
    actually computes the expected settlement to compare against."""

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

    def _read(self, row_texts, entered_after, expiry_seconds=300):
        rows = [self._FakeRow(t) for t in row_texts]
        page = self._FakePage(rows)
        # Two _safe_find calls in the real flow: trade_history_tab, then
        # the existence-check on row_selector before the real per-row scan.
        with patch.object(binomo_executor, "_safe_find", side_effect=[object(), object()]), \
             patch.object(binomo_executor, "_safe_click", return_value=True):
            return binomo_executor.read_trade_result(page, "irrelevant", entered_after, expiry_seconds)

    def test_settled_win_row(self):
        # Settlement 09:15:00 GMT+3 = 06:15:00 UTC; entered_after is the
        # ENTRY time, 300s (5min) earlier.
        result = self._read(
            ["Bitcoin (OTC)80%+ 72,00 ₴ 09:15:00 · 10 сер 40,00 ₴"],
            entered_after=datetime(2026, 8, 10, 6, 10, 0),
        )
        self.assertEqual(result["result"], "win")
        self.assertEqual(result["payout_amount"], 72.0)

    def test_settled_loss_row(self):
        # Settlement 16:00:00 GMT+3 = 13:00:00 UTC; entered_after 5min earlier.
        result = self._read(
            ["AUD/JPY80%+ 0,00 ₴ 16:00:00 · 12 сер 1 396,00 ₴"],
            entered_after=datetime(2026, 8, 12, 12, 55, 0),
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
        # pending at once. Both rows settled here; entered_after (+5min
        # expiry) belongs to the SECOND one (a loss, settled 09:50:10
        # GMT+3 = 06:50:10 UTC, so entered 06:45:10) - the old code would
        # have returned whichever row Playwright listed first (the win)
        # for both trades.
        result = self._read(
            [
                "EUR/SGD80%+ 1 754,00 ₴ 09:44:15 · 12 сер 1 000,00 ₴",  # win, trade #1
                "EUR/SGD80%+ 0,00 ₴ 09:50:10 · 12 сер 1 000,00 ₴",       # loss, trade #3
            ],
            entered_after=datetime(2026, 8, 12, 6, 45, 10),
        )
        self.assertEqual(result["result"], "loss")

    def test_still_open_row_for_a_different_trade_on_same_asset_is_skipped(self):
        # One trade on this asset has settled (and matches entered_after +
        # expiry); another is still open. The open one must never be
        # mistaken for a match just because it shares the asset name.
        # Settlement 09:44:15 GMT+3 = 06:44:15 UTC; entered 5min earlier.
        result = self._read(
            [
                "EUR/SGD80%+ 0,00 ₴ 00г11хв01с1 754,00 ₴",              # still open, different trade
                "EUR/SGD80%+ 1 754,00 ₴ 09:44:15 · 12 сер 1 000,00 ₴",  # settled win, our trade
            ],
            entered_after=datetime(2026, 8, 12, 6, 39, 15),
        )
        self.assertEqual(result["result"], "win")

    def test_settled_row_far_outside_tolerance_is_not_matched(self):
        # A settled row for this asset exists, but from a different day
        # entirely - must not be guessed as "close enough".
        result = self._read(
            ["EUR/SGD80%+ 1 754,00 ₴ 09:44:15 · 10 сер 1 000,00 ₴"],
            entered_after=datetime(2026, 8, 12, 6, 44, 15),  # 2 days later even after adding expiry
        )
        self.assertEqual(result["result"], "unknown")

    def test_closes_the_panel_after_a_successful_read(self):
        # Regression for the fourth live bug (2026-08-12): the panel used
        # to be left open on every exit from this function, which blocked
        # the next real trade's amount-input click in production.
        rows = [self._FakeRow("Bitcoin (OTC)80%+ 72,00 ₴ 09:15:00 · 10 сер 40,00 ₴")]
        page = self._FakePage(rows)
        with patch.object(binomo_executor, "_safe_find", side_effect=[object(), object()]), \
             patch.object(binomo_executor, "_safe_click", return_value=True), \
             patch.object(binomo_executor, "_close_trade_history_panel") as mock_close:
            binomo_executor.read_trade_result(page, "irrelevant", datetime(2026, 8, 10, 6, 10, 0), 300)
        mock_close.assert_called_once_with(page)

    def test_closes_the_panel_even_when_no_row_is_found(self):
        page = self._FakePage([])
        with patch.object(binomo_executor, "_safe_find", side_effect=[object(), None]), \
             patch.object(binomo_executor, "_safe_click", return_value=True), \
             patch.object(binomo_executor, "_close_trade_history_panel") as mock_close:
            binomo_executor.read_trade_result(page, "irrelevant", datetime(2026, 8, 10, 6, 10, 0), 300)
        mock_close.assert_called_once_with(page)


class CloseTradeHistoryPanelTest(unittest.TestCase):
    """Regression test for the fourth live bug found 2026-08-12, discovered
    immediately after fixing the third one: once _open_trade_history_panel
    made the panel reliably OPEN, nothing ever closed it again, and
    Binomo's invisible full-page backdrop behind it silently blocked the
    very next trade's amount-input click - two real trades (#25, #26)
    failed this way in production. Confirmed live (separate, already
    logged-in session) that only the panel's own [X] close button
    dismisses the backdrop, and that the dismissal itself takes a few
    seconds via Angular's own close transition - checking immediately
    after the click still showed the backdrop present; checking again a
    few seconds later showed it gone. _close_trade_history_panel must wait
    for that, not assume the click alone was enough."""

    class _FakePage:
        def __init__(self, *, closes_after_waits):
            self.click_calls = 0
            self.wait_calls = 0
            self._closes_after_waits = closes_after_waits

        def screenshot(self, path):
            from pathlib import Path

            Path(path).write_bytes(b"")

        def wait_for_selector(self, selector, timeout=None, state=None):
            self.wait_calls += 1
            if state == "detached" and self.wait_calls < self._closes_after_waits:
                raise TimeoutError("still attached")
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
        def _click(page_arg, selector, *, description, **kwargs):
            page.click_calls += 1
            return True
        return _click

    def test_closes_and_waits_for_the_backdrop_to_clear(self):
        page = self._FakePage(closes_after_waits=1)
        with patch.object(binomo_executor, "_safe_click", side_effect=self._counting_click(page)):
            binomo_executor._close_trade_history_panel(page)
        self.assertEqual(page.click_calls, 1)
        self.assertEqual(page.wait_calls, 1)

    def test_logs_a_warning_but_does_not_raise_if_it_never_clears(self):
        page = self._FakePage(closes_after_waits=99)
        with patch.object(binomo_executor, "_safe_click", side_effect=self._counting_click(page)):
            binomo_executor._close_trade_history_panel(page)  # must not raise

    def test_does_nothing_further_if_the_close_click_itself_fails(self):
        page = self._FakePage(closes_after_waits=1)
        with patch.object(binomo_executor, "_safe_click", return_value=False):
            binomo_executor._close_trade_history_panel(page)
        self.assertEqual(page.wait_calls, 0)


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

        @property
        def first(self):
            self._page.first_used.append(self._selector)
            return self

        def click(self, timeout=None):
            self._page.click_calls.append(self._selector)
            if self._page.raise_on_click:
                raise TimeoutError("element not found or not clickable")

    class _FakePage:
        def __init__(self, raise_on_click=False):
            self.click_calls = []
            self.first_used = []
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
        self.assertEqual(page.first_used, [])

    def test_click_failure_screenshots_logs_and_alerts_without_raising(self):
        page = self._FakePage(raise_on_click=True)
        with patch.object(binomo_executor, "notify_admin") as mock_notify:
            result = binomo_executor._safe_click(page, "#foo", description="foo")
        self.assertFalse(result)
        mock_notify.assert_called_once()

    def test_first_true_clicks_the_first_match_instead_of_requiring_exactly_one(self):
        # Regression for a real Telegram alert traced back to Playwright's
        # strict mode: trade_history_close_button's selector can legitimately
        # match more than one .dashboard-aside.revealed instance at once
        # (confirmed live 2026-08-12) - first=True picks one instead of
        # erroring, since "not found or blocked" was never actually true.
        page = self._FakePage()
        result = binomo_executor._safe_click(page, "#foo", description="foo", first=True)
        self.assertTrue(result)
        self.assertEqual(page.first_used, ["#foo"])
        self.assertEqual(page.click_calls, ["#foo"])


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


class RandomizedIntervalTest(unittest.TestCase):
    """POLICY (2026-08-13, user decision): periodic checks the executor
    runs on its own must use a random delay redrawn fresh on every firing,
    not a fixed period - a fixed interval is a regular, detectable
    automation signature. See _RandomizedInterval's own docstring for the
    live incident (the trade-history panel opening on every ~2s main-loop
    pass) this exists to fix."""

    def setUp(self):
        self._clock = _FakeClock()
        self._time_patch = patch.object(binomo_executor.time, "monotonic", self._clock)
        self._time_patch.start()

    def tearDown(self):
        self._time_patch.stop()

    def test_is_due_before_ever_firing(self):
        interval = binomo_executor._RandomizedInterval(45.0, 90.0)
        self.assertTrue(interval.is_due())

    def test_not_due_immediately_after_firing(self):
        interval = binomo_executor._RandomizedInterval(45.0, 90.0)
        interval.mark_fired()
        self.assertFalse(interval.is_due())

    def test_due_again_once_the_drawn_delay_elapses(self):
        with patch.object(binomo_executor.random, "uniform", return_value=60.0):
            interval = binomo_executor._RandomizedInterval(45.0, 90.0)
            interval.mark_fired()
            self._clock.advance(59.9)
            self.assertFalse(interval.is_due())
            self._clock.advance(0.2)
            self.assertTrue(interval.is_due())

    def test_draws_a_fresh_random_delay_within_bounds_on_every_firing(self):
        # Not a single jitter fixed once at construction - the whole
        # sequence of gaps must vary run to run, which is the entire
        # point (a fixed post-construction jitter is still a metronome,
        # just phase-shifted).
        drawn = iter([45.0, 90.0, 67.5])
        with patch.object(binomo_executor.random, "uniform", side_effect=lambda lo, hi: next(drawn)):
            interval = binomo_executor._RandomizedInterval(45.0, 90.0)  # consumes the first draw (45.0)
            interval.mark_fired()  # consumes the second draw (90.0)
            self._clock.advance(89.9)
            self.assertFalse(interval.is_due())
            self._clock.advance(0.2)
            self.assertTrue(interval.is_due())
            interval.mark_fired()  # consumes the third draw (67.5)
            self._clock.advance(67.6)
            self.assertTrue(interval.is_due())

    def test_min_and_max_are_always_passed_to_random_uniform(self):
        with patch.object(binomo_executor.random, "uniform", return_value=50.0) as mock_uniform:
            binomo_executor._RandomizedInterval(45.0, 90.0)
        mock_uniform.assert_called_once_with(45.0, 90.0)


class ResolveDueTradesTest(unittest.TestCase):
    """Regression test for the live incident found 2026-08-13: the user
    watched the real Binomo browser and caught the "Угоди" panel opening
    and closing 4 times within a couple of seconds. Root cause:
    _resolve_due_trades used to call read_trade_result (its own full
    open-scan-close cycle) separately for every due pending trade, so N
    trades due in the same pass meant N full open/close cycles. Fixed by
    opening the panel once, scanning every due trade against that same
    open panel via _read_settled_result, and closing once."""

    _PAST = datetime(2020, 1, 1)  # always "due" regardless of when the test runs
    _FUTURE = datetime(2099, 1, 1)  # never "due"

    def setUp(self):
        # _resolve_due_trades is now also gated by the module-level
        # _resolve_check_interval singleton (2026-08-13, randomized
        # interval) - without resetting it, whichever test runs first
        # "fires" it and every later test in the same process sees
        # is_due() == False for the next 45-90s, silently no-op'ing. A
        # fresh 0/0 interval is always immediately due, isolating each
        # test from whatever earlier tests in this run already did.
        self._interval_patch = patch.object(
            binomo_executor, "_resolve_check_interval", binomo_executor._RandomizedInterval(0, 0)
        )
        self._interval_patch.start()

    def tearDown(self):
        self._interval_patch.stop()

    def _trade(self, id_, asset, entry_ts, expiry_seconds=300):
        return {
            "id": id_, "asset": asset, "pair": asset.replace("/", ""), "direction": "up",
            "entry_ts": entry_ts, "expiry_seconds": expiry_seconds,
        }

    def test_opens_and_closes_the_panel_once_for_multiple_due_trades(self):
        trades = [
            self._trade(1, "EUR/USD", self._PAST),
            self._trade(2, "GBP/USD", self._PAST),
            self._trade(3, "USD/JPY", self._PAST),
        ]
        read_calls = []

        def _fake_read(page, asset, entered_after, expiry_seconds):
            read_calls.append(asset)
            return {"result": "unknown", "payout_amount": None}

        with patch.object(binomo_executor.db, "get_pending_binomo_trades", return_value=trades), \
             patch.object(binomo_executor, "_open_trade_history_panel", return_value=True) as mock_open, \
             patch.object(binomo_executor, "_select_trade_history_standard_tab") as mock_tab, \
             patch.object(binomo_executor, "_read_settled_result", side_effect=_fake_read), \
             patch.object(binomo_executor, "_close_trade_history_panel") as mock_close:
            binomo_executor._resolve_due_trades(page=object())

        mock_open.assert_called_once()
        mock_tab.assert_called_once()
        mock_close.assert_called_once()
        self.assertEqual(read_calls, ["EUR/USD", "GBP/USD", "USD/JPY"])

    def test_does_not_open_the_panel_at_all_when_nothing_is_due(self):
        trades = [self._trade(1, "EUR/USD", self._FUTURE)]
        with patch.object(binomo_executor.db, "get_pending_binomo_trades", return_value=trades), \
             patch.object(binomo_executor, "_open_trade_history_panel") as mock_open:
            binomo_executor._resolve_due_trades(page=object())

        mock_open.assert_not_called()

    def test_does_not_even_query_pending_trades_when_the_interval_is_not_due(self):
        # Regression for the second half of the live incident: the
        # "skip opening if nothing's due" guard above only ever stopped
        # the PANEL from opening - the DB query + due-check itself used
        # to run on every single main-loop pass (~every 2s) regardless.
        # A not-yet-due interval must short-circuit before even that.
        self._interval_patch.stop()  # replace this test's own always-due 0/0 interval
        not_due_interval = binomo_executor._RandomizedInterval(9999, 9999)
        not_due_interval.mark_fired()  # so is_due() has a recent firing to measure against
        self._interval_patch = patch.object(binomo_executor, "_resolve_check_interval", not_due_interval)
        self._interval_patch.start()
        with patch.object(binomo_executor.db, "get_pending_binomo_trades") as mock_get_pending:
            binomo_executor._resolve_due_trades(page=object())
        mock_get_pending.assert_not_called()

    def test_closes_the_panel_even_if_resolving_one_trade_raises(self):
        trades = [
            self._trade(1, "EUR/USD", self._PAST),
            self._trade(2, "GBP/USD", self._PAST),
        ]

        def _fake_read(page, asset, entered_after, expiry_seconds):
            if asset == "EUR/USD":
                raise RuntimeError("boom")
            return {"result": "unknown", "payout_amount": None}

        with patch.object(binomo_executor.db, "get_pending_binomo_trades", return_value=trades), \
             patch.object(binomo_executor, "_open_trade_history_panel", return_value=True), \
             patch.object(binomo_executor, "_select_trade_history_standard_tab"), \
             patch.object(binomo_executor, "_read_settled_result", side_effect=_fake_read), \
             patch.object(binomo_executor, "_close_trade_history_panel") as mock_close:
            with self.assertRaises(RuntimeError):
                binomo_executor._resolve_due_trades(page=object())

        mock_close.assert_called_once()

    def test_resolves_a_due_trade_and_notifies(self):
        trades = [self._trade(7, "EUR/USD", self._PAST)]

        def _fake_read(page, asset, entered_after, expiry_seconds):
            return {"result": "win", "payout_amount": 80.0}

        with patch.object(binomo_executor.db, "get_pending_binomo_trades", return_value=trades), \
             patch.object(binomo_executor, "_open_trade_history_panel", return_value=True), \
             patch.object(binomo_executor, "_select_trade_history_standard_tab"), \
             patch.object(binomo_executor, "_read_settled_result", side_effect=_fake_read), \
             patch.object(binomo_executor, "_close_trade_history_panel"), \
             patch.object(binomo_executor.db, "resolve_binomo_trade", return_value=True) as mock_resolve, \
             patch.object(binomo_executor, "notify_admin") as mock_notify:
            binomo_executor._resolve_due_trades(page=object())

        mock_resolve.assert_called_once_with(7, result="win", payout_amount=80.0)
        mock_notify.assert_called_once()


if __name__ == "__main__":
    unittest.main()
