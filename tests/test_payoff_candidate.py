import unittest
import numpy as np
import pandas as pd
from research_walkforward_20261015.payoff_candidate import action,enrich,labels,NAMES,wf


def bars(n=430):
    c=1.1+np.sin(np.arange(n)/17)*.002+np.arange(n)*.000002
    return pd.DataFrame(dict(ts=1704067200+np.arange(n)*900,Open=c-.00002,High=c+.0001,Low=c-.0001,Close=c))


class PayoffCandidateTests(unittest.TestCase):
    def test_abstain_and_select_expected_net_not_probability(self):
        self.assertEqual(action(-.1,-.2),0);self.assertEqual(action(0,0),0)
        self.assertEqual(action(.01,-.02),1);self.assertEqual(action(.01,.02),-1)
        self.assertEqual(action(.1,.1),1)
        with self.assertRaises(ValueError):action(np.nan,1)

    def test_payoff_label_can_lose_despite_up_endpoint(self):
        d=pd.DataFrame([dict(entry_ts=0,ATR=2)])
        bt={i*300:dict(ts=i*300,Open=100.,High=103.,Low=99.,Close=102.) for i in range(3)}
        bt[0]['Low']=96
        y=labels(d,bt)
        self.assertEqual(y[1].iloc[0],-1)

    def test_unknown_path_not_zero_payoff(self):
        y=labels(pd.DataFrame([dict(entry_ts=0,ATR=2)]),{})
        self.assertTrue(np.isnan(y[1].iloc[0]));self.assertTrue(np.isnan(y[-1].iloc[0]))

    def test_extended_features_prefix_and_no_extra_warmup(self):
        b=bars();d=wf.dataset(b,{})
        x=enrich(b,d);prefix=enrich(b.iloc[:300],wf.dataset(b.iloc[:300],{}))
        self.assertEqual(len(x),len(d))
        np.testing.assert_allclose(x.loc[prefix.index,NAMES],prefix[NAMES],rtol=1e-9,atol=1e-9)
        self.assertEqual(len(NAMES),15)


if __name__=='__main__':unittest.main()
