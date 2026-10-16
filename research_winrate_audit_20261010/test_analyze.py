import unittest
import analyze as a


def row(**changes):
    r = dict(outcome='up_timed', entry_price=100., exit_price=101., verdict='BUY',
             entry_ts='2026-10-09T10:00:00', score=20)
    r.update(changes)
    return r


class AnalysisTests(unittest.TestCase):
    def test_unknown_and_legacy_excluded(self):
        s = a.stats([row(), row(outcome='unknown'), row(outcome='up')])
        self.assertEqual((s['measured'], s['wins'], s['unknown'], s['legacy_unverified']), (1, 1, 1, 1))

    def test_sell_and_small_flat_moves(self):
        self.assertTrue(a.direction(row(verdict='SELL', exit_price=99.)))
        self.assertTrue(a.direction(row(outcome='flat_timed', exit_price=100.0001)))
        self.assertFalse(a.direction(row(exit_price=99.)))

    def test_current_tie_policy_is_explicit(self):
        s = a.stats([row(exit_price=100.)])
        self.assertEqual((s['losses'], s['ties_counted_as_losses']), (1, 1))

    def test_invalid_price_not_success(self):
        self.assertIsNone(a.direction(row(exit_price=float('nan'))))
        self.assertIsNone(a.direction(row(entry_price=0.)))

    def test_break_even_and_hypothetical_not_profit(self):
        rows = [row()]*5+[row(exit_price=99.)]*4
        s = a.stats(rows)
        self.assertAlmostEqual(s['hypothetical_return_per_unit_stake']['0.8'], 0.)

    def test_wilson_uncertainty_small_samples(self):
        lo, hi = a.wilson(1, 1)
        self.assertLess(lo, 25.)
        self.assertAlmostEqual(hi, 100.)
        self.assertIsNone(a.wilson(0, 0))


if __name__ == '__main__':
    unittest.main()
