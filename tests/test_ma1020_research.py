import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('ma1020_screen',Path(__file__).resolve().parents[1]/'research_ma1020_20261013'/'screen.py')
ma=importlib.util.module_from_spec(spec);spec.loader.exec_module(ma)


def bars():
    rows=[dict(ts=i*900,Open=100.,High=101.,Low=99.,Close=100.,Volume=10.) for i in range(45)]
    rows.append(dict(ts=45*900,Open=103.,High=105.,Low=103.,Close=104.,Volume=40.))
    return rows


class MATest(unittest.TestCase):
    def test_closed_cross_volume_and_previous_volume_baseline(self):
        r=ma.detect(bars(),900)[0]
        self.assertEqual(r['ts'],46*900)
        self.assertEqual(r['volume_baseline'],10)
        self.assertAlmostEqual(r['stop'],98.99)

    def test_no_volume_confirmation_does_not_trigger(self):
        rows=bars();rows[-1]['Volume']=10
        self.assertEqual(ma.detect(rows,900),[])
        self.assertEqual(len(ma.detect(rows,900,volume=False)),1)

    def test_SMA_and_EMA_decisions_do_not_repaint_with_future(self):
        rows=bars();later=rows+[dict(ts=46*900,Open=104.,High=110.,Low=103.,Close=109.,Volume=1000.)]
        for kind in ('SMA','EMA'):self.assertEqual(ma.detect(rows,900,kind),ma.detect(later,900,kind)[:1])

    def test_gap_resets_warmup(self):
        rows=bars();rows[-1]['ts']+=900
        self.assertEqual(ma.detect(rows,900),[])

    def test_samebar_both_levels_stop_first_and_gap_loss_exceeds_R(self):
        intent=dict(ts=0,stop=98)
        r=ma.simulate(intent,[dict(ts=0,Open=100,High=105,Low=97,Close=100)],.2,900)
        self.assertEqual(r['reason'],'stop');self.assertTrue(r['ambiguous'])
        path=[dict(ts=0,Open=100,High=101,Low=99,Close=100),dict(ts=900,Open=95,High=96,Low=94,Close=95)]
        self.assertLess(ma.simulate(intent,path,.2,900)['net_R'],-1)

    def test_no_forced_time_exit_or_fake_unknown_zero(self):
        intent=dict(ts=0,stop=98)
        r=ma.simulate(intent,[dict(ts=0,Open=100,High=101,Low=99,Close=100)],.2,900)
        self.assertEqual(r['status'],'unknown');self.assertNotIn('net_R',r)

    def test_one_position_and_unknown_halts_arm(self):
        path=[dict(ts=t,Open=100,High=101,Low=99,Close=100) for t in (0,900,1800)]
        results,skips=ma.replay(path,[dict(ts=0,stop=98),dict(ts=900,stop=98)],900,.002)
        self.assertEqual(len(results),1);self.assertEqual(results[0]['status'],'unknown')
