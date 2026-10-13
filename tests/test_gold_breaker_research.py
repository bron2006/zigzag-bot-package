import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('gold_breaker_screen',Path(__file__).resolve().parents[1]/'research_gold_breaker_20261013'/'screen.py')
gold=importlib.util.module_from_spec(spec);spec.loader.exec_module(gold)


def bar(t,o,h,l,c):return dict(ts=t,Open=o,High=h,Low=l,Close=c)


def sequence():
    return [bar(0,99,100,98,99),bar(60,100,102,99,101),bar(120,100,101,98,99),
            bar(180,98,100,96,97),bar(240,100,105,98,104),bar(300,105,110,103,108),
            bar(360,106,108,100,103),bar(420,100,102,94,95)]


class GoldBreakerTest(unittest.TestCase):
    def detect(self,rows):
        with patch.object(gold,'anchor_events',return_value=[dict(ts=0,high=108,low=90,anchor_ts=-3600)]):return gold.detect(rows)

    def test_sweep_is_not_immediate_entry_and_prior_pivots_retained(self):
        rows=sequence()
        self.assertEqual(self.detect(rows[:6]),[])
        order=self.detect(rows)[0]
        self.assertEqual((order['side'],order['entry'],order['ts']),(-1,96,480))
        self.assertAlmostEqual(order['stop'],110.01)
        self.assertAlmostEqual(order['target'],67.98)

    def test_long_mirrors_short_and_entry_is_old_structure_edge(self):
        rows=[bar(b['ts'],200-b['Open'],200-b['Low'],200-b['High'],200-b['Close']) for b in sequence()]
        with patch.object(gold,'anchor_events',return_value=[dict(ts=0,high=110,low=92,anchor_ts=-3600)]):orders=gold.detect(rows)
        o=orders[0];self.assertEqual((o['side'],o['entry']),(1,104))
        self.assertAlmostEqual(o['stop'],89.99)

    def test_future_does_not_rewrite_order_decision(self):
        rows=sequence();before=self.detect(rows)[0]
        after=self.detect(rows+[bar(480,95,100,90,96)])[0]
        self.assertEqual(before,after)

    def test_both_anchor_edges_same_bar_is_ambiguous_not_entry(self):
        rows=sequence();rows[0]=bar(0,99,109,89,99)
        self.assertEqual(self.detect(rows),[])

    def test_gap_invalidates_structure(self):
        rows=sequence();rows.pop(2)
        self.assertEqual(self.detect(rows),[])

    def order(self):return dict(ts=0,side=-1,entry=100,stop=102,target=96,expires=None)

    def test_limit_retest_not_entry_at_confirmation_close(self):
        o=self.order()
        self.assertEqual(gold.outcome(o,[bar(0,98,99,97,98)],.5)['status'],'pending')
        path=[bar(0,99,100.1,98,99),bar(60,99,100,95,96)]
        r=gold.outcome(o,path,.5)
        self.assertEqual(r['reason'],'target');self.assertAlmostEqual(r['net_R'],1.4)

    def test_entry_and_target_same_bar_is_unknown(self):
        r=gold.outcome(self.order(),[bar(0,99,101,95,96)],.5)
        self.assertEqual(r['status'],'unknown')

    def test_stop_first_ambiguous_and_adverse_gap(self):
        o=self.order()
        r=gold.outcome(o,[bar(0,99,103,95,100)],.5)
        self.assertEqual(r['reason'],'stop');self.assertTrue(r['ambiguous'])
        r=gold.outcome(o,[bar(0,99,100.1,98,99),bar(60,103,104,102,103)],.5)
        self.assertEqual(r['reason'],'stop_gap');self.assertLess(r['net_R'],-1)

    def test_expiry_cancels_unfilled_not_filled_position(self):
        o=dict(self.order(),expires=60)
        self.assertEqual(gold.outcome(o,[bar(0,98,99,97,98),bar(60,99,100.1,98,99)],.5)['status'],'cancelled')
        r=gold.outcome(o,[bar(0,99,100.1,98,99),bar(60,99,100,95,96)],.5)
        self.assertEqual(r['reason'],'target')

    def test_path_gap_after_fill_is_not_fake_return(self):
        r=gold.outcome(self.order(),[bar(0,99,100.1,98,99),bar(120,99,100,95,96)],.5)
        self.assertEqual(r['status'],'unknown')

    def test_big_H1_only_known_after_close_and_prior_ATR_warmup(self):
        rows=[]
        for h in range(15):
            for m in range(60):rows.append(bar(h*3600+m*60,100,101,99,100))
        for m in range(60):rows.append(bar(15*3600+m*60,100,104,99.9,103.8))
        self.assertEqual(gold.anchor_events(rows[:-1],'main'),[])
        events=gold.anchor_events(rows,'main')
        self.assertEqual(len(events),1);self.assertEqual(events[0]['ts'],16*3600)
