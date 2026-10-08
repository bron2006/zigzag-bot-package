import tempfile
import unittest
from pathlib import Path
from vwap_paper import PaperJournal,read_summary,JournalInUse

class PaperJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'paper.sqlite3'
        self.paper=PaperJournal(self.path)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.paper.close)
    def signal(self,**changes):
        args=dict(symbol='TEST',session='2026-10-08',ts=100.,end_ts=1000.,limit=100.,stop=99.,
                  fee_price=.1,target=101.,target_asof=90.)
        args.update(changes)
        return self.paper.signal(**args)
    def quote(self,ts,bid=99.8,ask=99.9):
        self.paper.quote('TEST',ts=ts,bid=bid,ask=ask)
    def order(self):
        return self.paper.orders['2026-10-08:TEST']
    def test_one_intention_even_with_different_limit(self):
        self.assertTrue(self.signal())
        self.assertFalse(self.signal(limit=100.5))
        self.assertEqual(read_summary(self.path)['orders'],1)
    def test_no_fill_at_or_before_signal(self):
        self.signal();self.quote(99);self.quote(100)
        self.assertEqual(self.order()['status'],'pending')
    def test_ask_controls_fill_not_bid(self):
        self.signal();self.quote(101,bid=99.5,ask=100.1)
        self.assertEqual(self.order()['status'],'pending')
    def test_fill_is_limit_not_past_low(self):
        self.signal();self.quote(101)
        self.assertEqual(self.order()['fill_price'],100.)
    def test_actual_bid_exit_with_fee(self):
        self.signal();self.quote(101);self.quote(102,bid=101.2,ask=101.3)
        self.assertEqual(self.order()['exit_reason'],'vwap_observed_market_bid')
        self.assertAlmostEqual(self.order()['r'],1.1)
    def test_gap_stop_actual_bid(self):
        self.signal();self.quote(101);self.quote(102,bid=98.5,ask=98.6)
        self.assertAlmostEqual(self.order()['r'],-1.6)
    def test_stop_wins_over_lower_target(self):
        self.signal();self.quote(101)
        self.paper.target('TEST',ts=101.5,value=98.,asof=100.)
        self.quote(102,bid=98.5,ask=98.6)
        self.assertEqual(self.order()['exit_reason'],'stop')
    def test_partial_sides_can_merge_if_fresh(self):
        self.signal();self.quote(101,bid=99.8,ask=None);self.quote(102,bid=None,ask=99.9)
        self.assertEqual(self.order()['status'],'open')
    def test_stale_side_cannot_fill(self):
        self.signal();self.quote(101,bid=99.8,ask=None);self.quote(120,bid=None,ask=99.9)
        self.assertEqual(self.order()['status'],'unknown')
    def test_crossed_quote_cannot_fill(self):
        self.signal();self.quote(101,bid=100.,ask=99.9)
        self.assertEqual(self.order()['status'],'pending')
    def test_future_target_rejected(self):
        with self.assertRaises(ValueError):self.signal(target_asof=101.)
    def test_invalid_risk_rejected(self):
        with self.assertRaises(ValueError):self.signal(stop=101.)
    def test_nan_rejected(self):
        with self.assertRaises(ValueError):self.signal(fee_price=float('nan'))
    def test_expire_never_fills_at_end(self):
        self.signal();self.quote(1000)
        self.assertEqual(self.order()['status'],'unknown')
    def test_expiration_requires_quote_coverage(self):
        self.signal(end_ts=200.)
        self.quote(101,bid=100.1,ask=100.2)
        self.quote(195,bid=100.1,ask=100.2)
        self.paper.advance(200.)
        self.assertEqual(self.order()['status'],'expired')
    def test_missing_bid_at_possible_touch_is_unknown(self):
        self.signal();self.quote(101,bid=None,ask=99.9)
        self.assertEqual(self.order()['status'],'unknown')
    def test_end_exit_last_fresh_bid_not_future_quote(self):
        self.signal();self.quote(101);self.quote(990,bid=100.,ask=100.1)
        # gap would make result unknown, so supply prior observations.
        self.assertEqual(self.order()['status'],'unknown')
    def test_end_exit_fresh_bid(self):
        self.signal(end_ts=200.);self.quote(101);self.quote(195,bid=100.2,ask=100.3)
        self.quote(200,bid=105.,ask=105.1)
        self.assertEqual(self.order()['exit_price'],100.2)
        self.assertAlmostEqual(self.order()['r'],.1)
    def test_missing_end_quote_unknown_not_zero(self):
        self.signal(end_ts=200.);self.quote(101);self.paper.advance(200.)
        self.assertEqual(self.order()['status'],'unknown')
        self.assertNotIn('r',self.order())
    def test_stream_loss_unknown(self):
        self.signal();self.quote(101);self.paper.gap(102.,'test_gap')
        self.assertEqual(self.order()['status'],'unknown')
    def test_restart_does_not_guess_missing_path(self):
        self.signal();self.quote(101)
        self.paper.close()
        other=PaperJournal(self.path,restart_ts=102.)
        try:
            self.assertEqual(other.orders['2026-10-08:TEST']['status'],'unknown')
            self.assertFalse(other.signal(symbol='TEST',session='2026-10-08',ts=103.,end_ts=1000.,limit=100.,stop=99.,fee_price=.1,target=101.,target_asof=90.))
        finally:other.close()
    def test_second_writer_rejected(self):
        with self.assertRaises(JournalInUse):PaperJournal(self.path)
    def test_capacity_pending_counts(self):
        self.paper.max_positions=1;self.signal()
        self.assertFalse(self.signal(symbol='OTHER'))
    def test_reader_never_creates_missing_file(self):
        missing=Path(self.tmp.name)/'missing.sqlite3'
        self.assertFalse(read_summary(missing)['exists'])
        self.assertFalse(missing.exists())
    def test_closed_does_not_reenter(self):
        self.signal();self.quote(101);self.quote(102,bid=101.2,ask=101.3)
        self.assertFalse(self.signal(ts=103.))
    def test_older_quote_ignored(self):
        self.signal();self.quote(102,bid=100.1,ask=100.2);self.quote(101)
        self.assertEqual(self.order()['status'],'pending')
    def test_manual_stop_cancels_pending(self):
        self.signal();self.paper.halt(101.)
        self.assertEqual(self.order()['status'],'cancelled')
    def test_manual_stop_closes_at_fresh_bid(self):
        self.signal();self.quote(101);self.paper.halt(102.)
        self.assertEqual(self.order()['status'],'closed')
        self.assertAlmostEqual(self.order()['r'],-.3)
    def test_manual_stop_missing_quote_unknown(self):
        self.signal();self.quote(101);self.paper.halt(200.)
        self.assertEqual(self.order()['status'],'unknown')
    def test_bid_only_target_does_not_need_old_ask(self):
        self.signal();self.quote(101);self.quote(102,bid=101.2,ask=None)
        self.assertEqual(self.order()['status'],'closed')
        self.assertAlmostEqual(self.order()['r'],1.1)
    def test_crossed_combined_bid_cannot_inflate_end_pnl(self):
        self.signal(end_ts=200.);self.quote(101);self.quote(195,bid=1000.,ask=100.)
        self.paper.advance(200.)
        self.assertEqual(self.order()['status'],'unknown')

if __name__=='__main__':unittest.main()
