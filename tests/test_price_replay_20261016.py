import unittest
from research_dispatch_20261016.price_replay import simulate


class StablePriceReplayTests(unittest.TestCase):
    def test_touch_not_lost_to_subtraction_residue(self):
        b={0:dict(Open=1.16,High=1.16082,Low=1.15959,Close=1.16)}
        # Equal target AND stop: explicit stop-first after removing binary noise.
        for distance in (.00041,.00041000000000002146):
            row=simulate(b,0,3600,1,distance,.0002)
            self.assertEqual(row['reason'],'stop')
            self.assertTrue(row['ambiguous'])
            self.assertAlmostEqual(row['net_R'],-1)

    def test_missing_path_remains_unknown(self):
        b={0:dict(Open=1.,High=1.001,Low=.999,Close=1.)}
        self.assertEqual(simulate(b,0,3600,1,.01,.001)['status'],'unknown')
        self.assertEqual(simulate({},0,3600,1,.01,.001)['reason'],'missing_entry')

    def test_adverse_gap_and_early_exit(self):
        b={0:dict(Open=1.,High=1.001,Low=.999,Close=1.),
           300:dict(Open=.98,High=.985,Low=.975,Close=.98)}
        row=simulate(b,0,3600,1,.01,.001)
        self.assertEqual(row['reason'],'gap_stop')
        self.assertEqual(row['exit'],.98)
        self.assertEqual(row['exit_ts'],600)
        self.assertLess(row['net_R'],-1)

    def test_favorable_gap_not_extra_target_profit(self):
        b={0:dict(Open=1.,High=1.001,Low=.999,Close=1.),
           300:dict(Open=1.04,High=1.05,Low=1.03,Close=1.04)}
        row=simulate(b,0,3600,1,.01,.001)
        self.assertEqual(row['reason'],'target')
        self.assertEqual(row['exit'],1.02)

    def test_invalid_terms(self):
        for distance,cost in ((float('nan'),0),(.01,-1),(0,0)):
            with self.assertRaises(ValueError):simulate({},0,3600,1,distance,cost)


if __name__=='__main__':unittest.main()
