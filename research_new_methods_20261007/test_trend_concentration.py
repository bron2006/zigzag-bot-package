import unittest
import pandas as pd
from trend_concentration import trade_cycles,concentration

class ConcentrationTests(unittest.TestCase):
    def frame(self,positions):
        return pd.DataFrame(dict(date=pd.date_range('2024-01-01',periods=len(positions),tz='UTC'),
            Open=[100.,110.,120.][:len(positions)],Close=[105.,115.,125.][:len(positions)],position=positions))
    def test_two_sided_fees(self):
        cycles=trade_cycles(self.frame([1,0]),.01)
        self.assertAlmostEqual(cycles[0]['factor'],.99**2*1.1)
        self.assertFalse(cycles[0]['final_liquidation'])
    def test_end_liquidation_is_counted(self):
        cycles=trade_cycles(self.frame([0,1,1]),.01)
        self.assertAlmostEqual(cycles[0]['factor'],.99**2*125/110)
        self.assertTrue(cycles[0]['final_liquidation'])
    def test_no_trades_is_not_missing(self):
        cycles=trade_cycles(self.frame([0,0]),.01)
        self.assertEqual(cycles,[])
        self.assertEqual(concentration(cycles)['total_return'],0)
    def test_sensitivity_is_product_not_sum(self):
        result=concentration([dict(factor=2.),dict(factor=.5)])
        self.assertAlmostEqual(result['total_return'],0)
        self.assertAlmostEqual(result['return_without_best_cycle'],-.5)

if __name__=='__main__':unittest.main()
