import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('risk_overlay',Path(__file__).resolve().parents[1]/'research_trend_pullback_20261015'/'sizing.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class RiskOverlayTests(unittest.TestCase):
    def setUp(self):
        self.volumes={s:dict(minVolume=1,stepVolume=1,maxVolume=100000) for s in ('EURUSD','GBPUSD')}

    def row(self,symbol='EURUSD',entry_ts=0,exit_ts=100,exit=1.01):
        return dict(symbol=symbol,entry_ts=entry_ts,exit_ts=exit_ts,status='closed',entry=1.,exit=exit,
                    side=1,stop_distance=.01)

    def test_shared_cap_and_deterministic_tie(self):
        rows=[self.row('GBPUSD'),self.row('EURUSD')]
        arm=m.replay(rows,self.volumes,'shared',0)
        self.assertEqual(arm['taken'],1)
        self.assertEqual(arm['trades'][0]['symbol'],'EURUSD')
        self.assertLessEqual(arm['max_reserved_risk_percent'],.5)
        self.assertEqual(m.replay(rows,self.volumes,'baseline',0)['taken'],2)

    def test_open_future_profit_cannot_change_size(self):
        rows=[self.row(exit=2),self.row('GBPUSD',entry_ts=50,exit_ts=150)]
        a=m.replay(rows,self.volumes,'baseline',0)
        rows[0]['exit']=.5
        b=m.replay(rows,self.volumes,'baseline',0)
        self.assertEqual(a['trades'][1]['units'],b['trades'][1]['units'])

    def test_equal_time_exit_releases_budget(self):
        rows=[self.row(),self.row('GBPUSD',entry_ts=100,exit_ts=200)]
        self.assertEqual(m.replay(rows,self.volumes,'shared',0)['taken'],2)

    def test_drawdown_reduces_later_risk(self):
        rows=[self.row(entry_ts=i*100,exit_ts=(i+1)*100,exit=.99) for i in range(7)]
        arm=m.replay(rows,self.volumes,'drawdown',0)
        self.assertGreater(arm['reduced_risk_opportunities'],0)
        self.assertLess(arm['trades'][-1]['units'],arm['trades'][0]['units']/1.5)

    def test_unknown_rejected_and_no_forced_minimum(self):
        row=self.row();row['status']='unknown'
        with self.assertRaises(ValueError):m.replay([row],self.volumes,'shared',0)
        self.volumes['EURUSD']['minVolume']=1000
        self.assertEqual(m.replay([self.row()],self.volumes,'shared',0)['taken'],0)

    def test_decimal_cost_and_balance(self):
        arm=m.replay([self.row()],self.volumes,'baseline',.001)
        self.assertAlmostEqual(arm['end_usd'],1000+454*.009)

    def test_closed_loss_changes_next_size(self):
        rows=[self.row(exit=.99),self.row(entry_ts=100,exit_ts=200)]
        loss=m.replay(rows,self.volumes,'baseline',0)
        rows[0]['exit']=1.01
        win=m.replay(rows,self.volumes,'baseline',0)
        self.assertLess(loss['trades'][1]['units'],win['trades'][1]['units'])

    def test_shared_risk_across_many_overlapping_entries(self):
        rows=[self.row('EURUSD' if i%2 else 'GBPUSD',i,100+i) for i in range(10)]
        for policy in ('shared','drawdown','conservative'):
            arm=m.replay(rows,self.volumes,policy,.001)
            self.assertLessEqual(arm['max_reserved_risk_percent'],.5)
            self.assertAlmostEqual(arm['end_usd'],1000+sum(t['pnl'] for t in arm['trades']))


if __name__=='__main__':unittest.main()
