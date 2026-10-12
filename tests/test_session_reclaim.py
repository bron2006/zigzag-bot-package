import unittest
from session_reclaim import setup,entry_terms


class SessionReclaimTest(unittest.TestCase):
    def test_failed_high_and_low_break_are_symmetric(self):
        short=setup(dict(Open=110,High=112,Low=108,Close=109),110,90,2)
        long=setup(dict(Open=90,High=92,Low=88,Close=91),110,90,2)
        self.assertEqual(short['direction'],-1)
        self.assertEqual(long['direction'],1)
        self.assertAlmostEqual(short['stop'],112.2)
        self.assertAlmostEqual(long['stop'],87.8)
        self.assertEqual(short['target'],100)
        self.assertIsNotNone(entry_terms(short,109,.5))

    def test_continuation_outside_range_and_double_sweep_are_not_entries(self):
        self.assertIsNone(setup(dict(Open=110,High=113,Low=109,Close=112),110,90,2))
        self.assertIsNone(setup(dict(Open=100,High=112,Low=88,Close=99),110,90,2))

    def test_gap_and_cost_can_cancel_before_trade(self):
        intent=setup(dict(Open=110,High=112,Low=108,Close=109),110,90,2)
        self.assertIsNone(entry_terms(intent,99,.5))
        self.assertIsNone(entry_terms(intent,113,.5))
        self.assertIsNone(entry_terms(intent,101,5))

    def test_invalid_history_rejected(self):
        with self.assertRaises(ValueError): setup(dict(Open=110,High=100,Low=90,Close=109),110,90,2)
