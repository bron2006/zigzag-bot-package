import json
from pathlib import Path
import tempfile
import unittest
from forward_structure_research import _connect,store_packet,snapshot,outcome,hourly


def bars(hours=40):
    result=[]
    for i in range(hours*12):
        result.append(dict(ts=i*300,Open=100.,High=100.5,Low=99.5,Close=100.))
    result[32*12+11].update(High=103.,Close=102.)
    return result


class ForwardResearchTest(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.path=str(Path(self.folder.name)/'forward.sqlite3')
    def tearDown(self):self.folder.cleanup()
    def init(self,activation):
        db=_connect(self.path,activation,False);db.close()

    def test_warmup_history_does_not_become_fake_prospective_trades(self):
        self.init(38*3600)
        store_packet(self.path,'EURUSD',bars(),40*3600+31,require_mount=False)
        view=snapshot(self.path,40*3600+32)
        self.assertEqual(view['recent'],[])
        self.assertEqual(view['counts'],[])
        self.assertFalse(view['real_orders'])
        self.assertFalse(view['changes_account_balance'])

    def test_pending_observation_only_closes_when_actual_path_available(self):
        self.init(32*3600)
        store_packet(self.path,'EURUSD',bars(34),34*3600+31,require_mount=False)
        self.assertEqual({r['status'] for r in snapshot(self.path,34*3600+32)['recent']},{'pending'})
        store_packet(self.path,'EURUSD',bars(),40*3600+31,require_mount=False)
        view=snapshot(self.path,40*3600+32)
        self.assertEqual(len(view['recent']),2)
        self.assertEqual({r['status'] for r in view['recent']},{'closed'})
        self.assertTrue(all(r['net_R']<0 for r in view['recent']))

    def test_repeat_poll_and_restart_preserve_activation_and_closed_results(self):
        self.init(32*3600)
        store_packet(self.path,'EURUSD',bars(),40*3600+31,require_mount=False)
        before=snapshot(self.path,40*3600+32)
        self.init(41*3600)
        store_packet(self.path,'EURUSD',bars(),41*3600,require_mount=False)
        after=snapshot(self.path,41*3600)
        self.assertEqual(before['activated'],after['activated'])
        self.assertEqual(before['recent'],after['recent'])

    def test_revision_fails_closed_and_does_not_rewrite_prices(self):
        self.init(32*3600)
        store_packet(self.path,'EURUSD',bars(),40*3600+31,require_mount=False)
        revised=bars();revised[0]['Close']=100.1
        with self.assertRaises(ValueError):store_packet(self.path,'EURUSD',revised,40*3600+31,require_mount=False)

    def test_unclosed_or_duplicate_candle_rejected_before_creating_file(self):
        for data,now in [(bars(),40*3600),(bars()+[bars()[-1]],41*3600)]:
            with self.assertRaises(ValueError):store_packet(self.path,'EURUSD',data,now,require_mount=False)
            self.assertFalse(Path(self.path).exists())

    def test_partial_session_is_not_fabricated_time_exit(self):
        intent=dict(day=0,ts=9*3600,side=1,atr=1.,stop=None,target=None)
        bar=dict(ts=9*3600,Open=100.,High=101.,Low=99.,Close=100.)
        self.assertEqual(outcome(intent,[bar],10*3600,'stress')['status'],'pending')
        bar.update(High=105.,Low=97.)
        result=outcome(intent,[bar],10*3600,'stress')
        self.assertEqual(result['reason'],'stop')
        self.assertTrue(result['ambiguous'])
        self.assertLess(result['hypothetical_risk5_usd'],0)

    def test_missing_entry_or_path_has_unknown_not_fake_zero_result(self):
        intent=dict(day=0,ts=9*3600,side=1,atr=1.,stop=None,target=None)
        self.assertEqual(outcome(intent,[],11*3600,'base')['status'],'unknown')
        data=[dict(ts=t,Open=100.,High=101.,Low=99.,Close=100.) for t in (9*3600,9*3600+600)]
        self.assertEqual(outcome(intent,data,10*3600,'base')['status'],'unknown')

    def test_only_complete_hours_and_forex_default_rule_unchanged(self):
        data=bars(34);data.pop(10)
        self.assertEqual(len(hourly(data)),33)

    def test_no_configured_path_is_not_running(self):
        self.assertEqual(snapshot(None,1000)['status'],'not_started')

    def test_resident_collector_sends_only_four_bounded_read_requests(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from twisted.internet.defer import succeed
        from twisted.internet.task import Clock
        from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsRes
        import forward_structure_research as research
        calls=[];epoch=1704067200;now=epoch+40*3600+31
        def send(request):
            calls.append(request)
            res=ProtoOAGetTrendbarsRes(ctidTraderAccountId=99,period=5,timestamp=int(now*1000))
            for bar in bars():
                res.trendbar.add(volume=1,low=9950000,deltaOpen=50000,deltaHigh=int((bar['High']-99.5)*100000),
                    deltaClose=int((bar['Close']-99.5)*100000),utcTimestampInMinutes=(epoch+bar['ts'])//60)
            return succeed(SimpleNamespace(payload=res.SerializeToString()))
        client=SimpleNamespace(_client=SimpleNamespace(account_id=99),is_authorized=True,send=send)
        state=SimpleNamespace(client=client,SYMBOLS_LOADED=True,get_symbol_details=lambda pair:SimpleNamespace(symbolId=research.PAIRS.index(pair)+1))
        original=research._connect
        with patch.object(research,'path',return_value=self.path),patch.object(research.time,'time',return_value=now), \
             patch.object(research,'_connect',side_effect=lambda filename,t,require_mount=True:original(filename,t,False)), \
             patch('twisted.internet.threads.deferToThreadPool',side_effect=lambda reactor,pool,f,*args:succeed(f(*args))):
            research.collect(state,Clock(),None)
        self.assertEqual(len(calls),4)
        self.assertEqual({type(r).__name__ for r in calls},{'ProtoOAGetTrendbarsReq'})
        self.assertTrue(all(r.count==2000 and r.period==5 and r.toTimestamp<now*1000 for r in calls))
        view=snapshot(self.path,now)
        self.assertEqual(view['status'],'collecting')
        self.assertEqual(len(view['sources']),4)
        self.assertEqual(view['recent'],[])
