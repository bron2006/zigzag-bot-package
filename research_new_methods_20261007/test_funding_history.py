import unittest
from funding_history_screen import validate,summarize,START,END
from industry_paper_profile import paper_weights
from test_external_reference import fixture
from inverse_hedge_math import short_pnl_coin,equity_usd,funding_usd_if_immediately_converted
import numpy as np


class FundingAndSourceTests(unittest.TestCase):
    def test_funding_negative_rates_not_discarded(self):
        rows=[{'symbol':'BTCUSDT','fundingTime':START,'fundingRate':'.0001'},
              {'symbol':'BTCUSDT','fundingTime':START+28800000,'fundingRate':'-.0002'}]
        validate(rows,'BTCUSDT',START);year=summarize(rows)['2023']
        self.assertAlmostEqual(year['sum_settled_rate'],-.0001)
        self.assertEqual(year['negative_count'],1)

    def test_duplicate_or_wrong_symbol_rejected(self):
        row={'symbol':'BTCUSDT','fundingTime':START,'fundingRate':'.0001'}
        with self.assertRaises(ValueError):validate([row,row],'BTCUSDT',START)
        with self.assertRaises(ValueError):validate([row],'ETHUSDT',START)

    def test_future_boundary_and_nonfinite_rejected(self):
        with self.assertRaises(ValueError):validate([{'symbol':'BTCUSDT','fundingTime':END,'fundingRate':'.01'}],'BTCUSDT',START)
        with self.assertRaises(ValueError):validate([{'symbol':'BTCUSDT','fundingTime':START,'fundingRate':'NaN'}],'BTCUSDT',START)

    def test_partial_year_not_annualized(self):
        row={'symbol':'BTCUSDT','fundingTime':END-28800000,'fundingRate':'.0001'}
        self.assertIsNone(summarize([row])['2026']['component_after_004cost_on_arbitrary_2capital'])

    def test_gap_not_filled(self):
        rows=[{'fundingTime':START,'fundingRate':'.0001'},
              {'fundingTime':START+57600000,'fundingRate':'.0001'}]
        year=summarize(rows)['2023']
        self.assertEqual(year['observations'],2);self.assertEqual(year['gaps_over_8h_tolerance'],1)

    def test_paper_source_profile_causal_and_cap(self):
        r,_=fixture();w=paper_weights(r);changed=r.copy();changed.iloc[150:]=-.1
        np.testing.assert_allclose(w.iloc[:150],paper_weights(changed).iloc[:150])
        self.assertTrue((w.sum(axis=1)<=2+1e-12).all());self.assertTrue((w>=0).all().all())

    def test_inverse_short_uses_correct_profit_sign(self):
        self.assertGreater(short_pnl_coin(900,60000,30000),0)
        self.assertLess(short_pnl_coin(900,60000,120000),0)

    def test_ideal_hedge_constant_equity_not_double_counting_spot(self):
        for price in (12000,30000,60000,120000,300000):
            result=equity_usd(900/60000,900,60000,price,price,100)
            self.assertAlmostEqual(result['equity_usd'],1000)
            self.assertGreater(result['margin_coin'],0)

    def test_basis_difference_is_not_assumed_zero(self):
        result=equity_usd(900/60000,900,60000,60000,57000,100)
        self.assertAlmostEqual(result['equity_usd'],955)

    def test_funding_conversion_uses_price_ratio_and_keeps_negative(self):
        self.assertAlmostEqual(funding_usd_if_immediately_converted(900,.0001,60000,57000),.0855)
        self.assertLess(funding_usd_if_immediately_converted(900,-.0001,60000,60000),0)

    def test_invalid_inverse_prices_rejected(self):
        with self.assertRaises(ValueError):short_pnl_coin(900,0,60000)


if __name__=='__main__':unittest.main()
