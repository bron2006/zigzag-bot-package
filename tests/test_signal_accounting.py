import unittest
import ast
from pathlib import Path
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

import db
import endpoint_sampler
import signal_accounting
import signal_tracking
from tests.test_signal_endpoint import isolated_state


def row(id_, status, entry=100, exit_=None, direction="BUY"):
    return SimpleNamespace(id=id_, outcome=status, entry_price=entry, exit_price=exit_,
                           verdict=direction, pair="TEST", entry_ts=datetime(2026, 10, 10))


class ScenarioTest(unittest.TestCase):
    def test_fixed_stake_and_no_unknown_refund(self):
        rows = [row(1, "up_timed", exit_=101), row(2, "down_timed", exit_=99), row(3, "unknown")]
        result = signal_accounting.summarize(rows, {r.id: {} for r in rows})
        self.assertEqual(result["counts"], dict(win=1, loss=1, unknown=1))
        self.assertEqual(result["scenario"]["measured_balance"], 998)
        self.assertEqual(result["scenario"]["balance_lower"], 988)
        self.assertEqual(result["scenario"]["balance_upper"], 1006)
        self.assertFalse(result["scenario"]["complete"])

    def test_exact_equality_is_paper_refund_not_tiny_move(self):
        result = signal_accounting.summarize([row(1, "flat_timed", exit_=100), row(2, "flat_timed", exit_=100.00001)], {1: {}, 2: {}})
        self.assertEqual(result["counts"], dict(refund=1, win=1))

    def test_no_mixing_old_generation(self):
        result = signal_accounting.summarize([row(1, "up_timed", exit_=101)], {})
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["legacy_total"], 1)

    def test_cancelled_publication_is_not_a_stake(self):
        result = signal_accounting.summarize([row(1, "unknown")], {1: dict(reason="publication_cancelled_db_delay")})
        self.assertEqual(result["scenario"]["balance_lower"], 1000)
        self.assertEqual(result["counts"], dict(cancelled=1))

    def test_invalid_price_never_a_win(self):
        result = signal_accounting.summarize([row(1, "up_timed", exit_=float("nan"))], {1: {}})
        self.assertEqual(result["counts"], dict(unknown=1))


class EvidenceIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        db.Base.metadata.create_all(self.engine)
        self.sessions = scoped_session(sessionmaker(bind=self.engine))
        patcher = patch.object(db, "SessionLocal", self.sessions)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.sessions.remove)
        self.entry = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=6)
        self.id = db.create_signal_outcome(pair="TEST", timeframe="1m", verdict="BUY", score=20,
                                          entry_price=100, horizon_seconds=300, entry_ts=self.entry,
                                          evidence=dict(version="live_mid_v1", entry_quote=dict(mid=100)))
        self.deadline = self.entry.replace(tzinfo=timezone.utc).timestamp() + 300

    def test_current_test_has_fixed_kyiv_cutoff_and_requires_generation(self):
        cutoff = datetime(2026, 10, 9, 21)
        def add(pair, entry, evidence):
            return db.create_signal_outcome(pair=pair, timeframe="1m", verdict="BUY", score=20,
                                            entry_price=100, horizon_seconds=300, entry_ts=entry, evidence=evidence)
        new = dict(version="live_mid_v1", entry_quote=dict(mid=100))
        before = add("BEFORE", cutoff-timedelta(microseconds=1), new)
        exact = add("EXACT", cutoff, new)
        legacy = add("LEGACY", cutoff+timedelta(hours=1), None)
        other = add("OTHER_VERSION", cutoff+timedelta(hours=1), dict(version="old"))
        with patch.object(db, "_utcnow", return_value=datetime(2027, 1, 1)):
            stats = db.get_signal_outcome_stats(1, current_test=True)
        ids = {r['id'] for r in stats['measurement_audit']['recent']}
        self.assertIn(exact, ids)
        self.assertNotIn(before, ids)
        self.assertNotIn(legacy, ids)
        self.assertNotIn(other, ids)
        self.assertEqual(stats['scope'], 'current_test')
        self.assertEqual(stats['total'], stats['measurement_audit']['total'])
        self.assertEqual(stats['pending'], stats['total'])
        with patch.object(db, "_utcnow", return_value=datetime(2026, 10, 11)):
            history = db.get_signal_outcome_stats(30, historical_only=True)
        history_pairs = {p['pair'] for p in history['by_pair']}
        self.assertIn('LEGACY', history_pairs)
        self.assertIn('BEFORE', history_pairs)
        self.assertNotIn('EXACT', history_pairs)

    def test_current_test_empty_is_valid_but_missing_db_is_not_zero(self):
        with db.session_scope() as session:
            session.query(db.SignalEvidence).delete()
        self.assertTrue(db.get_signal_outcome_stats(current_test=True)['ok'])
        self.assertEqual(db.get_signal_outcome_stats(current_test=True)['total'], 0)
        with patch.object(db, 'SessionLocal', None):
            self.assertFalse(db.get_signal_outcome_stats(current_test=True)['ok'])

    def test_atomic_entry_and_evidence_readback(self):
        pending = db.get_pending_signal_outcomes()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["entry_ts"], self.entry)
        self.assertEqual(pending[0]["evidence"]["version"], "live_mid_v1")

    def test_saved_endpoint_survives_lost_memory(self):
        quote = dict(ts=self.deadline+1, mid=101)
        self.assertTrue(db.save_signal_endpoint(self.id, quote))
        empty_state = isolated_state()
        with patch.object(signal_tracking, "app_state", empty_state):
            signal_tracking.resolve_pending_signals()
        stats = db.get_signal_outcome_stats(7)
        self.assertEqual(stats["measurement_audit"]["counts"], dict(win=1))
        self.assertEqual(stats["measurement_audit"]["recent"][0]["endpoint_ts"], quote["ts"])

    def test_endpoint_first_write_wins(self):
        self.assertTrue(db.save_signal_endpoint(self.id, dict(ts=self.deadline+1, mid=101)))
        self.assertTrue(db.save_signal_endpoint(self.id, dict(ts=self.deadline+2, mid=99)))
        self.assertEqual(db.get_pending_signal_outcomes()[0]["evidence"]["endpoint"]["mid"], 101)

    def test_resolution_race_cannot_overwrite_saved_quote(self):
        quote = dict(ts=self.deadline+1, mid=101)
        self.assertTrue(db.save_signal_endpoint(self.id, quote))
        self.assertFalse(db.resolve_signal_outcome(self.id, outcome="unknown", exit_price=None, evidence=dict(reason="gap")))
        self.assertEqual(db.get_pending_signal_outcomes()[0]["evidence"]["endpoint"], quote)

    def test_late_saved_quote_never_used_as_endpoint(self):
        self.assertFalse(db.save_signal_endpoint(self.id, dict(ts=self.deadline+20, mid=101)))
        with patch.object(signal_tracking, "app_state", isolated_state()), patch.object(endpoint_sampler, "register"):
            signal_tracking.resolve_pending_signals()
        self.assertEqual(len(db.get_pending_signal_outcomes()), 0)
        self.assertEqual(db.get_signal_outcome_stats(7)["measurement_audit"]["counts"], dict(unknown=1))


