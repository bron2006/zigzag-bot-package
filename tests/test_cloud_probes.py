import ast
import contextlib
import io
import json
from pathlib import Path
import runpy
import unittest
from unittest.mock import Mock, patch
import requests


class CloudProbeTest(unittest.TestCase):
    def test_statistics_probe_uses_resident_http_not_second_application(self):
        source=Path('scripts/verify_current_test_release.py').read_text(encoding='utf-8')
        imported={name.name for node in ast.walk(ast.parse(source)) if isinstance(node,ast.Import) for name in node.names}
        self.assertFalse(imported & {'api','db','analysis','app'})
        current=dict(ok=True,scope='current_test',total=1,test_started='start',
                     measurement_audit=dict(total=1,counts={},scenario={},valuation='asof60',
                                            cohort='asof60_v1',asof_comparison=dict(affects_balance=True)),
                     original_measurement_audit=dict(total=1,valuation='strict',counts={}))
        responses=[Mock(status_code=200,json=Mock(return_value=current)),
                   Mock(status_code=200,json=Mock(return_value=dict(ok=True,total=0)))]
        with patch('requests.get',side_effect=responses) as get, contextlib.redirect_stdout(io.StringIO()):
            runpy.run_path('scripts/verify_current_test_release.py')
        self.assertEqual([c.kwargs['params']['scope'] for c in get.call_args_list],['current_test','history'])
        self.assertTrue(all(c.kwargs['timeout']==(5,20) for c in get.call_args_list))

    def test_timeout_does_not_abort_whole_audit_batch(self):
        response=Mock(status_code=200,json=Mock(return_value=dict(
            pair='TEST',outcome='unknown',saved=None,history=dict(endpoint=None,counts=[0,0]))))
        output=io.StringIO()
        with patch('sys.argv',['audit','--asof','1','2']), \
             patch('requests.post',side_effect=[requests.Timeout(),response,response]) as post, \
             patch('time.sleep'), contextlib.redirect_stdout(output):
            runpy.run_path('scripts/audit_historical_endpoints.py')
        self.assertEqual([json.loads(line)['id'] for line in output.getvalue().splitlines()],[1,2])
        self.assertEqual(post.call_count,3)
