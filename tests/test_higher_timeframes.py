import unittest
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from research_walkforward_20261015.higher_timeframes import aggregate,features,eligible,simulate,action,NAMES
from research_walkforward_20261015.higher_audit import ledger


def bars(n=430,step=3600):
    c=1.1+np.sin(np.arange(n)/17)*.002+np.arange(n)*.000002
    return pd.DataFrame(dict(ts=1704067200+np.arange(n)*step,Open=c-.00002,High=c+.0001,Low=c-.0001,Close=c))


class HigherTimeframeTests(unittest.TestCase):
    def test_true_h1_h4_complete_aggregation(self):
        b=bars(48,300)
        self.assertEqual(len(aggregate(b,3600)[0]),4);self.assertEqual(len(aggregate(b,14400)[0]),1)
        a,partial=aggregate(b.drop(index=1),14400)
        self.assertEqual((len(a),partial),(0,1))

    def test_features_causal_prefix_both_timeframes(self):
        for step in (3600,14400):
            b=bars(step=step);a=features(b,step);p=features(b.iloc[:300],step)
            np.testing.assert_allclose(a.loc[p.index,NAMES],p[NAMES],rtol=1e-9,atol=1e-9)
            self.assertEqual(int(a.iloc[0].entry_ts),int(b.iloc[199].ts)+step+300)
            self.assertEqual(int(a.iloc[0].target_ts-a.iloc[0].entry_ts),step)

    def test_weekend_carry_has_no_synthetic_bar_and_ema_can_warm_up(self):
        b=bars();b.loc[120:,'ts']+=2*86400
        a=features(b,3600)
        self.assertEqual(len(a),231);self.assertEqual(a.index[0],199)

    def test_no_swap_window_clock_rule(self):
        start=int(datetime(2025,1,6,tzinfo=timezone.utc).timestamp())
        h4=pd.DataFrame(dict(decision_ts=[start+h*3600 for h in (4,8,12,16)]))
        h4['target_ts']=h4.decision_ts+300+14400
        self.assertEqual(eligible(h4).tolist(),[True,True,True,False])
        h4.decision_ts+=5*86400;h4.target_ts+=5*86400
        self.assertFalse(eligible(h4).any())

    def test_entry_bar_stop_first_and_adverse_gap(self):
        bt={i*300:dict(ts=i*300,Open=100.,High=101.,Low=99.,Close=100.) for i in range(12)}
        bt[0].update(High=105.,Low=97.)
        r=simulate(bt,0,3600,1,2,.5)
        self.assertEqual(r['net_R'],-1);self.assertTrue(r['ambiguous'])
        bt[0].update(High=101.,Low=99.);bt[300].update(Open=95.,High=96.,Low=94.,Close=95.)
        self.assertEqual(simulate(bt,0,3600,1,2,.5)['net_R'],-2.2)

    def test_missing_after_known_stop_does_not_erase_exit(self):
        bt={0:dict(ts=0,Open=100.,High=101.,Low=97.,Close=99.)}
        self.assertEqual(simulate(bt,0,3600,1,2,.5)['status'],'closed')
        self.assertEqual(simulate(bt,0,3600,-1,2,.5)['status'],'unknown')

    def test_exact_deadline_and_tp_gap_no_improvement(self):
        for step in (3600,14400):
            bt={i*300:dict(ts=i*300,Open=100.,High=101.,Low=99.,Close=100.5) for i in range(step//300)}
            r=simulate(bt,0,step,1,2,.5)
            self.assertEqual((r['reason'],r['exit_ts'],r['net_R']),('deadline',step,0.))
            bt[300].update(Open=106.,High=107.,Low=105.,Close=106.)
            self.assertEqual(simulate(bt,0,step,1,2,.5)['net_R'],1.4)

    def test_expected_net_zero_abstains(self):
        self.assertEqual(action(-.2,-.1),0);self.assertEqual(action(0,0),0)
        self.assertEqual(action(.01,-.01),1);self.assertEqual(action(.01,.02),-1)

    def test_rounded_cash_ledger_no_year_reset_or_flat_five_dollar_R(self):
        rows=[dict(status='closed',entry_ts=i*3600,exit_ts=i*3600+300,entry=1.1,exit=1.101,
            stop_distance=.002,side=side,scenario='base',month=month) for i,(side,month) in enumerate([(1,'2025-01'),(-1,'2026-01')])]
        r=ledger(rows,1000,1000,100000000)
        self.assertEqual([t['units'] for t in r['trades']],[2000,2000])
        self.assertAlmostEqual(r['end_usd'],999.2)
        self.assertAlmostEqual(r['year_end_balances']['2025'],1001.6)

    def test_ledger_cannot_force_broker_minimum_or_unknown_cash(self):
        row=dict(status='closed',entry_ts=0,exit_ts=300,entry=1.1,exit=1.101,stop_distance=1,
                 side=1,scenario='base',month='2025-01')
        r=ledger([row],1000,1000,100000000)
        self.assertEqual((r['end_usd'],r['taken'],r['minimum_size_skips']),(1000.,0,1))
        row['status']='unknown'
        with self.assertRaises(ValueError):ledger([row],1000,1000,100000000)

    def test_ledger_rejects_simultaneous_unfunded_positions(self):
        row=dict(status='closed',entry_ts=0,exit_ts=300,entry=1.1,exit=1.101,stop_distance=.002,
                 side=1,scenario='base',month='2025-01')
        with self.assertRaises(ValueError):ledger([row,dict(row)],1000,1000,100000000)


if __name__=='__main__':unittest.main()
