import copy
from datetime import date
import unittest
import numpy as np
import pandas as pd
import batch as b


def rows():
    rng = np.random.default_rng(41)
    times = list(range(1700000100, 1700000100+200*300, 300))
    close = 1000+np.cumsum(rng.normal(0, 3, 200))
    frame = pd.DataFrame(dict(ts=times, Open=np.r_[1000, close[:-1]], Close=close))
    frame['High'] = frame[['Open', 'Close']].max(axis=1)+2
    frame['Low'] = frame[['Open', 'Close']].min(axis=1)-2
    return b.features(frame).iloc[100:].to_dict('records')


class BatchTests(unittest.TestCase):
    def test_fixed_count(self):
        self.assertEqual(len(b.RULES), 24)
        self.assertEqual(len(set(b.RULES)), 24)
        self.assertEqual(len(b.MARKETS)*len(b.RULES), 96)

    def test_london_dst(self):
        winter = b.times_for(date(2026, 1, 5), 'EURUSD')[0]
        summer = b.times_for(date(2026, 7, 6), 'EURUSD')[0]
        self.assertEqual(b.datetime.fromtimestamp(winter, b.nasdaq.timezone.utc).hour, 8)
        self.assertEqual(b.datetime.fromtimestamp(summer, b.nasdaq.timezone.utc).hour, 7)
        self.assertEqual(len(b.times_for(date(2026, 7, 6), 'EURUSD')), 96)

    def test_all_rules_ignore_future_after_selected_signal(self):
        bars = rows()
        previous = [dict(day=date(2026, 10, d), High=1010., Low=990., Close=1000.) for d in (1, 2, 5, 6)]
        for rule in b.RULES+b.CONTROLS:
            with self.subTest(rule=rule):
                expected = b.select(rule, bars, previous, date(2026, 10, 7))
                if not expected:
                    continue
                changed = copy.deepcopy(bars)
                for row in changed[expected[0]:]:
                    for key, value in row.items():
                        if isinstance(value, float):
                            row[key] = 999999.
                self.assertEqual(b.select(rule, changed, previous, date(2026, 10, 7)), expected)

    def test_indicator_prefix_invariance(self):
        raw = pd.DataFrame([{k: r[k] for k in ('ts', 'Open', 'High', 'Low', 'Close')} for r in rows()])
        whole = b.features(raw)
        prefix = b.features(raw.iloc[:80])
        pd.testing.assert_frame_equal(whole.iloc[:80], prefix)

    def test_gap_resets_warmup(self):
        raw = pd.DataFrame([{k: r[k] for k in ('ts', 'Open', 'High', 'Low', 'Close')} for r in rows()])
        raw.loc[70:, 'ts'] += 300
        result = b.features(raw)
        self.assertTrue(result.ready.iloc[69])
        self.assertFalse(result.ready.iloc[70:].any())

    def test_stop_before_target_same_bar(self):
        bars = [dict(ts=0, Open=100., Low=98., High=105., Close=104.)]
        trade = b.simulate(bars, 0, 1, 1.)
        self.assertEqual((trade['exit'], trade['reason']), (99., 'stop'))
        trade = b.simulate(bars, 0, -1, 1.)
        self.assertEqual((trade['exit'], trade['reason']), (101., 'stop'))

    def test_adverse_gap_and_no_tp_improvement(self):
        bars = [dict(ts=0, Open=100., Low=99.5, High=101., Close=100.),
                dict(ts=300, Open=97., Low=96., High=98., Close=97.)]
        self.assertEqual(b.simulate(bars, 0, 1, 1.)['exit'], 97.)
        bars[1].update(Open=104., Low=103., High=105., Close=104.)
        self.assertEqual(b.simulate(bars, 0, 1, 1.)['exit'], 102.)

    def test_cost_units(self):
        self.assertEqual(b.cost('USTEC', 'stress'), 5.)
        self.assertEqual(b.cost('USDJPY', 'stress'), .04)
        self.assertEqual(b.cost('EURUSD', 'stress'), .0004)

    def test_jpy_conversion(self):
        self.assertEqual(b.unit_usd(1.5, 150., 'USDJPY'), .01)
        self.assertEqual(b.unit_usd(1.5, 150., 'EURUSD'), 1.5)

    def test_minimum_not_forced_and_cap(self):
        spec = dict(minVolume='10', stepVolume='10', maxVolume='25000')
        trade = dict(risk=200., stop=19800., entry=20000.)
        self.assertEqual(b.quantity(trade, 1000, 5, spec, 'USTEC', True), 0.)
        spec = dict(minVolume='100000', stepVolume='100000', maxVolume='10000000000')
        trade = dict(risk=.0001, stop=1.0999, entry=1.1)
        size = b.quantity(trade, 1000, .0004, spec, 'EURUSD', True)
        self.assertEqual(size, 4000.)
        self.assertLessEqual(size*trade['entry'], 5000.)
        self.assertLessEqual(size*(trade['risk']+.0004), 10.)

    def test_empty_day_zero_and_family_lower(self):
        spec = dict(minVolume='10', stepVolume='10', maxVolume='25000')
        summary = b.ledger([dict(day='2026-01-01')], 'USTEC', 'stress', spec, True)
        self.assertEqual(summary['fixed_daily_usd'], [0.])
        ci = b.intervals([0., 1., -1., 2.]*30)
        self.assertLessEqual(ci['familywise_lower'], ci['ci95'][0])
        self.assertEqual(ci, b.intervals([0., 1., -1., 2.]*30))


if __name__ == '__main__':
    unittest.main()
