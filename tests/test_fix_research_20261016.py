import importlib.util
from datetime import date
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('fix_test_candidate',ROOT/'research_fix_20261016'/'run.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

class FixTests(unittest.TestCase):
    def signal(self,up=True):
        fix=r.fixing_timestamp(date(2025,6,2));bt={}
        for i,t in enumerate(range(fix-3600,fix,300)):
            op=1.1+i*.0001;cl=op+.00009
            bt[t]=dict(ts=t,Open=op,Close=cl,High=cl+.00001,Low=op-.00001)
        bt[fix]=dict(ts=fix,Open=1.10119,Close=1.101,High=1.1012,Low=1.10099)
        if not up:
            for b in bt.values():
                o,c,h,l=[b[k] for k in ('Open','Close','High','Low')]
                b.update(Open=2.2-o,Close=2.2-c,High=2.2-l,Low=2.2-h)
        return fix,bt

    def test_dst(self):
        winter=r.fixing_timestamp(date(2025,1,2));summer=r.fixing_timestamp(date(2025,6,2))
        self.assertEqual(winter%86400,16*3600);self.assertEqual(summer%86400,15*3600)
        self.assertEqual(r.fixing_timestamp(date(2025,3,28))%86400,16*3600)
        self.assertEqual(r.fixing_timestamp(date(2025,3,31))%86400,15*3600)

    def test_closed_confirmation_and_delay(self):
        fix,bt=self.signal();rows,_=r.detect(bt);self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['side'],-1);self.assertEqual(rows[0]['decision_ts'],fix+300)
        self.assertEqual(rows[0]['entry_ts'],fix+600);self.assertGreater(rows[0]['stop'],1.1012)

    def test_long_mirror(self):
        _,bt=self.signal(False);rows,_=r.detect(bt);self.assertEqual(rows[0]['side'],1)

    def test_wick_not_confirmation(self):
        fix,bt=self.signal();bt[fix]['Close']=bt[fix]['Open']+.00001
        self.assertEqual(r.detect(bt)[0],[])

    def test_missing_signal_not_imputed(self):
        fix,bt=self.signal();del bt[fix-600]
        rows,skip=r.detect(bt);self.assertFalse(rows);self.assertEqual(skip['incomplete_signal_window'],1)

    def test_future_cannot_change_signal(self):
        fix,bt=self.signal();before=r.detect(bt)[0]
        bt[fix+300]=dict(ts=fix+300,Open=9,Close=9,High=10,Low=8)
        self.assertEqual(r.detect(bt)[0],before)

    def test_missing_entry_unknown_halts(self):
        _,bt=self.signal();intents,_=r.detect(bt)
        rows,_=r.replay(intents*2,bt,.0004)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['status'],'unknown')

    def test_stop_first_and_gap(self):
        bt={0:dict(Open=1.1,High=1.103,Low=1.098,Close=1.1)}
        o=r.stable.simulate(bt,0,3600,1,.001,.0002)
        self.assertEqual(o['reason'],'stop');self.assertTrue(o['ambiguous'])
        bt={0:dict(Open=1.1,High=1.1001,Low=1.0999,Close=1.1),300:dict(Open=1.098,High=1.1,Low=1.097,Close=1.099)}
        o=r.stable.simulate(bt,0,3600,1,.001,.0002)
        self.assertEqual(o['reason'],'gap_stop');self.assertEqual(o['exit'],1.098)

    def test_unknown_path_not_zero_after_known_exit(self):
        bt={0:dict(Open=1.1,High=1.1001,Low=1.0999,Close=1.1)}
        self.assertEqual(r.stable.simulate(bt,0,3600,1,.001,.0002)['status'],'unknown')
        bt[0]['Low']=1.098
        self.assertEqual(r.stable.simulate(bt,0,3600,1,.001,.0002)['status'],'closed')

    def test_unknown_forbids_cash(self):
        with self.assertRaises(ValueError):r.cash.ledger([dict(status='unknown',entry_ts=0)],1000,1000,100000)

    def test_control_binary_residue_equality(self):
        # Derived risk carries binary residue; quoted low exactly touches stop.
        first=dict(Open=1.1,High=1.1001,Low=1.09959,Close=1.0999)
        bt={i*300:dict(Open=1.0999,High=1.1001,Low=1.0997,Close=1.1) for i in range(12)}
        bt[0]=first
        out=r.stable.simulate(bt,0,3600,1,.00041000000000002146,.0002)
        self.assertEqual(out['reason'],'stop');self.assertEqual(out['net_R'],-1.)

if __name__=='__main__':unittest.main()
