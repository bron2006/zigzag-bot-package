import copy
import math
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import historical_endpoints as history
import db
import signal_accounting
from types import SimpleNamespace


def fixture(deadline, bids=None, asks=None):
    bids = [(deadline-10, 100)] if bids is None else bids
    asks = [(deadline-8, 102)] if asks is None else asks
    return dict(source='cTrader_asof60_shadow_v1', complete=True,
                from_ms=math.floor((deadline-60)*1000), to_ms=math.floor(deadline*1000),
                counts=[len(bids), len(asks)], endpoint=history.select_asof(bids, asks, deadline),
                sides={name: [dict(ts=t, price=p) for t,p in ticks]
                       for name,ticks in [('bid',bids),('ask',asks)]})


class AsOfTest(unittest.TestCase):
    def test_last_event_wins_equal_timestamp(self):
        quote=history.select_asof([(999,100),(999,101)],[(999,103),(999,104)],1000)
        self.assertEqual(quote['bid'],101)
        self.assertEqual(quote['ask'],104)
        self.assertTrue(history.validate_asof(fixture(1000,[(999,100),(999,101)],[(999,103),(999,104)]),1000))

    def test_alternative_balance_does_not_mix_prices_or_mutate_original_rows(self):
        row=SimpleNamespace(id=1,outcome='up_timed',entry_price=100,exit_price=102,
                            verdict='BUY',pair='TEST',entry_ts=datetime(2026,10,10))
        audit={1:dict(version='live_mid_v1',publication=dict(state='confirmed'),
                      asof_audit=dict(history=dict(endpoint=dict(mid=99,ts=1000))))}
        self.assertEqual(signal_accounting.summarize([row],audit)['scenario']['measured_balance'],1008)
        self.assertEqual(signal_accounting.summarize([row],audit,valuation='asof60')['scenario']['measured_balance'],990)
        self.assertEqual(row.exit_price,102)
        audit[1].pop('asof_audit')
        self.assertEqual(signal_accounting.summarize([row],audit,valuation='asof60')['counts'],{'pending':1})
        audit[1]['asof_audit']=dict(history=dict(endpoint=None))
        self.assertEqual(signal_accounting.summarize([row],audit,valuation='asof60')['counts'],{'unknown':1})

    def test_last_sides_at_expiry_not_first_future_tick(self):
        quote = history.select_asof([(990,100),(1001,200)], [(992,102),(1002,202)], 1000)
        self.assertEqual(quote['mid'],101)
        self.assertEqual(quote['ts'],1000)
        self.assertEqual(quote['bid_ts'],990)
        self.assertEqual(quote['max_age'],10)

    def test_no_synthetic_stale_crossed_or_missing_side(self):
        for bids,asks in [([],[(999,102)]), ([(939,100)],[(999,102)]),
                          ([(999,103)],[(999,102)]), ([(1001,100)],[(1001,102)])]:
            self.assertIsNone(history.select_asof(bids,asks,1000))

    def test_older_quote_is_diagnostic_only_not_accepted_by_60s_policy(self):
        self.assertIsNone(history.select_asof([(900,100)],[(998,102)],1000))
        quote=history.select_asof([(900,100)],[(998,102)],1000,max_age=300)
        self.assertEqual(quote['max_age'],100)
        proof=fixture(1000)
        proof['source']='cTrader_asof300_diagnostic_v1'
        self.assertFalse(history.validate_asof(proof,1000))

    def test_valid_proof_empty_proof_and_tampering(self):
        proof=fixture(1000)
        self.assertTrue(history.validate_asof(proof,1000))
        self.assertTrue(history.validate_asof(fixture(1000,[],[]),1000))
        for field,value in [('mid',999),('bid_ts',940),('ts',1001)]:
            invalid=copy.deepcopy(proof)
            invalid['endpoint'][field]=value
            self.assertFalse(history.validate_asof(invalid,1000))
        invalid=copy.deepcopy(proof)
        invalid['sides']['bid'].append(dict(ts=1001,price=200))
        invalid['counts'][0]+=1
        self.assertFalse(history.validate_asof(invalid,1000))
        proof['complete']=False
        self.assertFalse(history.validate_asof(proof,1000))


class AsOfDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.assertEqual(db.engine.url.database, ':memory:')
        db.Base.metadata.create_all(db.engine)
        self.entry=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(seconds=960)
        self.deadline=self.entry.replace(tzinfo=timezone.utc).timestamp()+900
        self.identifier=db.create_signal_outcome(pair='ZZASOF',timeframe='5m',verdict='BUY',score=20,
            entry_price=100,horizon_seconds=900,entry_ts=self.entry,
            evidence=dict(version='live_mid_v1',publication=dict(version=1,state='confirmed')))

    def test_parallel_audit_never_overwrites_outcome_price_or_receipt(self):
        db.resolve_signal_outcome(self.identifier,outcome='unknown',exit_price=None)
        proof=fixture(self.deadline)
        self.assertTrue(db.save_signal_asof_audit(self.identifier,proof))
        self.assertFalse(db.save_signal_asof_audit(self.identifier,proof))
        row=db.get_signal_endpoint_audit(self.identifier)
        self.assertEqual(row['outcome'],'unknown')
        self.assertNotIn('endpoint',row['evidence'])
        self.assertEqual(row['evidence']['publication']['state'],'confirmed')
        self.assertEqual(row['evidence']['asof_audit']['history']['endpoint']['mid'],101)

    def test_pending_or_invalid_proof_not_written(self):
        self.assertFalse(db.save_signal_asof_audit(self.identifier,fixture(self.deadline)))
        db.resolve_signal_outcome(self.identifier,outcome='up_timed',exit_price=102)
        proof=fixture(self.deadline)
        proof['endpoint']['mid']=900
        self.assertFalse(db.save_signal_asof_audit(self.identifier,proof))
