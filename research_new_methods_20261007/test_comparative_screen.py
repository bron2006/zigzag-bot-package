import copy
import unittest
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from comparative_screen import indicators,directions,collect,block_ci,gate,SYMBOLS


def fixture(year=2025,scale=1.):
    start=int(datetime(year,1,6,3,tzinfo=timezone.utc).timestamp())
    close=(1.1+np.arange(180)*.0001)*scale
    return pd.DataFrame({'ts':start+np.arange(180)*300,'Open':close-.00002*scale,
        'Close':close,'High':close+.00003*scale,'Low':close-.00005*scale})


class ComparativeTest(unittest.TestCase):
    def test_future_does_not_change_indicators_or_signals(self):
        bars=fixture();changed=bars.copy();changed.loc[120:,'Close']+=50
        pd.testing.assert_frame_equal(indicators(bars).iloc[:120],indicators(changed).iloc[:120])
        for rule,signal in directions(bars,indicators(bars)).items():
            np.testing.assert_array_equal(signal[:120],directions(changed,indicators(changed))[rule][:120])

    def test_gap_resets_warmup(self):
        bars=fixture();bars.loc[90:,'ts']+=300
        features=indicators(bars)
        self.assertTrue(features.iloc[90:149].isna().all().all())
        self.assertTrue(features.iloc[149].notna().all())

    def test_price_scale_invariance(self):
        a=fixture();b=fixture(scale=150)
        for rule,signal in directions(a,indicators(a)).items():
            np.testing.assert_array_equal(signal,directions(b,indicators(b))[rule])

    def test_breakout_excludes_current_high(self):
        bars=fixture();features=indicators(bars)
        self.assertAlmostEqual(features.upper.iloc[70],bars.High.iloc[50:70].max())
        self.assertEqual(directions(bars,features)['breakout'][70],1)

    def test_reversion_opposes_deviation_without_volume(self):
        bars=fixture();self.assertNotIn('Volume',bars)
        self.assertEqual(directions(bars,indicators(bars))['reversion'][70],-1)

    def test_one_first_signal_delay_and_expiry(self):
        rows,info=collect(fixture(),'EURUSD','early')
        self.assertEqual(len(info['full_session_dates']),1)
        self.assertEqual(len(rows),3)
        for row in rows:
            self.assertEqual(row['signal_ts']%86400,8*3600+300)
            self.assertEqual(row['entry_ts']-row['signal_ts'],300)
            self.assertEqual(row['exit_ts']-row['entry_ts'],300)
            self.assertLessEqual(row['exit_ts']%86400,16*3600)

    def test_incomplete_session_is_excluded(self):
        bars=fixture().drop(index=70).reset_index(drop=True)
        rows,info=collect(bars,'EURUSD','early')
        self.assertEqual(rows,[])
        self.assertEqual(info['exclusions']['incomplete_sessions'],1)

    def test_early_phase_does_not_label_final_year(self):
        self.assertEqual(collect(fixture(year=2026),'EURUSD','early')[0],[])
        self.assertEqual(collect(fixture(year=2025),'EURUSD','final')[0],[])

    def test_costs_and_baselines_use_same_observation(self):
        for symbol,scale,pip in [('EURUSD',1,.0001),('USDJPY',150,.01)]:
            rows,_=collect(fixture(scale=scale),symbol,'early')
            for row in rows:
                move=(row['exit']-row['entry'])/row['atr']
                cost=max(.44,4*pip/row['atr'])
                self.assertAlmostEqual(row['stress_cost_atr'],cost)
                self.assertAlmostEqual(row['always_buy_stress_atr'],move-cost)
                self.assertAlmostEqual(row['always_sell_stress_atr'],-move-cost)
                self.assertAlmostEqual(row['opposite_stress_atr'],-row['gross_atr']-cost)

    def test_bootstrap_constant_and_empty(self):
        days=[str(i) for i in range(20)]
        rows=[{'day':day,'value':2.,'base':1.} for day in days]
        self.assertEqual(block_ci(rows,'value',days),[2.,2.])
        self.assertEqual(block_ci(rows,'value',days,'base'),[1.,1.])
        self.assertIsNone(block_ci([],'value',days))

    def test_gate_requires_both_baselines_and_sample_and_pairs(self):
        key='stress_net_atr';early={key:{'mean':.1}}
        final={'decided':300,'days':100,key:{'adjusted_block_ci':[.01,.3]},
            'paired_advantage':{key:{'always_buy_stress_atr':[.01,.3],'always_sell_stress_atr':[.01,.3]}},
            'per_pair':{s:{'stress_mean_atr':.1} for s in SYMBOLS}}
        self.assertTrue(gate(early,final,key))
        bad=copy.deepcopy(final);bad['paired_advantage'][key]={}
        self.assertFalse(gate(early,bad,key))
        bad=copy.deepcopy(final);bad['decided']=299
        self.assertFalse(gate(early,bad,key))
        self.assertFalse(gate({key:{'mean':-.1}},final,key))
        bad=copy.deepcopy(final);bad[key]['adjusted_block_ci'][0]=-.01
        self.assertFalse(gate(early,bad,key))
        bad=copy.deepcopy(final)
        for s in SYMBOLS[:2]:bad['per_pair'][s]['stress_mean_atr']=-.1
        self.assertFalse(gate(early,bad,key))


if __name__=='__main__':unittest.main()
