import unittest
import numpy as np
from tests.test_trend_pullback_candidate import setup,START
from tests.test_higher_timeframes import bars
from research_trend_pullback_20261015.strategy import detect
from research_walkforward_20261015.higher_timeframes import aggregate,features,NAMES


class ChartScaleTests(unittest.TestCase):
    def test_complete_aggregation_all_new_scales(self):
        raw=bars(288,300)
        for step in (1800,7200,28800,86400):
            out,partial=aggregate(raw,step)
            self.assertEqual(len(out),86400//step)
            self.assertEqual(partial,0)
            self.assertEqual(out.iloc[0].Open,raw.iloc[0].Open)
            self.assertEqual(out.iloc[-1].Close,raw.iloc[-1].Close)
            out,partial=aggregate(raw.drop(index=1),step)
            self.assertEqual(partial,1)
            self.assertEqual(len(out),86400//step-1)

    def test_new_scale_features_are_prefix_causal(self):
        for step in (1800,7200,28800,86400):
            raw=bars(step=step)
            before=features(raw.iloc[:300],step)
            after=features(raw,step)
            np.testing.assert_allclose(before[NAMES],after.loc[before.index,NAMES],rtol=1e-9,atol=1e-9)

    def test_new_chart_entry_delay_and_closed_context(self):
        for signal,context in ((1800,7200),(7200,28800),(28800,86400)):
            candles,contexts=setup()
            decision=START+8*3600
            candles[0]['ts']=decision-2*signal
            candles[1]['ts']=decision-signal
            contexts[0]['ts']=decision-context
            r=detect(candles,contexts,signal_step=signal,context_step=context)[0]
            self.assertEqual(r['entry_ts'],decision+300)
            self.assertEqual(r['context_closed_ts'],decision)
            contexts[0]['ts']+=context
            self.assertEqual(detect(candles,contexts,signal_step=signal,context_step=context),[])

    def test_m30_cutoff_no_extra_1530_trade(self):
        for hour,minute,expected in ((14,30,1),(15,0,1),(15,30,0)):
            candles,contexts=setup();decision=START+hour*3600+minute*60
            candles[0]['ts']=decision-3600;candles[1]['ts']=decision-1800
            contexts[0]['ts']=START+12*3600
            self.assertEqual(len(detect(candles,contexts,signal_step=1800,context_step=7200)),expected)

    def test_invalid_chart_rejected(self):
        for signal,context in ((300,7200),(7200,7200),(1800,12345)):
            with self.assertRaises(ValueError):detect([],[],signal_step=signal,context_step=context)


if __name__=='__main__':unittest.main()