class SamplerTest(unittest.TestCase):
    def setUp(self):
        endpoint_sampler._targets.clear()
        endpoint_sampler._captured.clear()

    def tearDown(self):
        endpoint_sampler._targets.clear()
        endpoint_sampler._captured.clear()

    def test_capture_all_before_slow_writes_and_retry_original(self):
        endpoint_sampler._targets.update({1: ("A", 1000), 2: ("B", 1000)})
        state = Mock()
        state.get_signal_endpoint_quote.side_effect = [dict(ts=1001, mid=100), dict(ts=1001, mid=200)]
        save = Mock(return_value=False)
        endpoint_sampler.sample_once(state, save, 1002)
        self.assertEqual(len(endpoint_sampler._captured), 2)
        state.get_signal_endpoint_quote.reset_mock()
        save.return_value = True
        endpoint_sampler.sample_once(state, save, 2000)
        state.get_signal_endpoint_quote.assert_not_called()
        self.assertFalse(endpoint_sampler._targets)

    def test_missing_endpoint_never_saved(self):
        endpoint_sampler._targets[1] = ("A", 1000)
        state = Mock()
        state.get_signal_endpoint_quote.return_value = None
        save = Mock()
        endpoint_sampler.sample_once(state, save, 1601)
        save.assert_not_called()
        self.assertFalse(endpoint_sampler._targets)

    def test_no_sampling_before_deadline(self):
        endpoint_sampler._targets[1] = ("A", 1000)
        state = Mock()
        endpoint_sampler.sample_once(state, Mock(), 999)
        state.get_signal_endpoint_quote.assert_not_called()

    def test_observer_captures_valid_tick_even_with_same_second_downsampling(self):
        endpoint_sampler._targets[1] = ("TEST", 1000.5)
        state = isolated_state()
        with patch("state.time.time", return_value=1001):
            state.update_live_price("TEST", dict(quote_ts=1000.1, bid=100, ask=102))
            state.update_live_price("TEST", dict(quote_ts=1000.6, bid=104, ask=106))
        # The sampled history alone misses it; the registered observer does not.
        self.assertIsNone(state.get_signal_endpoint_quote("TEST", 1000.5, 1001))
        save = Mock(return_value=True)
        endpoint_sampler.sample_once(state, save, 1001)
        self.assertEqual(save.call_args.args[1]["mid"], 105)
        self.assertEqual(save.call_args.args[1]["ts"], 1000.6)

    def test_observer_first_valid_quote_never_replaced(self):
        endpoint_sampler._targets[1] = ("TEST", 1000)
        endpoint_sampler.observe("OTHER", dict(ts=1001, mid=50))
        endpoint_sampler.observe("TEST", dict(ts=999, mid=50))
        endpoint_sampler.observe("TEST", dict(ts=1001, mid=101))
        endpoint_sampler.observe("TEST", dict(ts=1002, mid=99))
        self.assertEqual(endpoint_sampler._captured[1], dict(ts=1001, mid=101))


class EntryQuoteTest(unittest.TestCase):
    def test_fresh_complete_quote_and_stale_rejection(self):
        state = isolated_state()
        with patch("state.time.time", return_value=1001):
            state.update_live_price("TEST", dict(quote_ts=1001, bid=100, ask=102))
        self.assertEqual(state.get_signal_entry_quote("TEST", 1002), dict(ts=1001, mid=101, bid=100, ask=102))
        self.assertIsNone(state.get_signal_entry_quote("TEST", 1007))
        self.assertIsNone(state.get_signal_entry_quote("TEST", 1000))

    def test_gap_reason_distinguishes_missing_timestamp_and_old_feed(self):
        state = isolated_state()
        state.live_prices["TEST"] = dict(mid=100)
        self.assertEqual(state.signal_measurement_gap_reason("TEST", 1000), "missing_broker_timestamp")
        with patch("state.time.time", return_value=1001):
            state.update_live_price("TEST", dict(quote_ts=999, bid=100, ask=102))
        self.assertEqual(state.signal_measurement_gap_reason("TEST", 1000), "last_complete_quote_before_deadline")


class ResolverSchedulingTest(unittest.TestCase):
    def wrapper(self, deferred):
        # Extract the real wrapper without importing app.py startup services.
        tree = ast.parse(Path("app.py").read_text(encoding="utf-8"))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_resolve_outcomes_async")
        dispatcher = Mock(return_value=deferred)
        resolver = Mock()
        namespace = dict(deferToThreadPool=dispatcher, reactor=Mock(), app_state=Mock(),
                         signal_tracking=SimpleNamespace(resolve_pending_signals=resolver), logger=Mock())
        exec(compile(ast.Module(body=[node], type_ignores=[]), "app.py", "exec"), namespace)
        return namespace["_resolve_outcomes_async"], dispatcher, resolver

    def test_database_resolver_dispatched_off_event_loop(self):
        from twisted.internet.defer import Deferred
        d = Deferred()
        wrapper, dispatcher, resolver = self.wrapper(d)
        self.assertIs(wrapper(), d)
        resolver.assert_not_called()
        self.assertIs(dispatcher.call_args.args[-1], resolver)
        self.assertFalse(d.called)

    def test_worker_failure_is_consumed_so_loop_can_retry(self):
        from twisted.internet.defer import Deferred
        d = Deferred()
        wrapper, _, _ = self.wrapper(d)
        wrapper()
        d.errback(RuntimeError("test DB failure"))
        self.assertIsNone(d.result)
