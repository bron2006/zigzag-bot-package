import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('fibonacci_research',Path(__file__).resolve().parents[1]/'research_fibonacci_20261013'/'screen.py')
fib=importlib.util.module_from_spec(spec);spec.loader.exec_module(fib)


def bar(ts,o=106,h=106,l=104.5,c=105):return dict(ts=ts,Open=o,High=h,Low=l,Close=c)


class FibonacciResearchTest(unittest.TestCase):
    def detect(self,rows,side=1,known=0):
        a=dict(key=(side,1,2),side=side,origin=100 if side==1 else 110,target=110 if side==1 else 100,known=known)
        with patch.object(fib,'anchors',return_value=[(known,a)]):return fib.detect(rows,pip=.01)

    def test_zone_touch_and_later_bullish_close_break_required(self):
        rows=[bar(0),bar(300,o=105,h=108,l=104,c=107)]
        intent=self.detect(rows)[0]
        self.assertEqual((intent['side'],intent['ts'],intent['target']),(1,600,110))
        self.assertAlmostEqual(intent['stop'],103.81)
        self.assertEqual(self.detect(rows+[bar(600,o=107,h=110,l=104,c=109)]),[intent])

    def test_wick_without_closing_confirmation_does_not_enter(self):
        self.assertEqual(self.detect([bar(0),bar(300,o=105,h=108,l=104,c=105.5)]),[])

    def test_stop_touch_before_entry_invalidates_anchor(self):
        self.assertEqual(self.detect([bar(0,l=103),bar(300,o=105,h=108,l=104,c=107)]),[])

    def test_anchor_unavailable_before_confirmation_time(self):
        self.assertEqual(self.detect([bar(0),bar(300,o=105,h=108,l=104,c=107)],known=600),[])

    def test_short_is_mirrored(self):
        rows=[bar(0,o=104,h=105.5,l=103,c=105),bar(300,o=105,h=106,l=102,c=102.5)]
        intent=self.detect(rows,-1)[0]
        self.assertEqual(intent['side'],-1)
        self.assertAlmostEqual(intent['stop'],106.19)
        self.assertEqual(intent['target'],100)

    def test_confirmed_H1_pivots_do_not_change_when_future_added(self):
        prices=[100,102,106,103,101,104,109,105,103,106,112,108,106,109,115,110,108,111]
        rows=[bar(h*3600+m*300,o=p,h=p+1,l=p-1,c=p) for h,p in enumerate(prices) for m in range(12)]
        cutoff=14*3600
        before=fib.anchors([r for r in rows if r['ts']<cutoff]);after=fib.anchors(rows)
        self.assertEqual(before,[e for e in after if e[0]<=cutoff])
        self.assertTrue(any(a is not None for _,a in before))
        for t,a in after:
            if a:
                self.assertGreaterEqual(a['known'],max(a['key'][1:])+3*3600)

    def test_incomplete_H1_cannot_confirm_a_swing(self):
        rows=[bar(i*300) for i in range(59)]
        self.assertEqual(len(fib.anchors(rows)),4)
        self.assertTrue(all(a is None for _,a in fib.anchors(rows)))

    def test_next_open_target_and_unknown_paths(self):
        rows=[bar(0),bar(300,o=105,h=108,l=104,c=107)]
        intents=self.detect(rows)
        self.assertEqual(fib.replay(rows,intents,.02)[0]['status'],'unknown')
        rows.append(bar(600,o=107,h=111,l=106,c=110))
        result=fib.replay(rows,intents,.02)[0]
        self.assertEqual((result['entry'],result['target'],result['reason']),(107,110,'target'))
        rows[-1]=bar(600,o=103,h=104,l=102,c=103)
        self.assertEqual(fib.replay(rows,intents,.02)[0]['status'],'skipped')

    def test_M5_gap_does_not_confirm_using_previous_nonadjacent_bar(self):
        self.assertEqual(self.detect([bar(0),bar(600,o=105,h=108,l=104,c=107)]),[])
