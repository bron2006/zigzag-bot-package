import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('calendar_research_probe',ROOT/'research_calendar_provider_20261016'/'probe.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

class ProviderDiagnosticTests(unittest.TestCase):
    def setUp(self):self.parser,_=p.load_existing_parser()
    def event(self):return dict(currency='USD',title='Fixture GDP',date='2026-10-16T12:00:00Z',importance=1)
    def row(self,end,events):return dict(begin='2026-10-15',end=end,http_status=200,**p.classify({'events':events},self.parser))

    def test_existing_parser_valid_fixture(self):
        out=p.classify({'events':[self.event()]},self.parser)
        self.assertEqual(out['parsed_count'],1);self.assertEqual(out['status'],'parsed')
        self.assertEqual(self.parser([self.event()])[0]['impact'],'HIGH')
    def test_empty_big_loses_narrow_known_event(self):
        problems=p.check_consistency([self.row('2026-10-18',[]),self.row('2026-10-17',[self.event()])])
        self.assertEqual(len(problems),1);self.assertEqual(problems[0]['missing_count'],1)
    def test_equal_event_consistent(self):
        self.assertEqual(p.check_consistency([self.row('2026-10-18',[self.event()]),self.row('2026-10-17',[self.event()])]),[])
    def test_malformed_payload(self):
        for payload in (None,[],{'events':'bad'},{}):self.assertEqual(p.classify(payload,self.parser)['status'],'malformed_payload')
    def test_invalid_event_not_reported_as_valid(self):
        out=p.classify({'events':[{},None,dict(self.event(),date='bad')]},self.parser)
        self.assertEqual(out['parsed_count'],0);self.assertEqual(out['status'],'partially_parsed')
    def test_transport_timeout(self):
        def timeout(*args,**kwargs):raise TimeoutError('private details must not print')
        out=p.fetch_one('2026-10-15','2026-10-18',self.parser,timeout)
        self.assertEqual(out['status'],'transport_error');self.assertNotIn('error',out)
    def test_hard_parent_deadline(self):
        with patch.object(p.subprocess,'run',side_effect=subprocess.TimeoutExpired(['child'],36)):
            self.assertEqual(p.bounded_child(['child'])['status'],'parent_deadline')
    def test_header_allowlist(self):
        class Response:
            status_code=200
            headers={'Set-Cookie':'secret','Authorization':'secret','Date':'now','X-Vercel-Cache':'HIT'}
            def json(self):return {'events':[]}
        out=p.fetch_one('2026-10-15','2026-10-18',self.parser,lambda *a,**kw:Response())
        self.assertEqual(set(out['headers']),{'Date','X-Vercel-Cache'})

if __name__=='__main__':unittest.main()
