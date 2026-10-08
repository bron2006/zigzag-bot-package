import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import tempfile
import unittest
import time
import queue
import threading
from vwap_paper_bridge import PaperBridge
from vwap_paper import read_summary
from scripts.vwap_paper_replay import replay_events

ROOT=Path(__file__).resolve().parents[1]

class AdapterTests(unittest.TestCase):
    def test_invalid_signal_during_gap_does_not_kill_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            # Preload before starting the worker so gap recovery is deterministic.
            bridge=PaperBridge.__new__(PaperBridge)
            bridge.path=Path(directory)/'gap.sqlite3'
            bridge.queue=queue.Queue(maxsize=2000)
            bridge._lost=threading.Event()
            bridge._lost.set()
            bridge._stop=threading.Event()
            bridge.ready=threading.Event()
            bridge.failed=False
            bridge._watched=set()
            bridge._seen=set()
            bridge._attached=[]
            bridge.queue.put(('signal',dict(ts=time.time())))
            bridge.thread=threading.Thread(target=bridge._run,args=(5,),daemon=True)
            bridge.thread.start()
            try:
                self.assertTrue(bridge.ready.wait(2))
                deadline=time.monotonic()+2
                while bridge.queue.unfinished_tasks and time.monotonic()<deadline:
                    time.sleep(.01)
                self.assertEqual(bridge.queue.unfinished_tasks,0)
                self.assertFalse(bridge.failed)
                self.assertTrue(bridge.thread.is_alive())
                now=time.time()
                bridge.signal(symbol='TEST',session='2026-10-08',ts=now,
                              end_ts=now+100,limit=100.,stop=99.,fee_price=.1,
                              target=101.,target_asof=now-10)
                bridge.quote('TEST',ts=now+.01,bid=99.8,ask=99.9)
                bridge.quote('TEST',ts=now+.02,bid=101.2,ask=101.3)
                deadline=time.monotonic()+2
                while bridge.queue.unfinished_tasks and time.monotonic()<deadline:
                    time.sleep(.01)
                self.assertEqual(read_summary(bridge.path)['statuses'],{'closed':1})
            finally:
                bridge.close()
    def test_queue_overflow_is_bounded_and_marks_gap(self):
        bridge=PaperBridge.__new__(PaperBridge)
        bridge.failed=False
        bridge.queue=queue.Queue(maxsize=1)
        bridge._lost=threading.Event()
        self.assertTrue(bridge._submit('quote',dict(ts=1.)))
        self.assertFalse(bridge._submit('quote',dict(ts=2.)))
        self.assertTrue(bridge._lost.is_set())
    def test_replay_and_live_bridge_use_same_model(self):
        with tempfile.TemporaryDirectory() as directory:
            now=time.time()
            signal=dict(symbol='TEST',session='2026-10-08',ts=now,end_ts=now+100,
                        limit=100.,stop=99.,fee_price=.1,target=101.,target_asof=now-10)
            events=[dict(kind='signal',payload=signal),dict(kind='quote',payload=dict(symbol='TEST',ts=now+.01,bid=99.8,ask=99.9)),
                    dict(kind='quote',payload=dict(symbol='TEST',ts=now+.02,bid=101.2,ask=101.3))]
            offline=replay_events(events,Path(directory)/'offline.sqlite3')
            bridge=PaperBridge(Path(directory)/'live.sqlite3')
            try:
                self.assertTrue(bridge.ready.wait(2))
                self.assertFalse(bridge.failed)
                self.assertTrue(bridge.signal(**signal))
                self.assertFalse(bridge.signal(**signal))
                for e in events[1:]:bridge.quote(**e['payload'])
                deadline=time.monotonic()+3
                while bridge.queue.unfinished_tasks and time.monotonic()<deadline:time.sleep(.01)
                self.assertEqual(bridge.queue.unfinished_tasks,0)
                live=read_summary(Path(directory)/'live.sqlite3')
                self.assertEqual(live['statuses'],offline['statuses'])
                self.assertAlmostEqual(live['total_r'],offline['total_r'])
            finally:bridge.close()
    def test_replay_refuses_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.sqlite3'
            replay_events([],path)
            with self.assertRaises(ValueError):replay_events([],path)
    def test_old_client_callback_ignored_and_attach_idempotent(self):
        bridge=PaperBridge.__new__(PaperBridge)
        bridge._attached=[]
        bridge.gap=Mock()
        client=Mock()
        handler=Mock()
        current=[True]
        bridge.attach(client,handler,is_current=lambda:current[0])
        bridge.attach(client,handler)
        self.assertEqual(client.on.call_count,2)
        on_spot=client.on.call_args_list[0].args[1]
        on_error=client.on.call_args_list[1].args[1]
        current[0]=False
        on_spot(object());on_error('DISCONNECTED')
        handler.assert_not_called();bridge.gap.assert_not_called()
    def test_executor_hook_is_inside_readonly_before_real_create(self):
        tree=ast.parse((ROOT/'vwap_executor.py').read_text(encoding='utf-8-sig'))
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_maybe_enter')
        paper_call=next(n for n in ast.walk(function) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='_paper_intention')
        gate=next(n for n in function.body if isinstance(n,ast.If) and '_is_read_only' in ast.unparse(n.test))
        self.assertIn(paper_call,list(ast.walk(gate)))
        self.assertIsInstance(gate.body[-1],ast.Return)
        creation=next(n for n in ast.walk(function) if isinstance(n,ast.Call) and ast.unparse(n.func)=='db.create_vwap_trade')
        self.assertLess(paper_call.lineno,creation.lineno)
    def test_spot_adapter_fixed_scale_no_past_prices(self):
        tree=ast.parse((ROOT/'vwap_executor.py').read_text(encoding='utf-8-sig'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_paper_spot_event')
        bridge=Mock()
        env=dict(_paper_bridge=bridge,app_state=SimpleNamespace(symbol_id_map={1:'TEST'}),time_module=SimpleNamespace(time=lambda:123.))
        exec(compile(ast.Module(body=[node],type_ignores=[]),'adapter-test','exec'),env)
        event=SimpleNamespace(symbolId=1,bid=10000000,ask=10001000,HasField=lambda field:True)
        env['_paper_spot_event'](event)
        bridge.quote.assert_called_once_with('TEST',ts=123.,bid=100.,ask=100.01)

if __name__=='__main__':unittest.main()
