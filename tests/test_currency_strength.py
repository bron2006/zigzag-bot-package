import unittest
from currency_strength import select


class CurrencyStrengthTest(unittest.TestCase):
    def test_recovers_relative_strength_and_selects_available_pair(self):
        scores=dict(EUR=.03,USD=.01,GBP=-.01,JPY=-.03)
        data={a+b:scores[a]-scores[b] for a,b in [('EUR','USD'),('EUR','JPY'),('GBP','USD'),('USD','JPY')]}
        result=select(data)
        self.assertEqual((result['pair'],result['direction']),('EURJPY',1))
        for c,value in scores.items(): self.assertAlmostEqual(result['strengths'][c],value)
        self.assertAlmostEqual(result['residual_rms'],0)

    def test_inverse_quotes_preserve_currency_ranking(self):
        original=dict(EURUSD=.02,EURJPY=.06,GBPUSD=-.02,USDJPY=.04)
        a=select(original)
        b=select({p[3:]+p[:3]:-v for p,v in original.items()})
        self.assertEqual(b['pair'],'JPYEUR')
        self.assertEqual(b['direction'],-1)
        for c in a['strengths']: self.assertAlmostEqual(a['strengths'][c],b['strengths'][c])

    def test_does_not_rank_disconnected_graph(self):
        with self.assertRaises(ValueError): select(dict(EURUSD=.1,GBPJPY=.2))

    def test_flat_market_has_no_setup(self):
        self.assertIsNone(select(dict(EURUSD=0,USDJPY=0,EURJPY=0)))
        self.assertIsNone(select({}))

    def test_input_order_is_irrelevant_and_bad_data_rejected(self):
        data=dict(EURUSD=.02,EURJPY=.06,GBPUSD=-.02,USDJPY=.04)
        self.assertEqual(select(data),select(dict(reversed(list(data.items())))))
        for invalid in ({'BTCUSDT':.1},{'EURUSD':float('nan')}):
            with self.assertRaises(ValueError): select(invalid)
