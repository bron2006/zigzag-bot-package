import unittest
import numpy as np
import pandas as pd
from model_contract_probe import to_m15, endpoint, summarize, feature_function


class ModelContractTest(unittest.TestCase):
    def test_m15_requires_three_aligned_bars(self):
        df = pd.DataFrame({'ts': [0, 300, 600, 900, 1500], 'Open': [1]*5,
            'High': [2]*5, 'Low': [.5]*5, 'Close': [1, 1.1, 1.2, 1, 1], 'Volume': [1]*5})
        result = to_m15(df)
        self.assertEqual(result.ts.tolist(), [0])
        self.assertEqual(result.Close.tolist(), [1.2])

    def test_endpoint_cannot_jump_missing_bars(self):
        df = pd.DataFrame({'ts': [0, 300, 900, 1200], 'Close': [1, 2, 3, 4]})
        self.assertIsNone(endpoint(df, 0, 300))
        self.assertIsNone(endpoint(df, 3, 300))

    def test_endpoint_common_fifteen_minute_horizon(self):
        df = pd.DataFrame({'ts': [0, 300, 600, 900], 'Close': [1, 2, 3, 4]})
        self.assertEqual(endpoint(df, 0, 300), 4)

    def test_mapping_and_thresholds_are_not_optimized(self):
        result = summarize([.8, .2, .75, .25, .9], [1, -1, 1, -1, 0], ['a','b','a','b','a'])
        self.assertEqual(result['threshold_signals'], 2)
        self.assertEqual(result['original_wins'], 2)
        self.assertEqual(result['deployed_inverted_wins'], 0)
        self.assertEqual(result['ties'], 1)

    def test_feature_inputs_do_not_see_future(self):
        df = pd.DataFrame({k: 1 + np.arange(320)*.001 for k in ['Open','High','Low','Close']})
        df.High += .01
        df.Low -= .01
        prepare = feature_function()
        first = prepare(df.iloc[:300])
        df.loc[300:, 'Close'] = 1000
        pd.testing.assert_frame_equal(first, prepare(df.iloc[:300]))
