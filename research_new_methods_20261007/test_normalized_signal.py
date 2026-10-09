import unittest
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from normalized_signal_candidate import features, split_masks, payoff, passes_gate, TRAIN_END, VALID_END


def fixture():
    close = 1 + np.arange(500) * .0001 + np.sin(np.arange(500)) * .0002
    return pd.DataFrame({'ts': np.arange(500)*300, 'Close': close, 'Open': close-.0001,
                         'High': close+.001, 'Low': close-.001})


class NormalizedSignalTest(unittest.TestCase):
    def test_future_mutation_does_not_change_features(self):
        bars = fixture()
        expected = features(bars).iloc[:300]
        bars.loc[300:, ['Close','Open','High','Low']] *= 100
        pd.testing.assert_frame_equal(expected, features(bars).iloc[:300])

    def test_price_scale_invariant(self):
        bars = fixture()
        original = features(bars)
        bars[['Close','Open','High','Low']] *= 100
        np.testing.assert_allclose(original, features(bars), atol=1e-9, rtol=1e-8, equal_nan=True)

    def test_gap_resets_warmup(self):
        bars = fixture()
        bars.loc[250:, 'ts'] += 300
        result = features(bars)
        self.assertTrue(result.iloc[250:449].isna().all().all())
        self.assertTrue(result.iloc[449].notna().all())

    def test_targets_cannot_cross_partition_boundary(self):
        frame = pd.DataFrame({'decision_ts': [TRAIN_END-300,TRAIN_END,VALID_END-300,VALID_END],
                              'target_ts': [TRAIN_END,TRAIN_END+300,VALID_END,VALID_END+300]})
        masks = split_masks(frame)
        self.assertEqual(masks['train'].tolist(), [False]*4)
        self.assertEqual(masks['validation'].tolist(), [False,True,False,False])
        self.assertEqual(masks['test'].tolist(), [False,False,False,True])

    def test_payout_not_price_return_and_no_martingale(self):
        np.testing.assert_array_equal(payoff([1,-1,1,0], [1,1,0,1], .8), [.8,-1,0,0])

    def test_empty_signal_set_fails_closed(self):
        empty = {'payout_scenarios': {}, 'decided': 0, 'days': 0}
        self.assertFalse(passes_gate(empty, empty))

    def test_invalid_or_unsorted_bars_rejected(self):
        bars = fixture()
        with self.assertRaises(ValueError):
            features(bars.iloc[::-1])
        bars.loc[250, 'Close'] = bars.High.iloc[250] + 1
        with self.assertRaises(ValueError):
            features(bars)

    def test_scaler_fitted_only_to_training(self):
        train = np.array([[0., 1.], [1., 2.], [2., 3.], [3., 4.]])
        model = make_pipeline(StandardScaler(), LogisticRegression())
        model.fit(train, [0, 0, 1, 1])
        before = model[0].mean_.copy()
        model.predict_proba([[1e6, 1e6]])
        np.testing.assert_array_equal(before, train.mean(axis=0))
        np.testing.assert_array_equal(before, model[0].mean_)

    def test_gate_requires_advantage_over_each_baseline(self):
        valid = {'payout_scenarios': {'0.8': {'mean_units': .1}}}
        test = {'payout_scenarios': {'0.8': {'day_ci95': [.01,.2]}},
                'decided': 200, 'days': 10,
                'baseline_advantage_ci95_at80': {'always_up': [0., .1],
                    'always_down': [.01,.1], 'candle_momentum': [.01,.1]}}
        self.assertFalse(passes_gate(valid, test))
        test['baseline_advantage_ci95_at80']['always_up'] = [.01,.1]
        self.assertTrue(passes_gate(valid, test))
        test['baseline_advantage_ci95_at80'] = {}
        self.assertFalse(passes_gate(valid, test))


if __name__ == '__main__':
    unittest.main()
