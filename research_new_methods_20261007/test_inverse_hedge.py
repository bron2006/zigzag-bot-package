import unittest
from fetch_inverse_prices import validate,HOUR
from inverse_hedge_screen import simulate,funding_issues
from batched_funding_screen import quantity,simulate as batch_simulate


class InverseHedgeTests(unittest.TestCase):
    def test_lot_rounding(self):
        self.assertEqual(quantity(.012345,.00001),.01234)
        self.assertEqual(quantity(.012345,.00001,True),.01235)

    def test_batched_tiny_funding_not_sold_and_marked_residual_separate(self):
        prices={t:60000.0 for t in range(HOUR,10*HOUR,HOUR)}
        rows=[{'fundingTime':8*HOUR+3,'fundingRate':'.0001','markPrice':'60000'}]
        r=batch_simulate(prices,prices,rows,HOUR,9*HOUR,.00001)
        self.assertEqual(r['funding_coin_conversion_operations'],0)
        self.assertAlmostEqual(r['ending_marked_equity_usd'],r['ending_cash_usd']+r['remaining_coin_value_usd'])
        self.assertAlmostEqual(r['residual_price_and_reinvestment_effect_usd'],0)

    def test_negative_funding_buys_minimum_and_keeps_change(self):
        prices={t:60000.0 for t in range(HOUR,10*HOUR,HOUR)}
        rows=[{'fundingTime':8*HOUR+3,'fundingRate':'-.001','markPrice':'60000'}]
        r=batch_simulate(prices,prices,rows,HOUR,9*HOUR,.00001)
        self.assertEqual(r['funding_coin_conversion_operations'],1)
        self.assertLess(r['gross_funding_at_receipt_proxy_usd'],0)
        self.assertTrue(r['cash_reserve_nonnegative'])

    def test_retained_funding_coin_exposure_not_hidden(self):
        prices={t:60000.0 if t<9*HOUR else 30000.0 for t in range(HOUR,11*HOUR,HOUR)}
        rows=[{'fundingTime':8*HOUR+3,'fundingRate':'.0001','markPrice':'60000'}]
        r=batch_simulate(prices,prices,rows,HOUR,10*HOUR,.00001)
        self.assertLess(r['residual_price_and_reinvestment_effect_usd'],0)

    def test_bad_hourly_data_rejected(self):
        for rows in ([],[[0,'NaN',2,1,1]],[[0,2,1,1,2]],[[HOUR,1,1,1,1]]):
            with self.assertRaises(ValueError):validate(rows,0)

    def test_constant_prices_fees_and_funding_reconcile(self):
        spot=mark={t:60000.0 for t in range(HOUR,17*HOUR,HOUR)}
        rows=[{'fundingTime':8*HOUR+3,'fundingRate':'.0001','markPrice':'60000'},
              {'fundingTime':16*HOUR+3,'fundingRate':'.0001','markPrice':'60000'}]
        # Last funding occurs AFTER end snapshot and must not be credited.
        result=simulate(spot,mark,rows,HOUR,16*HOUR)
        self.assertEqual(result['funding_records'],1)
        self.assertAlmostEqual(result['gross_funding_usd'],.09)
        self.assertAlmostEqual(result['profit_usd'],.09-.00009-1.35045-1.34955)

    def test_no_preentry_funding_and_negative_charge(self):
        prices={t:60000.0 for t in range(HOUR,10*HOUR,HOUR)}
        rows=[{'fundingTime':0,'fundingRate':'1','markPrice':'60000'},
              {'fundingTime':8*HOUR+3,'fundingRate':'-.0001','markPrice':'60000'}]
        r=simulate(prices,prices,rows,HOUR,9*HOUR)
        self.assertEqual(r['funding_records'],1);self.assertAlmostEqual(r['gross_funding_usd'],-.09)

    def test_missing_schedule_or_mark_unknown(self):
        self.assertTrue(funding_issues([],HOUR,17*HOUR)[1])
        rows=[{'fundingTime':8*HOUR,'fundingRate':'.0001','markPrice':''}]
        self.assertTrue(funding_issues(rows,HOUR,9*HOUR)[1])

    def test_price_move_hedge_and_stress_fees(self):
        spot=mark={t:60000.0 if t<4*HOUR else 120000.0 for t in range(HOUR,8*HOUR,HOUR)}
        base=simulate(spot,mark,[],HOUR,7*HOUR)
        stress=simulate(spot,mark,[],HOUR,7*HOUR,True)
        self.assertAlmostEqual(base['basis_valuation_change_usd'],0)
        self.assertAlmostEqual(base['minimum_margin_coin_over_notional_coin'],1)
        self.assertLess(stress['profit_usd'],base['profit_usd'])


if __name__=='__main__':unittest.main()
