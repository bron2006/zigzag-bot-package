import unittest
from research_funding_20261008.screen import month_simulation,lower_ci,public
from local_trend_bot.strategy import DAY


def bar(ts,price,high=None):
    return [ts,price,high or price,price,price]


def payment(ts,rate,price=100):
    return dict(fundingTime=ts,fundingRate=str(rate),markPrice=str(price))


class FundingTests(unittest.TestCase):
    def test_flat_hedge_exact_costs(self):
        rows=[bar(0,100)]
        result,_=month_simulation(rows,rows,rows,[],1000,.0015,.001)
        self.assertAlmostEqual(result['end_nav'],997.5)
        self.assertEqual(result['funding_cash'],0)
        self.assertEqual(result['basis_cash'],0)
    def test_price_direction_cancelled_same_quantity(self):
        spot=[bar(0,100),bar(DAY,120)]
        result,_=month_simulation(spot,spot,spot,[],1000,0,0)
        self.assertEqual(result['end_nav'],1000)
        self.assertEqual(result['basis_cash'],0)
    def test_short_collects_positive_and_pays_negative(self):
        rows=[bar(0,100)]
        rates=[payment(1,.01),payment(2,-.02)]
        result,_=month_simulation(rows,rows,rows,rates,1000,0,0)
        self.assertEqual(result['funding_cash'],-5)
        self.assertEqual(result['end_nav'],995)
        self.assertEqual(result['negative_funding_events'],1)
    def test_funding_cash_uses_event_mark_not_initial_notional(self):
        rows=[bar(0,100)]
        result,_=month_simulation(rows,rows,rows,[payment(1,.01,200)],1000,0,0)
        self.assertEqual(result['funding_cash'],10)
    def test_no_funding_at_or_before_entry_or_after_exit(self):
        rows=[bar(0,100)]
        rates=[payment(-1,1),payment(0,1),payment(DAY,1),payment(DAY-1,.01)]
        result,_=month_simulation(rows,rows,rows,rates,1000,0,0)
        self.assertEqual(result['funding_events'],1)
        self.assertEqual(result['funding_cash'],5)
    def test_basis_change_not_hidden_as_funding(self):
        spot=[bar(0,100),bar(DAY,100)]
        future=[bar(0,101),bar(DAY,99)]
        result,_=month_simulation(spot,future,future,[],1000,0,0)
        self.assertEqual(result['basis_cash'],10)
        self.assertEqual(result['end_nav'],1010)
    def test_margin_can_fail_while_total_hedged_nav_flat(self):
        rows=[bar(0,100),bar(DAY,220)]
        result,_=month_simulation(rows,rows,rows,[],1000,0,0)
        self.assertEqual(result['end_nav'],1000)
        self.assertIn(DAY,result['margin_violations'])
        self.assertLess(result['min_margin_stress_ratio'],0)
    def test_same_day_positive_funding_not_used_before_intraday_high(self):
        rows=[bar(0,100)]
        mark=[bar(0,100,220)]
        result,_=month_simulation(rows,rows,mark,[payment(1,.5)],1000,0,0)
        self.assertIn(0,result['margin_violations'])
        self.assertEqual(result['end_nav'],1250)
    def test_stress_costs_worse(self):
        rows=[bar(0,100)]
        base,_=month_simulation(rows,rows,rows,[],1000,.0015,.001)
        stress,_=month_simulation(rows,rows,rows,[],1000,.003,.002)
        self.assertLess(stress['end_nav'],base['end_nav'])
    def test_alignment_required(self):
        with self.assertRaises(ValueError):month_simulation([bar(0,100)],[bar(DAY,100)],[bar(0,100)],[],1000,0,0)
    def test_cash_comparator_negative_lower_for_negative_returns(self):
        self.assertLess(lower_ci([-.01]*21),0)
        self.assertEqual(lower_ci([0]*21),0)
    def test_private_route_refused(self):
        with self.assertRaises(ValueError):public('order')


if __name__=='__main__':unittest.main()
