import unittest
from datetime import datetime, timezone
from full_tick_replay import tick_replay
from verify_replay_ticks import decode_ticks

class QuoteReplayTests(unittest.TestCase):
    def setUp(self):
        self.t = int(datetime(2026, 9, 1, 12, tzinfo=timezone.utc).timestamp())
        self.end = (self.t+4*3600)*1000
        self.order = dict(signal_ts=self.t, day='2026-09-01', limit=100., stop=99.)
    def run_case(self, ask, bid, completed=None, vwaps=None):
        streams = {name: [dict(timestamp_ms=ts, price=p) for ts,p in rows]
                   for name,rows in [('ASK',ask),('BID',bid)]}
        return tick_replay(self.order, streams, completed or [self.t], vwaps or [101.], .1)
    def test_no_entry_before_signal_plus_one_second(self):
        result=self.run_case([(self.t*1000,99.9),(self.end-1,100.2)],[(self.t*1000,100.),(self.end-1,100.)])
        self.assertEqual(result['status'],'unfilled')
    def test_ask_not_bid_controls_buy(self):
        result=self.run_case([(self.t*1000+1000,100.1),(self.end-1,100.1)],[(self.t*1000,99.8),(self.end-1,99.8)])
        self.assertEqual(result['status'],'unfilled')
    def test_stale_ask_not_evidence_of_nonfill(self):
        result=self.run_case([(self.t*1000+1000,100.2)],[(self.t*1000,100.)])
        self.assertEqual(result['status'],'missing_ask_at_session_end')
    def test_gap_stop_actual_bid_and_commission(self):
        result=self.run_case([(self.t*1000+1000,100.)],[(self.t*1000,99.8),(self.t*1000+2000,98.5)])
        self.assertEqual(result['outcome'],'STOP')
        self.assertAlmostEqual(result['r'],-1.6)
    def test_same_millisecond_stop_wins_at_fill(self):
        result=self.run_case([(self.t*1000+1000,100.)],[(self.t*1000+1000,98.9),(self.t*1000+1000,101.2)])
        self.assertEqual(result['outcome'],'STOP')
    def test_future_vwap_is_not_used(self):
        result=self.run_case([(self.t*1000+1000,100.)],[(self.t*1000,99.8),(self.end-1,100.5)],
                             [self.t,self.t+300],[110.,110.])
        self.assertEqual(result['outcome'],'SESSION_END')
    def test_target_only_completed_bar(self):
        result=self.run_case([(self.t*1000+1000,100.)],[(self.t*1000,99.8),(self.t*1000+2000,101.2)],
                             [self.t,self.t+300],[101.,110.])
        self.assertEqual(result['outcome'],'VWAP')
        self.assertAlmostEqual(result['r'],.9)
    def test_stale_bid_at_fill_unknown(self):
        result=self.run_case([(self.t*1000+1000,100.)],[(self.t*1000-61000,99.8)])
        self.assertEqual(result['status'],'missing_bid_at_fill')
    def test_stale_bid_at_close_unknown(self):
        result=self.run_case([(self.t*1000+1000,100.)],[(self.t*1000,99.8)])
        self.assertEqual(result['status'],'missing_bid_at_session_end')
    def test_invalid_stop(self):
        self.order['stop']=101.
        self.assertEqual(self.run_case([],[])['status'],'invalid_risk')
    def test_delta_ticks(self):
        result=decode_ticks([dict(timestamp='10000',tick='10000000'),dict(timestamp='-2',tick='-10')])
        self.assertEqual(result,[dict(timestamp_ms=9998,price=99.9999),dict(timestamp_ms=10000,price=100.)])

if __name__=='__main__':
    unittest.main()
