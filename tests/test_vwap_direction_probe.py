from datetime import datetime
import unittest
from research_new_methods_20261007.direction_probe import replay_pair,atr_before,summary

START=int(datetime.fromisoformat('2026-10-05T12:00:00+00:00').timestamp())
ORDER=dict(day='2026-10-05',signal_ts=START,limit=10.,stop=9.)


def streams(prices):
    return {side:[dict(timestamp_ms=(START+offset)*1000,price=value) for offset,bid,ask in prices for value in [bid if side=='BID' else ask] if value is not None] for side in ('BID','ASK')}


class DirectionProbeTests(unittest.TestCase):
    def test_decline_wins_short_with_spread_and_fee(self):
        result=replay_pair(ORDER,streams([(1,9.9,10),(2,8.7,8.8)]),.1)
        self.assertEqual(result['status'],'paired')
        self.assertAlmostEqual(result['long']['r'],-1.4)
        self.assertAlmostEqual(result['short']['r'],.9)
    def test_rally_wins_long_short_stop_uses_ask(self):
        result=replay_pair(ORDER,streams([(1,9.9,10),(2,11.2,11.3)]),.1)
        self.assertAlmostEqual(result['long']['r'],.9)
        self.assertAlmostEqual(result['short']['r'],-1.5)
    def test_pre_signal_touch_not_entry(self):
        result=replay_pair(ORDER,streams([(0,9.9,10),(1,10.1,10.2),(2,11.2,11.3)]),0)
        self.assertNotEqual(result['status'],'paired')
    def test_stale_entry_side_unknown_not_later_better_entry(self):
        result=replay_pair(ORDER,streams([(-20,9.9,None),(1,None,10),(2,9.9,10),(3,11,11.1)]),0)
        self.assertEqual(result['status'],'unknown')
        self.assertEqual(result['reason'],'invalid_quote_at_common_entry')
    def test_crossed_entry_unknown(self):
        self.assertEqual(replay_pair(ORDER,streams([(1,10.1,10)]),0)['status'],'unknown')
    def test_gap_does_not_invent_takeprofit(self):
        result=replay_pair(ORDER,streams([(1,9.9,10),(200,11.2,11.3)]),0)
        self.assertEqual(result['reason'],'quote_gap')
    def test_same_timestamp_extremes_do_not_grant_favorable_order(self):
        result=replay_pair(ORDER,streams([(1,9.9,10),(2,11.2,11.3),(2,8.7,8.8)]),0)
        self.assertEqual(result['long']['outcome'],'STOP')
        self.assertEqual(result['short']['outcome'],'STOP')
    def test_stress_worse_with_same_triggers(self):
        data=streams([(1,9.9,10),(2,8.7,8.8)])
        base=replay_pair(ORDER,data,.1)
        stress=replay_pair(ORDER,data,.2,.1)
        for side in ('long','short'):
            self.assertAlmostEqual(stress[side]['r'],base[side]['r']-.2)
            self.assertEqual(stress[side]['fill_ms'],base[side]['fill_ms'])
    def test_zero_risk_rejected(self):
        with self.assertRaises(ValueError):replay_pair(dict(ORDER,stop=10),streams([(1,9.9,10)]),0)
    def test_missing_quotes_unknown(self):
        self.assertEqual(replay_pair(ORDER,dict(BID=[],ASK=[]),0)['status'],'unknown')
    def test_summary_unknown_not_zero_profit(self):
        self.assertEqual(summary([dict(status='unknown',day='2026-10-05')]),dict(statuses={'unknown':1},paired=0))


if __name__=='__main__':unittest.main()
