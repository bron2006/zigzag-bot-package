import importlib.util
from pathlib import Path
import unittest
from test_ny_h4_reclaim import fixture,bar

spec=importlib.util.spec_from_file_location('ny_repeat_compare',Path(__file__).resolve().parents[1]/'research_ny_h4_20261013'/'compare.py')
compare=importlib.util.module_from_spec(spec);spec.loader.exec_module(compare)
sys_path=__import__('sys').path
sys_path.insert(0,str(Path(__file__).resolve().parents[1]/'research_ny_h4_20261013'))
from alternatives import continuation,regimes,aligned


class RepeatResearchTest(unittest.TestCase):
    def test_continuation_is_not_reclaim_and_does_not_use_wick_break(self):
        rows,end=fixture()
        rows += [bar(end,o=100,h=108,l=99,c=101),bar(end+300,o=101,h=108,l=100,c=106)]
        intent=continuation(rows)[0]
        self.assertEqual((intent['side'],intent['stop'],intent['ts']),(1,100,end+600))

    def test_H1_filter_uses_only_complete_past_hours(self):
        rows=[dict(ts=i*300,Open=100+i*.01,High=101+i*.01,Low=99+i*.01,Close=100+i*.01) for i in range(52*12)]
        cutoff=51*3600
        early=regimes([b for b in rows if b['ts']<cutoff])
        full=regimes(rows)
        intents=[dict(ts=cutoff,side=1)]
        self.assertEqual(aligned(intents,early),aligned(intents,full))
        self.assertEqual(aligned([dict(ts=49*3600,side=1)],full),[])
        self.assertEqual(aligned([dict(ts=cutoff+10*3600,side=1)],full),[])

    def test_distinct_break_and_return_required_for_each_entry(self):
        rows,end=fixture()
        rows += [bar(end),bar(end+300,o=94,h=97,l=94,c=96),bar(end+600,o=96,h=100,l=95,c=99),
                 bar(end+900),bar(end+1200,o=94,h=97,l=92,c=96)]
        setups=compare.repeated(rows)
        self.assertEqual([r['ts'] for r in setups],[end+600,end+1500])
        self.assertEqual([r['sequence'] for r in setups],[1,2])
        self.assertEqual([r['stop'] for r in setups],[93,92])

    def test_future_candles_do_not_change_prior_repeat_entries(self):
        rows,end=fixture();rows += [bar(end),bar(end+300,o=94,h=97,l=94,c=96)]
        before=compare.repeated(rows)
        rows.append(bar(end+600,o=96,h=1000,l=1,c=500))
        self.assertEqual(compare.repeated(rows)[:len(before)],before)

    def test_missing_path_never_counted_as_zero_pnl(self):
        rows,end=fixture();rows += [bar(end),bar(end+300,o=94,h=97,l=94,c=96)]
        results,_=compare.replay(rows,compare.repeated(rows),.0004)
        self.assertEqual(results[0]['status'],'unknown')
        self.assertNotIn('net_R',results[0])

    def test_nonoverlap_blocks_new_entry_during_position_or_unknown_path(self):
        rows,end=fixture()
        rows += [bar(end,l=90),bar(end+300,o=94,h=97,l=94,c=96),bar(end+600,o=96,h=97,l=95,c=96),
                 bar(end+900),bar(end+1200,o=94,h=97,l=92,c=96),bar(end+1500,o=96,h=97,l=95,c=96)]
        intents=compare.repeated(rows)
        self.assertEqual(len(intents),2)
        results,skips=compare.replay(rows,intents,.0004,True)
        self.assertEqual(len(results),1)
        self.assertEqual(skips,1)
