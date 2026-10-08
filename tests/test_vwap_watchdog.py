"""Actual watchdog source tested without importing DB/config or networking."""
import ast
from datetime import datetime, timezone
import logging
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class WatchdogTest(unittest.TestCase):
    def setUp(self):
        source=Path(__file__).resolve().parents[1]/'vwap_executor.py'
        tree=ast.parse(source.read_text(encoding='utf-8'))
        names={'_in_weekend_closure','_is_poll_cycle_stale','_dead_mans_switch_tick'}
        constants={'_WEEKEND_CLOSURE_START_WEEKDAY','_WEEKEND_CLOSURE_START_HOUR_UTC',
                   '_WEEKEND_CLOSURE_END_WEEKDAY','_WEEKEND_CLOSURE_END_HOUR_UTC'}
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names
               or isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in constants for t in n.targets)]
        self.ns=dict(datetime=datetime,timezone=timezone,logger=Mock(),
                     _last_poll_completed_ts=1.0,_dead_mans_switch_alerted=False,
                     VWAP_EXECUTOR_STALE_POLL_ALERT_SECONDS=90)
        exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),'exec'),self.ns)
        self.notify=Mock()
        self.modules=patch.dict('sys.modules',{'notifier':SimpleNamespace(notify_admin=self.notify)})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def tick(self,day,hour,minute=0,second=0):
        ts=datetime(2026,10,day,hour,minute,second,tzinfo=timezone.utc).timestamp()
        return self.ns['_dead_mans_switch_tick'](ts),ts

    def test_saturday_stale_cycle_is_silent(self):
        result,ts=self.tick(3,12)
        self.assertFalse(result)
        self.notify.assert_not_called()
        self.assertEqual(self.ns['_last_poll_completed_ts'],ts)

    def test_friday_closure_boundary_is_silent(self):
        self.assertFalse(self.tick(2,22)[0])
        self.notify.assert_not_called()

    def test_sunday_before_reopening_is_silent(self):
        self.assertFalse(self.tick(4,20,59,59)[0])
        self.notify.assert_not_called()

    def test_weekday_stale_alerts_only_once(self):
        self.assertTrue(self.tick(5,12)[0])
        self.assertFalse(self.tick(5,12,1)[0])
        self.notify.assert_called_once()

    def test_friday_before_closure_still_alerts(self):
        self.assertTrue(self.tick(2,21,59,59)[0])
        self.notify.assert_called_once()

    def test_reopening_has_grace_but_stall_is_not_hidden(self):
        self.tick(4,20,59,59)
        self.assertFalse(self.tick(4,21)[0])
        self.assertTrue(self.tick(4,21,1,30)[0])
        self.notify.assert_called_once()

    def test_weekend_clears_old_alert_latch(self):
        self.ns['_dead_mans_switch_alerted']=True
        self.tick(3,12)
        self.assertFalse(self.ns['_dead_mans_switch_alerted'])

    def test_healthy_weekday_and_unstarted_process_stay_silent(self):
        ts=datetime(2026,10,5,12,tzinfo=timezone.utc).timestamp()
        self.ns['_last_poll_completed_ts']=ts-30
        self.assertFalse(self.tick(5,12)[0])
        self.ns['_last_poll_completed_ts']=0
        self.assertFalse(self.tick(5,12)[0])
        self.notify.assert_not_called()


if __name__=='__main__': unittest.main()
