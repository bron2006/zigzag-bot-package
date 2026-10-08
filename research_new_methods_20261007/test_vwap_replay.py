import unittest
import numpy as np
from replay_vwap import replay, statistics, timestamp, bands


def bar(ts, low=99., high=105., opened=101., close=101., vwap=103.):
    return dict(ts=ts, Low=low, High=high, Open=opened, Close=close, vwap=vwap)


class ReplayTests(unittest.TestCase):
    def test_local_time_conversion(self):
        self.assertEqual(timestamp(dict(local_wall_time='2026-08-25T15:00:00')), 1787659200)

    def test_never_use_low_before_signal(self):
        result = replay(dict(limit=100, stop=98, timestamp=1),
                        [bar(0), bar(300, low=101)], 0, 0)
        self.assertEqual(result['status'], 'unfilled')

    def test_ask_proxy_prevents_false_bid_fill(self):
        result = replay(dict(limit=100, stop=98, timestamp=0), [bar(0, low=99.9)], .2, 0)
        self.assertEqual(result['status'], 'unfilled')

    def test_fill_bar_target_not_counted(self):
        result = replay(dict(limit=100, stop=98, timestamp=0),
                        [bar(0, high=110, close=99.5)], 0, 0)
        self.assertEqual(result['outcome'], 'SESSION_END')
        self.assertEqual(result['r'], -.25)

    def test_stop_first_tie(self):
        result = replay(dict(limit=100, stop=98, timestamp=0),
                        [bar(0), bar(300, low=97, high=110, opened=100)], 0, 0)
        self.assertEqual(result['outcome'], 'STOP')
        self.assertEqual(result['r'], -1)

    def test_gap_stop_is_worse(self):
        result = replay(dict(limit=100, stop=98, timestamp=0),
                        [bar(0), bar(300, low=96, opened=97)], 0, 0)
        self.assertEqual(result['r'], -1.5)

    def test_target_uses_previous_completed_vwap(self):
        result = replay(dict(limit=100, stop=98, timestamp=0),
                        [bar(0, vwap=103), bar(300, low=100, high=103.5, vwap=105)], 0, .1)
        self.assertAlmostEqual(result['r'], 1.45)

    def test_invalid_risk_rejected(self):
        self.assertEqual(replay(dict(limit=100, stop=101, timestamp=0), [bar(0)], 0, 0)['status'], 'invalid_risk')

    def test_empty_fills_do_not_become_zero_profit(self):
        self.assertIsNone(statistics([dict(status='unfilled', day='2026-09-01')])['mean_r'])

    def test_shared_vwap_future_change_does_not_rewrite_past(self):
        prices, volume = np.array([100., 101., 99., 98.]), np.ones(4)
        before = bands(prices, volume)[0]
        prices[-1] = 200
        after = bands(prices, volume)[0]
        np.testing.assert_array_equal(before[:3], after[:3])
