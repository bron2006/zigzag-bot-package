import unittest
import numpy as np
import pandas as pd
from research_walkforward_20261015.feasible_candidate import attainable,quantity,dollar_label
from research_walkforward_20261015.current_cost_probe import estimate

VOLUME=dict(minVolume=1000.,stepVolume=1000.,maxVolume=100000000.)


class FeasibleCandidateTests(unittest.TestCase):
    def test_affordability_uses_decision_close_and_known_stop(self):
        data=pd.DataFrame(dict(ATR=[.002,.004],entry_ts=[1,2]),index=[10,20])
        close=pd.Series([1.1,1.1],index=[10,20])
        out=attainable(data,close,VOLUME)
        self.assertEqual(out.index.tolist(),[10]);self.assertEqual(out.decision_units.iloc[0],1000)
        self.assertAlmostEqual(out.minimum_risk_fraction.iloc[0],.0034)

    def test_minimum_not_forced_and_max_notional_applies(self):
        self.assertEqual(quantity(1.1,.006,.0004,VOLUME),0)
        self.assertEqual(quantity(10.,.0001,.0004,VOLUME),0)
        self.assertLessEqual(quantity(1.1,.0001,.0004,VOLUME)*1.1,5000)

    def test_net_dollar_label_not_flat_five_dollar_R(self):
        r=dict(status='closed',entry=1.1,stop_distance=.003,net_R=1.)
        self.assertAlmostEqual(dollar_label(r,.0004,VOLUME),3.4)

    def test_unknown_label_not_zero_and_unattainable_known_is_flat(self):
        self.assertTrue(np.isnan(dollar_label(dict(status='unknown'),.0004,VOLUME)))
        r=dict(status='closed',entry=1.1,stop_distance=.006,net_R=1.)
        self.assertEqual(dollar_label(r,.0004,VOLUME),0)

    def test_commission_precision_and_roundtrip_spread(self):
        spec=dict(commissionType='USD_PER_MILLION_USD',minCommissionAsset='USD',
                  preciseTradingCommissionRate='3000000000',preciseMinCommission='0',pipPosition=4)
        q=dict(bid=1.1,ask=1.1001,bid_ts=100,ask_ts=100)
        r=estimate(spec,q,101)
        self.assertAlmostEqual(r['spread_pips'],1)
        self.assertAlmostEqual(r['commission_roundtrip_pips'],.66003)
        self.assertAlmostEqual(r['roundtrip_proxy_pips'],1.66003)
        self.assertFalse(r['cost_complete'])

    def test_stale_or_asynchronous_quote_not_fee_evidence(self):
        spec=dict(commissionType='USD_PER_MILLION_USD',minCommissionAsset='USD')
        with self.assertRaises(ValueError):estimate(spec,dict(bid=1.1,ask=1.1001,bid_ts=100,ask_ts=103),104)
        with self.assertRaises(ValueError):estimate(spec,dict(bid=1.1,ask=1.1001,bid_ts=100,ask_ts=100),106)

    def test_non_fx_commission_not_silently_mispriced(self):
        with self.assertRaises(ValueError):estimate(dict(commissionType='PERCENTAGE_OF_VALUE'),{},100)


if __name__=='__main__':unittest.main()
