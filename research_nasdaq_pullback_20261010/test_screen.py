import unittest
from datetime import date
import screen as s


def bars():
    return [dict(ts=t, Open=100., High=101., Low=99., Close=100.)
            for t in s.session_timestamps(date(2026, 10, 7))]


def setbar(rows, i, o, c, low=None, high=None):
    rows[i].update(Open=o, Close=c, Low=min(o, c) if low is None else low,
                   High=max(o, c) if high is None else high)


class ScreenTests(unittest.TestCase):
    def test_dst(self):
        winter = s.session_timestamps(date(2026, 1, 5))[0]
        summer = s.session_timestamps(date(2026, 7, 6))[0]
        self.assertEqual(s.datetime.fromtimestamp(winter, s.timezone.utc).hour, 14)
        self.assertEqual(s.datetime.fromtimestamp(summer, s.timezone.utc).hour, 13)
        self.assertEqual(len(bars()), 78)

    def test_entry_next_bar_no_future(self):
        b = bars()
        setbar(b, 2, 104, 106)
        setbar(b, 3, 108, 107)
        setbar(b, 4, 107, 108)
        self.assertEqual(s.decide_entry(b, 10)[0], (4, 1, b[2]['ts']+300))
        for row in b[5:]:
            row.update(Open=1., High=1., Low=1., Close=1.)
        self.assertEqual(s.decide_entry(b, 10)[0][0], 4)

    def test_first_intent_cancel_no_retry(self):
        b = bars()
        setbar(b, 2, 104, 106)
        setbar(b, 3, 106, 105)
        setbar(b, 5, 93, 92)
        self.assertEqual(s.decide_entry(b, 10), (None, 'cancelled_reentry'))

    def test_entry_gap_cancels(self):
        b = bars()
        setbar(b, 2, 104, 106)
        setbar(b, 3, 108, 107)
        self.assertEqual(s.decide_entry(b, 10), (None, 'cancelled_entry_gap'))

    def test_thirty_minutes_inclusive(self):
        b = bars()
        setbar(b, 2, 104, 106)
        for i in range(3, 8):
            setbar(b, i, 106, 107)
        setbar(b, 8, 108, 107)
        setbar(b, 9, 107, 108)
        self.assertEqual(s.decide_entry(b, 10)[0][0], 9)
        setbar(b, 8, 106, 107)
        self.assertEqual(s.decide_entry(b, 10), (None, 'expired_intent'))

    def test_short(self):
        b = bars()
        setbar(b, 2, 96, 94)
        setbar(b, 3, 92, 93)
        setbar(b, 4, 93, 92)
        self.assertEqual(s.decide_entry(b, 10)[0][1], -1)
        setbar(b, 4, 93, 92, high=101)
        result = s.exit_trade(b, 4, -1, 100)
        self.assertEqual(result[:3], (100, b[4]['ts'], 'stop'))
        self.assertEqual(result[4], [-7])

    def test_entry_bar_stop_and_gap(self):
        b = bars()
        setbar(b, 4, 107, 108, low=99)
        self.assertEqual(s.exit_trade(b, 4, 1, 100)[:3], (100, b[4]['ts'], 'stop'))
        setbar(b, 4, 107, 108)
        setbar(b, 5, 98, 99)
        self.assertEqual(s.exit_trade(b, 4, 1, 100)[:3], (98, b[5]['ts'], 'stop_gap'))

    def test_atr_excludes_incomplete_and_future(self):
        start = s.session_timestamps(date(2026, 10, 7))[0]
        daily = [dict(ts=start-i*86400, High=102., Low=98., Close=100.)
                 for i in range(30, -1, -1)]
        self.assertEqual(s.atr_before(daily, start), 4.)
        daily[-1].update(High=999999., Low=0., Close=9999.)
        self.assertEqual(s.atr_before(daily, start), 4.)

    def test_missing_not_interpolated_and_holiday(self):
        rows = s.collect([], [])
        self.assertTrue(all(r['status'] == 'missing_session' for r in rows))
        self.assertNotIn('2025-01-09', {r['day'] for r in rows})

    def test_risk_rounding_and_small_skip(self):
        t = dict(risk_points=100., entry=1000., gross_points=-100.,
                 mark_points=[-100.], adverse_mark_points=[-100.])
        a = s.account_projection([t], 0., .1, .1, True)
        self.assertAlmostEqual(a['net_usd'], -10.)
        a = s.account_projection([t], 2., .1, .1, True)
        self.assertEqual(a['trades_taken'], 0)
        self.assertEqual(a['below_minimum_skips'], 1)

    def test_bootstrap_reproducible(self):
        self.assertEqual(s.block_interval([0, 1, -1, 2]*10), s.block_interval([0, 1, -1, 2]*10))
        self.assertEqual(s.block_interval([0]*10), [0., 0.])


if __name__ == '__main__':
    unittest.main()
