import unittest
from carry_screen import get,measure,average_fill

class CarryScreenTests(unittest.TestCase):
    def setUp(self):
        self.spot=dict(askPrice='100',bidPrice='99.9',askQty='2')
        self.future=dict(bidPrice='102',askPrice='102.1',bidQty='1')
    def test_buy_ask_sell_bid_and_cost(self):
        r=measure(self.spot,self.future,86400000*100,0)
        self.assertAlmostEqual(r['gross_gap'],.02)
        self.assertAlmostEqual(r['net_cost_008'],.012)
        self.assertEqual(r['quoted_common_top_level_quantity'],1)
        self.assertAlmostEqual(r['stress_simple_annualized_on_illustrative_2x_capital'],.006*365.25/100)
    def test_backwardation_is_not_profit(self):
        self.future.update(bidPrice='98')
        self.assertLess(measure(self.spot,self.future,86400000,0)['net_cost_008'],0)
    def test_expired_rejected(self):
        with self.assertRaises(ValueError): measure(self.spot,self.future,0,0)
    def test_crossed_book_rejected(self):
        self.future['bidPrice']='103'
        with self.assertRaises(ValueError): measure(self.spot,self.future,86400000,0)
    def test_private_endpoint_rejected_before_network(self):
        with self.assertRaises(ValueError): get('https://fapi.binance.com','/fapi/v1/order')
    def test_depth_consumes_multiple_levels(self):
        self.assertAlmostEqual(average_fill([['100','1'],['102','2']],2),101.)
    def test_insufficient_depth_is_unknown(self):
        self.assertIsNone(average_fill([['100','1']],2))

if __name__=='__main__': unittest.main()
