import unittest
import numpy as np
import pandas as pd
from research_walkforward_20261015.run import m15,features,train_mask,simulate,dataset,session,NORMALIZED_NAMES


def bars(n=430):
    c=1.1+np.sin(np.arange(n)/17)*.002+np.arange(n)*.000002
    return pd.DataFrame(dict(ts=1704067200+np.arange(n)*900,Open=c-.00002,High=c+.0001,Low=c-.0001,Close=c))


class WalkForwardTests(unittest.TestCase):
    def test_features_prefix_and_future_poison(self):
        b=bars();x=features(b);p=features(b.iloc[:300])
        np.testing.assert_allclose(x.iloc[250:300],p.iloc[250:300],rtol=1e-10,atol=1e-10)
        changed=b.copy();changed.loc[300:,'Close']+=100
        np.testing.assert_allclose(x.iloc[250:300],features(changed).iloc[250:300])

    def test_gap_resets_warmup(self):
        b=bars();b.loc[220:,'ts']+=900
        x=features(b)
        self.assertTrue(x.iloc[220:419].isna().all().all())
        self.assertTrue(np.isfinite(x.iloc[419]).all())

    def test_training_target_purge(self):
        d=pd.DataFrame(dict(known_path=[True,True,False],move=[1,1,1],target_ts=[99,100,90]))
        self.assertEqual(train_mask(d,100).tolist(),[True,False,False])

    def test_complete_m15_only(self):
        b=bars(6);b.ts=1704067200+np.arange(6)*300
        self.assertEqual(len(m15(b)),2)
        self.assertEqual(len(m15(b.drop(index=1))),1)

    def test_stop_first_entry_bar_and_adverse_gap(self):
        p=[dict(ts=i*300,Open=100.,High=101.,Low=99.,Close=100.) for i in range(3)]
        p[0].update(High=105.,Low=97.)
        r=simulate(p,1,2.,.5)
        self.assertTrue(r['ambiguous']);self.assertEqual(r['net_R'],-1)
        p[0].update(High=101.,Low=99.);p[1].update(Open=95.,High=96.,Low=94.,Close=95.)
        self.assertEqual(simulate(p,1,2.,.5)['net_R'],-2.2)

    def test_missing_path_unknown_not_refund(self):
        self.assertEqual(simulate([None]*3,1,2.,.5),dict(status='unknown'))

    def test_target_payout_is_net_not_raw_two_R(self):
        p=[dict(ts=i*300,Open=100.,High=105.,Low=99.,Close=103.) for i in range(3)]
        self.assertEqual(simulate(p,1,2.,.5)['net_R'],1.4)

    def test_session_overlap_explicit_and_dst(self):
        self.assertEqual(session(1783342800),'overlap')  # 2026Jul6 13UTC

    def test_normalized_feature_scale_invariance(self):
        b=bars();a=dataset(b,{})
        c=b.copy();c[['Open','High','Low','Close']]*=100
        z=dataset(c,{})
        np.testing.assert_allclose(a[NORMALIZED_NAMES],z[NORMALIZED_NAMES],rtol=1e-8,atol=1e-8)


if __name__=='__main__':unittest.main()
