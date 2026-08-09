import unittest

import pandas as pd

import analysis


class IndicatorMathTest(unittest.TestCase):
    def test_prepare_features_returns_model_feature_columns(self):
        df = pd.DataFrame(
            {
                "Open": [1.0 + i * 0.001 for i in range(300)],
                "High": [1.1 + i * 0.001 for i in range(300)],
                "Low": [0.9 + i * 0.001 for i in range(300)],
                "Close": [1.05 + i * 0.001 for i in range(300)],
                "Volume": [100 + i for i in range(300)],
            }
        )

        features = analysis._prepare_features(df)

        self.assertIsNotNone(features)
        self.assertEqual(list(features.columns), analysis.MODEL_FEATURE_NAMES)
        self.assertFalse(features.isna().any().any())


if __name__ == "__main__":
    unittest.main()
