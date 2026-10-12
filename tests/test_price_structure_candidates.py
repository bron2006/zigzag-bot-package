import copy
import unittest
from price_structure_candidates import generate,RULES


def history():
    return [dict(ts=i*3600,Open=100.,High=100.5,Low=99.5,Close=100.) for i in range(40)]


class StructureTest(unittest.TestCase):
    def test_all_three_rules_produce_a_nonempty_causal_setup(self):
        for rule in RULES:
            bars=history()
            if rule=='channel24':bars[32].update(High=103.,Close=102.)
            if rule=='compression':
                bars[31].update(High=100.1,Low=99.9)
                bars[32].update(High=101.,Close=100.8)
            if rule=='failed24':
                for b in bars:b.update(High=105.,Low=95.)
                bars[32].update(Open=95.,High=96.,Low=94.9,Close=95.2)
            out=generate(bars,rule)
            self.assertTrue(out,rule)
            self.assertEqual(out[0]['ts'],33*3600)
            self.assertEqual(out[0]['side'],1)
            self.assertEqual(generate(bars[:33],rule),out[:1])

    def test_prefix_invariance_no_future_peeking(self):
        bars=history();bars[32].update(High=103.,Close=102.)
        prefix=generate(bars[:33],'channel24')
        future=copy.deepcopy(bars)
        for b in future[33:]:b.update(Open=1000.,High=1001.,Low=999.,Close=1000.)
        self.assertEqual([s for s in generate(future,'channel24') if s['ts']<=33*3600],prefix)

    def test_missing_hour_resets_range_warmup(self):
        bars=history();bars[32].update(High=103.,Close=102.)
        self.assertEqual(generate(bars[:20]+bars[21:],'channel24'),[])

    def test_opposite_price_reflection_flips_direction(self):
        bars=history();bars[32].update(High=103.,Close=102.)
        mirrored=[dict(ts=b['ts'],Open=200-b['Open'],High=200-b['Low'],Low=200-b['High'],Close=200-b['Close']) for b in bars]
        self.assertEqual(generate(bars,'channel24')[0]['side'],-generate(mirrored,'channel24')[0]['side'])

    def test_invalid_data_or_unordered_hours_fail(self):
        bars=history();bars[10]['Close']=float('nan')
        with self.assertRaises(ValueError):generate(bars,'channel24')
        bars=history();bars[10]['ts']=bars[9]['ts']
        with self.assertRaises(ValueError):generate(bars,'channel24')
