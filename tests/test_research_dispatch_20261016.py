import unittest
from unittest.mock import Mock,patch
import subprocess
from research_dispatch_20261016.batch import validate,job


class ResearchDispatchTests(unittest.TestCase):
    def test_completed_failed_candidate_is_not_process_failure(self):
        self.assertFalse(validate(dict(protocol_sha256='a',gate=False,arms=dict(EURUSD={},GBPUSD={})),'a'))

    def test_missing_gate_and_wrong_protocol_fail(self):
        for data in (dict(protocol_sha256='a',arms=dict(EURUSD={},GBPUSD={})),
                     dict(protocol_sha256='b',gate=False,arms=dict(EURUSD={},GBPUSD={}))):
            with self.assertRaises(ValueError):validate(data,'a')

    def test_cannot_hide_losing_pair_or_use_truthy_string(self):
        for data in (dict(protocol_sha256='a',gate=True,arms=dict(EURUSD={})),
                     dict(protocol_sha256='a',gate='false',arms=dict(EURUSD={},GBPUSD={}))):
            with self.assertRaises(ValueError):validate(data,'a')

    def test_calendar_report_schema_and_ambiguity(self):
        data=dict(protocol_sha256='a',gate=False,pairs=dict(EURUSD={},GBPUSD={}))
        self.assertFalse(validate(data,'a'))
        data['arms']=data['pairs']
        with self.assertRaises(ValueError):validate(data,'a')

    def test_timeout_stops_child_and_is_not_candidate_loss(self):
        child=Mock()
        child.communicate.side_effect=[subprocess.TimeoutExpired('test',180),('','')]
        with patch('research_dispatch_20261016.batch.subprocess.Popen',return_value=child):
            result=job('research_fix_20261016',run=True)
        child.kill.assert_called_once()
        self.assertFalse(result['completed'])
        self.assertIsNone(result['candidate_passed'])
        self.assertEqual(result['error'],'hard_timeout_child_stopped')

    def test_process_failure_cannot_reuse_old_report_as_success(self):
        child=Mock(returncode=1);child.communicate.return_value=('','failure')
        with patch('research_dispatch_20261016.batch.subprocess.Popen',return_value=child):
            result=job('research_fix_20261016',run=True)
        self.assertFalse(result['completed'])
        self.assertEqual(result['error'],'research_process_failed_not_candidate_loss')


if __name__=='__main__':unittest.main()
