from datetime import datetime,timezone
import unittest
from broker_closure import closure_predicate
from paper_cfd import simulate_stop_trade
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from forward_structure_research import _connect,store_packet,snapshot
from ny_h4_reclaim import RULE


def stamp(text):return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp())
SCHEDULE=dict(scheduleTimeZone='America/New_York',schedule=[dict(startSecond=0,endSecond=233940),dict(startSecond=234300,endSecond=604800)])


class ClosureTest(unittest.TestCase):
    def test_missing_fully_closed_M5_summer_and_winter(self):
        proof=closure_predicate(SCHEDULE)
        for start in ('2026-10-13T21:00:00','2026-01-06T22:00:00'):
            t=stamp(start);self.assertTrue(proof(t,t+300))

    def test_partial_open_missing_bar_or_wrong_timezone_not_ignored(self):
        proof=closure_predicate(SCHEDULE);t=stamp('2026-10-13T21:00:00')
        self.assertFalse(proof(t-300,t));self.assertFalse(proof(t,t+600))
        for data in (None,{},dict(SCHEDULE,schedule=[]),dict(SCHEDULE,scheduleTimeZone='unknown'),dict(SCHEDULE,schedule=[dict(startSecond=0.,endSecond=1)])):
            self.assertIsNone(closure_predicate(data))

    def test_default_still_unknown_and_verified_closure_continues(self):
        t=stamp('2026-10-13T20:55:00')
        bars=[dict(ts=t,Open=100,High=101,Low=99,Close=100),dict(ts=t+600,Open=100,High=105,Low=99,Close=104)]
        self.assertEqual(simulate_stop_trade(bars,0,1,2,2)['status'],'unknown')
        result=simulate_stop_trade(bars,0,1,2,2,gap_is_closed=closure_predicate(SCHEDULE))
        self.assertEqual(result['reason'],'target');self.assertEqual(result['scheduled_closure_gaps'],1)

    def test_bad_reopening_gap_is_not_hidden_by_schedule(self):
        t=stamp('2026-10-13T20:55:00')
        bars=[dict(ts=t,Open=100,High=101,Low=99,Close=100),dict(ts=t+600,Open=95,High=96,Low=94,Close=95)]
        result=simulate_stop_trade(bars,0,1,2,2,gap_is_closed=closure_predicate(SCHEDULE))
        self.assertEqual((result['reason'],result['exit']),('stop_gap',95))

    def test_unknown_repaired_with_history_preserved_and_closed_never_rewritten(self):
        t=stamp('2026-10-13T20:55:00');intent=dict(rule=RULE,ts=t,day=t//86400,side=1,stop=98)
        bars=[dict(ts=t,Open=100.,High=101.,Low=99.,Close=100.),dict(ts=t+600,Open=100.,High=105.,Low=99.,Close=104.)]
        now=t+1200+31
        with tempfile.TemporaryDirectory() as folder:
            file=str(Path(folder)/'research.sqlite3');db=_connect(file,t-1000,False);db.close()
            with patch('forward_structure_research.detect_ny',return_value=dict(intents=[intent],states=[])):
                store_packet(file,'ETHUSD',bars,now,require_mount=False)
                self.assertEqual({r['status'] for r in snapshot(file,now)['recent']},{'unknown'})
                store_packet(file,'ETHUSD',bars,now,require_mount=False,schedule=SCHEDULE)
                view=snapshot(file,now)
                self.assertEqual({r['status'] for r in view['recent']},{'closed'})
                self.assertEqual(view['revision_count'],2)
                db=_connect(file,now,False)
                old=[json.loads(r[0]) for r in db.execute('SELECT prior FROM observation_revisions')]
                self.assertTrue(all(r['status']=='unknown' and r['reason']=='path_gap' for r in old));db.close()
                store_packet(file,'ETHUSD',bars,now,require_mount=False,schedule=dict(SCHEDULE,schedule=[dict(startSecond=0,endSecond=604800)]))
                self.assertEqual(snapshot(file,now)['recent'],view['recent'])
                self.assertEqual(snapshot(file,now)['revision_count'],2)
