import os
from pathlib import Path
from queue import Queue
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import paper_stop_runtime as runtime
from paper_stop_journal import PaperStopJournal
from paper_stop_view import snapshot


def q(ts=1000,bid=1.1,ask=1.1002,ask_ts=None):
    return dict(bid=bid,ask=ask,bid_ts=ts,ask_ts=ts if ask_ts is None else ask_ts,
                ts=max(ts,ts if ask_ts is None else ask_ts))


class PaperRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.folder=TemporaryDirectory()
        self.path=str(Path(self.folder.name)/'account.sqlite3')
        self.patches=[patch.dict(os.environ,PAPER_STOP_JOURNAL_PATH=self.path),
                      patch.object(runtime,'_quotes',Queue(maxsize=50000)),
                      patch.object(runtime,'_intents',Queue(maxsize=512)),
                      patch.object(runtime,'_initialized',False),
                      patch.object(runtime,'_overflow',False),
                      patch.object(runtime,'_last_cycle',None),
                      patch.object(runtime,'_last_error',None),
                      patch.object(runtime,'_terms',{'EURUSD':dict(minimum=1000,step=1000,maximum=1000000,quote_currency='USD')})]
        for p in self.patches:p.start()
        self.quote=q()
        self.state=SimpleNamespace(get_paper_quote=lambda pair,now:self.quote)

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.folder.cleanup()

    def run_cycle(self,now=1000):
        with patch.object(runtime.time,'time',return_value=now):
            runtime.cycle(self.state,now,require_mount=False)
        return snapshot(self.path,now)

    def enter(self,**overrides):
        signal=dict(signal_outcome_id=1,pair='EURUSD',ts=1000,verdict_text='BUY',atr=.001)
        signal.update(overrides)
        runtime.submit(signal)
        return self.run_cycle()

    def test_no_ephemeral_account_is_created(self):
        runtime.cycle(self.state,1000)
        self.assertFalse(Path(self.path).exists())
        self.assertEqual(runtime.health()['error'],'paper_worker_error')

    def test_idle_account_initialized_and_visible_without_fake_trades(self):
        view=self.run_cycle()
        self.assertEqual(view['balance'],1000)
        self.assertEqual(view['open_positions'],[])
        self.assertFalse(view['real_orders'])

    def test_original_signal_entry_uses_ask_risk_rounding_and_fee_reserve(self):
        view=self.enter()
        p=view['open_positions'][0]
        self.assertEqual(p['entry'],1.1002)
        self.assertAlmostEqual(p['stop'],1.0992)
        self.assertAlmostEqual(p['target'],1.1017)
        self.assertEqual(p['units']%1000,0)
        self.assertLessEqual(p['units']*(.001+.00007),5)
        self.assertLess(view['equity'],1000)

    def test_fresh_bid_stop_does_not_wait_for_unchanged_old_ask(self):
        self.enter()
        runtime.receive('EURUSD',q(1001,bid=1.099,ask_ts=990))
        view=self.run_cycle(1001)
        self.assertEqual(view['closed_positions'][0]['reason'],'stop')
        self.assertLess(view['balance'],1000)

    def test_ask_only_event_does_not_falsely_freeze_long(self):
        self.enter()
        runtime.receive('EURUSD',dict(bid=1.1,ask=1.1003,bid_ts=1000,ask_ts=1008,ts=1008))
        view=self.run_cycle(1008)
        self.assertIsNone(view['open_positions'][0]['reason'])

    def test_contiguous_target_and_duplicate_no_double_credit(self):
        self.enter()
        runtime.receive('EURUSD',q(1001,1.102,1.1022))
        view=self.run_cycle(1001)
        self.assertEqual(view['closed_positions'][0]['reason'],'target')
        runtime.receive('EURUSD',q(1001,1.102,1.1022))
        self.assertEqual(self.run_cycle(1001)['balance'],view['balance'])

    def test_disconnect_never_fabricates_target_profit(self):
        self.enter()
        runtime.connection_gap()
        runtime.receive('EURUSD',q(1002,1.102,1.1022))
        view=self.run_cycle(1002)
        self.assertEqual(view['balance'],1000)
        self.assertEqual(view['open_positions'][0]['reason'],'path_gap')
        self.assertIsNone(view['equity'])
        self.assertEqual(view['runtime']['status'],'suspended_path_gap')

    def test_restart_preserves_balance_but_marks_open_path_unverified(self):
        self.enter()
        runtime._initialized=False
        view=self.run_cycle(1002)
        self.assertEqual(view['balance'],1000)
        self.assertEqual(view['open_positions'][0]['reason'],'path_gap')

    def test_queue_overflow_and_late_received_ticks_fail_closed(self):
        self.enter()
        runtime._overflow=True
        self.assertEqual(self.run_cycle()['open_positions'][0]['reason'],'path_gap')

    def test_received_path_gap_cannot_credit_optimistic_target(self):
        self.enter()
        runtime.receive('EURUSD',q(1040,1.102,1.1022))
        view=self.run_cycle(1040)
        self.assertEqual(view['balance'],1000)
        self.assertEqual(view['closed_positions'],[])

    def test_expired_and_unsupported_intents_are_journaled_not_reentered(self):
        view=self.enter(ts=980)
        self.assertEqual(view['skipped'][0]['reason'],'expired_signal_no_late_entry')
        self.assertEqual(self.enter()['open_positions'],[])
        view=self.enter(signal_outcome_id=2,pair='USDJPY')
        self.assertEqual(sum(item['total'] for item in view['skipped']),2)

    def test_one_global_position_and_visible_skip(self):
        self.enter()
        view=self.enter(signal_outcome_id=2)
        self.assertEqual(len(view['open_positions']),1)
        self.assertEqual(view['skipped'][0]['reason'],'one_open_position')

    def test_time_exit_is_price_based_not_binary_payout(self):
        self.enter()
        for ts in range(1020,2801,20):
            runtime.receive('EURUSD',q(ts))
            view=self.run_cycle(ts)
        self.assertEqual(view['closed_positions'][0]['reason'],'time_exit')
        self.assertLess(view['balance'],1000)
        self.assertNotEqual(view['balance'],990)

    def test_worker_staleness_is_visible_without_resetting_cash(self):
        self.run_cycle()
        view=snapshot(self.path,1020)
        self.assertEqual(view['runtime']['status'],'not_ready')
        self.assertEqual(view['balance'],1000)

    def test_delayed_tick_before_entry_cannot_trigger_a_stop(self):
        self.quote=dict(bid=1.1,ask=1.1002,bid_ts=999,ask_ts=1000,ts=1000)
        self.enter()
        runtime.receive('EURUSD',q(999.5,1.099,1.1002))
        view=self.run_cycle(1001)
        self.assertEqual(view['closed_positions'],[])
        self.assertEqual(view['balance'],1000)

    def test_time_exit_never_uses_a_quote_from_before_deadline(self):
        self.enter()
        for ts in range(1020,2781,20):
            runtime.receive('EURUSD',q(ts))
            self.run_cycle(ts)
        runtime.receive('EURUSD',q(2799))
        view=self.run_cycle(2801)
        self.assertEqual(view['closed_positions'],[])
        runtime.receive('EURUSD',q(2802))
        view=self.run_cycle(2802)
        self.assertEqual(view['closed_positions'][0]['reason'],'time_exit')

    def test_missing_specs_block_entry(self):
        runtime._terms={}
        view=self.enter()
        self.assertEqual(view['open_positions'],[])
        self.assertEqual(view['skipped'][0]['reason'],'broker_specs_unavailable')

    def test_retirement_rejects_new_and_already_queued_entries(self):
        runtime.submit(dict(signal_outcome_id=1,pair='EURUSD',ts=1000,verdict_text='BUY',atr=.001))
        with patch.dict(os.environ,PAPER_STOP_ACCEPT_ENTRIES='false'):
            runtime.submit(dict(signal_outcome_id=2,pair='EURUSD',ts=1000,verdict_text='BUY',atr=.001))
            self.assertEqual(runtime._intents.qsize(),1)
            view=self.run_cycle()
            self.assertEqual(view['open_positions'],[])
            self.assertEqual(view['balance'],1000)
            self.assertEqual(view['skipped'][0]['reason'],'strategy_entries_disabled')
            self.assertFalse(view['runtime']['accepting_entries'])

    def test_disabled_entries_do_not_abandon_an_existing_stop(self):
        self.enter()
        with patch.dict(os.environ,PAPER_STOP_ACCEPT_ENTRIES='false'):
            runtime.receive('EURUSD',q(1001,1.099,1.0992))
            view=self.run_cycle(1001)
            self.assertEqual(view['closed_positions'][0]['reason'],'stop')
            self.assertEqual(view['runtime']['status'],'paused_no_strategy')

    def test_metadata_uses_only_read_requests_and_verified_USD_quote_asset(self):
        from twisted.internet.defer import succeed
        from twisted.internet.task import Clock
        from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAAssetListRes,ProtoOASymbolByIdRes
        from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOALightSymbol
        assets=ProtoOAAssetListRes(ctidTraderAccountId=99)
        assets.asset.add(assetId=2,name='USD',displayName='US Dollar')
        assets.asset.add(assetId=3,name='JPY',displayName='Yen')
        symbols=ProtoOASymbolByIdRes(ctidTraderAccountId=99)
        symbols.symbol.add(symbolId=1,digits=5,pipPosition=4,minVolume=100000,stepVolume=100000,maxVolume=100000000,tradingMode=0)
        calls=[]
        def send(req):
            calls.append(type(req).__name__)
            response=assets if len(calls)%2 else symbols
            return succeed(SimpleNamespace(payload=response.SerializeToString()))
        client=SimpleNamespace(_client=SimpleNamespace(account_id=99),send=send)
        light=ProtoOALightSymbol(symbolId=1,symbolName='EURUSD',quoteAssetId=2)
        state=SimpleNamespace(client=client,SYMBOLS_LOADED=True,get_symbol_details=lambda p:light if p=='EURUSD' else None)
        with patch.object(runtime,'_metadata_client',None),patch.object(runtime,'_metadata_next',0),patch.object(runtime,'_metadata_pending',False):
            runtime.refresh_metadata(state,Clock())
            self.assertEqual(calls,['ProtoOAAssetListReq','ProtoOASymbolByIdReq'])
            self.assertEqual(runtime._terms['EURUSD']['minimum'],1000)
            light.quoteAssetId=3
            runtime._metadata_next=0
            runtime.refresh_metadata(state,Clock())
            self.assertEqual(runtime._terms,{})


if __name__=='__main__':unittest.main()
