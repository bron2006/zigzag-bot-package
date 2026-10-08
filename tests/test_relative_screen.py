import unittest
from research_funding_20261008.relative import ranking,leg
from local_trend_bot.strategy import DAY


def bar(ts,price,high=None,low=None):
    return [ts,price,high or price,low or price,price]


class RelativeTests(unittest.TestCase):
    def test_ranking_uses_full_month_buffer(self):
        prices={'BTCUSDT':{'2022-11':100,'2023-11':120,'2023-12':1},
                'ETHUSDT':{'2022-11':100,'2023-11':110,'2023-12':1000}}
        self.assertEqual(ranking(prices,'2024-01'),(1,'2023-11'))
    def test_relative_tie_cash(self):
        prices={s:{'2022-11':100,'2023-11':120} for s in ('BTCUSDT','ETHUSDT')}
        self.assertEqual(ranking(prices,'2024-01')[0],0)
    def test_long_and_short_price_sign(self):
        rows=[bar(0,100),bar(DAY,120)]
        long,_=leg(rows,rows,[],1,500,0)
        short,_=leg(rows,rows,[],-1,500,0)
        self.assertEqual(long['end_cash'],600)
        self.assertEqual(short['end_cash'],400)
        self.assertEqual(long['end_cash']+short['end_cash'],1000)
    def test_funding_signs_and_two_fees(self):
        rows=[bar(0,100)]
        rates=[dict(fundingTime=1,fundingRate='.01',markPrice='100')]
        long,_=leg(rows,rows,rates,1,500,.001)
        short,_=leg(rows,rows,rates,-1,500,.001)
        self.assertEqual(long['end_cash'],494)
        self.assertEqual(short['end_cash'],504)
    def test_long_margin_stress_uses_low(self):
        rows=[bar(0,100)]
        mark=[bar(0,100,low=.01)]
        result,_=leg(rows,mark,[],1,500,.001)
        self.assertIn(0,result['violation_days'])
    def test_short_margin_stress_uses_high(self):
        rows=[bar(0,100)]
        mark=[bar(0,100,high=220)]
        result,_=leg(rows,mark,[],-1,500,0)
        self.assertIn(0,result['violation_days'])
    def test_funding_at_entry_not_collected(self):
        rows=[bar(0,100)]
        rates=[dict(fundingTime=0,fundingRate='1',markPrice='100')]
        result,_=leg(rows,rows,rates,-1,500,0)
        self.assertEqual(result['funding_cash'],0)


if __name__=='__main__':unittest.main()
