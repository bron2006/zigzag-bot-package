import unittest
import numpy as np
from sklearn.metrics import roc_auc_score
from research_walkforward_20261015.auc_audit import weighted_auc
from research_walkforward_20261015.all_forecasts import diagnostics,paired_values,interval


def row(move,p,prior=.5,ts=1767225600):
    return dict(move=move,p_up=p,prior_up=prior,decision_ts=ts)


class AllForecastTests(unittest.TestCase):
    def test_rejected_low_confidence_forecasts_included(self):
        r=diagnostics([row(1,.51),row(-1,.49)])
        self.assertEqual(r['forecasts'],2);self.assertEqual(r['accuracy'],1)

    def test_flat_and_unknown_not_negative_labels(self):
        r=diagnostics([row(1,.9),row(-1,.1),row(0,.1),row(None,.9)])
        self.assertEqual((r['forecasts'],r['nonflat'],r['flat'],r['unknown']),(4,2,1,1))
        self.assertAlmostEqual(r['brier'],.01);self.assertEqual(r['auc'],1)

    def test_direction_accuracy_not_class_one_frequency(self):
        r=diagnostics([row(-1,.1),row(-1,.2),row(1,.9)])
        self.assertEqual(r['accuracy'],1);self.assertAlmostEqual(r['always_up_accuracy'],1/3)

    def test_prior_baseline_not_test_prevalence(self):
        r=diagnostics([row(1,.5,.8),row(1,.5,.8)])
        self.assertAlmostEqual(r['prior_brier'],.04)

    def test_positive_improvement_means_better(self):
        _,values=paired_values([row(1,.9),row(-1,.1)])
        self.assertAlmostEqual(values['brier'][0],.24)
        self.assertEqual(values['accuracy_up'].tolist(),[0.,1.])

    def test_bins_include_zero_one_once(self):
        r=diagnostics([row(1,0),row(-1,.1),row(1,1)])
        counts=[b['n'] for b in r['calibration_bins']]
        self.assertEqual(sum(counts),3);self.assertEqual((counts[0],counts[1],counts[9]),(1,1,1))

    def test_bootstrap_deterministic_and_empty_days_weighted(self):
        rows=[row(1,.9),row(-1,.1,ts=1767225600+20*86400)]
        a=interval(rows,2026);self.assertEqual(a,interval(rows,2026))
        self.assertAlmostEqual(a['brier'][0],.24);self.assertAlmostEqual(a['brier'][1],.24)

    def test_no_direction_tuning_for_inverted_predictor(self):
        r=diagnostics([row(1,.1),row(-1,.9)])
        self.assertEqual(r['auc'],0);self.assertEqual(r['accuracy'],0)

    def test_weighted_auc_matches_explicit_duplicate_records_with_ties(self):
        y=np.array([1,0,1,0]);p=np.array([.5,.5,.8,.2]);w=np.array([2,3,1,2])
        self.assertAlmostEqual(weighted_auc(y,p,w),roc_auc_score(np.repeat(y,w),np.repeat(p,w)))
        self.assertIsNone(weighted_auc(np.ones(4),p,w))


if __name__=='__main__':unittest.main()
