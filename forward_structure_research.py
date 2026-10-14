"""Prospective OHLC observations, NOT an executor or funded paper account.

The three structure controls and owner-defined NY reclaim have no proven edge.
FX failures remain negative controls; crypto is a new unvalidated extension.
"""
from collections import defaultdict
from decimal import Decimal
import json
import logging
import math
import os
from pathlib import Path
import sqlite3
import time
from urllib.parse import quote as uri_quote

from price_structure_candidates import RULES as STRUCTURE_RULES,generate
from ny_h4_reclaim import RULE as NY_RULE,detect as detect_ny
from paper_cfd import simulate_stop_trade
from broker_closure import closure_predicate

logger=logging.getLogger(__name__)
PAIRS=('EURUSD','GBPUSD','BTCUSD','ETHUSD')
VERSION='prospective_structure_observation_v1'
RULES=STRUCTURE_RULES+(NY_RULE,)
_schedule_client=None
_schedule_next=0
_schedules={}


def path():return os.getenv('FORWARD_STRUCTURE_RESEARCH_PATH')


def _connect(filename,now,require_mount=True):
    if require_mount and (Path(filename).parent!=Path('/data') or not os.path.ismount('/data')):
        raise ValueError('research_requires_persistent_mount')
    db=sqlite3.connect(filename,timeout=5,isolation_level=None)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS metadata (id INTEGER PRIMARY KEY CHECK(id=1),version TEXT NOT NULL,activated REAL NOT NULL)')
    db.execute('INSERT OR IGNORE INTO metadata VALUES (1,?,?)',(VERSION,now))
    if db.execute('SELECT version FROM metadata').fetchone()[0]!=VERSION:
        db.close();raise ValueError('research_contract_mismatch')
    db.execute('CREATE TABLE IF NOT EXISTS bars (pair TEXT NOT NULL,ts INTEGER NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(pair,ts))')
    db.execute('CREATE TABLE IF NOT EXISTS sources (pair TEXT PRIMARY KEY,checked REAL NOT NULL,last_bar INTEGER,error TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS observations (pair TEXT NOT NULL,rule TEXT NOT NULL,day INTEGER NOT NULL,scenario TEXT NOT NULL,status TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(pair,rule,day,scenario))')
    db.execute('CREATE TABLE IF NOT EXISTS rule_activation (rule TEXT PRIMARY KEY,activated REAL NOT NULL)')
    original=db.execute('SELECT activated FROM metadata').fetchone()[0]
    for rule in RULES:
        db.execute('INSERT OR IGNORE INTO rule_activation VALUES (?,?)',(rule,now if rule==NY_RULE else original))
    db.execute('CREATE TABLE IF NOT EXISTS pattern_states (pair TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS schedule_snapshots (pair TEXT PRIMARY KEY,fetched REAL NOT NULL,payload TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS observation_revisions (id INTEGER PRIMARY KEY,pair TEXT,rule TEXT,day INTEGER,scenario TEXT,revised REAL,prior TEXT,replacement TEXT)')
    return db


def initialize(now=None):
    if not path():return
    db=_connect(path(),time.time() if now is None else now)
    db.close()


def hourly(bars):
    groups=defaultdict(list)
    for b in bars:groups[b['ts']//3600].append(b)
    out=[]
    for h,group in sorted(groups.items()):
        ts=h*3600
        if [b['ts'] for b in group]!=list(range(ts,ts+3600,300)):continue
        out.append(dict(ts=ts,Open=group[0]['Open'],High=max(b['High'] for b in group),
                        Low=min(b['Low'] for b in group),Close=group[-1]['Close']))
    return out


def outcome(intent,bars,now,scenario,*,crypto=False,schedule=None):
    ny_rule=intent.get('rule')==NY_RULE
    end=float('inf') if ny_rule else intent['day']*86400+(86400 if crypto else 16*3600)
    available=[b for b in bars if intent['ts']<=b['ts']<end]
    if not available or available[0]['ts']!=intent['ts']:
        return dict(status='unknown' if now-intent['ts']>3600 else 'pending',reason='missing_entry_bar')
    entry=available[0]['Open'];side=intent['side']
    cost=entry*(.001 if scenario=='base' else .002) if crypto else (.0002 if scenario=='base' else .0004)
    if ny_rule:
        distance=side*(entry-intent['stop']);multiple=2.
        if distance<=0 or entry+side*multiple*distance<=0:
            return dict(status='skipped',reason='entry_gap_invalid_stop_geometry')
    else:
        distance=2*intent['atr'];multiple=1.5
    if not ny_rule and intent['stop'] is not None:
        distance=side*(entry-intent['stop']);reward=side*(intent['target']-entry)
        if distance<=0 or reward<=0 or (reward-cost)/(distance+cost)<1.5:
            return dict(status='skipped',reason='invalid_entry_or_net_RR')
        multiple=reward/distance
    proof=closure_predicate(schedule) if ny_rule else None
    trade=simulate_stop_trade(available,0,side,distance,multiple,gap_is_closed=proof)
    if trade['status']=='unknown':return trade
    if ny_rule and trade['reason']=='session_end':
        return dict(status='pending',reason='waiting_stop_or_target',entry=trade['entry'],stop=trade['stop'],target=trade['target'])
    if trade['reason']=='session_end' and available[-1]['ts']+300<end:
        return dict(status='unknown' if now>end+3600 else 'pending',reason='waiting_for_closed_bars')
    points=Decimal(side)*(Decimal(str(trade['exit']))-Decimal(str(entry)))
    net_R=float((points-Decimal(str(cost)))/(Decimal(str(distance))+Decimal(str(cost))))
    # USD5 risk-unit illustration, NOT money credited to any account.
    return dict(status='closed',**{k:v for k,v in trade.items() if k!='status'},
                cost_assumed_points=cost,net_R=net_R,hypothetical_risk5_usd=round(5*net_R,2),
                cost_complete=False,
                executable=False,venue='cTrader_midpoint_OHLC_conditional')


def store_packet(filename,pair,bars,now,*,require_mount=True,schedule=None):
    if pair not in PAIRS:raise ValueError('unsupported_pair')
    if not bars:raise ValueError('empty_broker_history')
    previous=-1
    for b in bars:
        values=[b[k] for k in ('Open','High','Low','Close')]
        if b['ts']<=previous or b['ts']%300 or b['ts']+300>math.floor((now-30)/300)*300:
            raise ValueError('duplicate_unordered_or_unclosed_bar')
        if not all(math.isfinite(v) and v>0 for v in values) or not b['Low']<=min(b['Open'],b['Close'])<=max(b['Open'],b['Close'])<=b['High']:
            raise ValueError('invalid_OHLC')
        previous=b['ts']
    db=_connect(filename,now,require_mount)
    try:
        db.execute('BEGIN IMMEDIATE')
        activations=dict(db.execute('SELECT rule,activated FROM rule_activation').fetchall())
        if schedule is not None and closure_predicate(schedule) is not None:
            db.execute('INSERT OR REPLACE INTO schedule_snapshots VALUES (?,?,?)',(pair,schedule.get('_fetched',now),json.dumps(schedule,sort_keys=True)))
        for b in bars:
            encoded=json.dumps(b,sort_keys=True)
            old=db.execute('SELECT payload FROM bars WHERE pair=? AND ts=?',(pair,b['ts'])).fetchone()
            if old and old[0]!=encoded:raise ValueError('sealed_broker_bar_revision')
            db.execute('INSERT OR IGNORE INTO bars VALUES (?,?,?)',(pair,b['ts'],encoded))
        db.execute('INSERT OR REPLACE INTO sources VALUES (?,?,?,NULL)',(pair,now,bars[-1]['ts']))
        # Cached history is WARMUP ONLY. Count only post-activation setup times.
        # Candle-boundary entry is a modeled OHLC observation, NOT proof we
        # received a signal before that opening tick or could execute at it.
        first=now-6*86400
        old_pending=db.execute("SELECT pair,rule,day,scenario,payload FROM observations WHERE pair=? AND status='pending' AND day<?",(pair,int(first//86400))).fetchall()
        for old in old_pending:
            payload=json.loads(old['payload']);payload.update(status='unknown',reason='collector_coverage_gap')
            db.execute('UPDATE observations SET status=?,payload=? WHERE pair=? AND rule=? AND day=? AND scenario=?',
                ('unknown',json.dumps(payload,sort_keys=True),old['pair'],old['rule'],old['day'],old['scenario']))
        retained=[json.loads(r[0]) for r in db.execute('SELECT payload FROM bars WHERE pair=? AND ts>=? ORDER BY ts',(pair,first))]
        hours=hourly(retained);crypto=pair in ('BTCUSD','ETHUSD')
        ny=detect_ny(retained)
        if ny['states']:
            current=dict(ny['states'][-1],pair=pair)
            if current.get('entry_ts',float('inf'))<activations[NY_RULE]:
                current['status']='setup_before_activation'
            db.execute('INSERT OR REPLACE INTO pattern_states VALUES (?,?)',(pair,json.dumps(current,sort_keys=True)))
        for rule in RULES:
            intents=ny['intents'] if rule==NY_RULE else generate(hours,rule,end_hour=23 if crypto else 15,start_hour=1 if crypto else 9)
            for intent in intents:
                if intent['ts']<activations[rule]:continue
                for scenario in ('base','stress'):
                    key=(pair,rule,intent['day'],scenario)
                    prior=db.execute('SELECT status,payload FROM observations WHERE pair=? AND rule=? AND day=? AND scenario=?',key).fetchone()
                    repair=bool(prior and rule==NY_RULE and prior[0]=='unknown' and json.loads(prior[1]).get('reason')=='path_gap' and schedule is not None)
                    if prior and prior[0]!='pending' and not repair:continue
                    result=outcome(intent,retained,now,scenario,crypto=crypto,schedule=schedule)
                    payload=dict(intent=intent,pair=pair,scenario=scenario,**result)
                    if repair:
                        if result['status']=='unknown':continue
                        payload['revision_reason']='verified_weekly_closure_policy_v1'
                        db.execute('INSERT INTO observation_revisions (pair,rule,day,scenario,revised,prior,replacement) VALUES (?,?,?,?,?,?,?)',key+(now,prior[1],json.dumps(payload,sort_keys=True)))
                    db.execute('INSERT OR REPLACE INTO observations VALUES (?,?,?,?,?,?)',key+(result['status'],json.dumps(payload,sort_keys=True)))
        db.execute('COMMIT')
    except Exception:
        db.execute('ROLLBACK');raise
    finally:db.close()


def source_error(pair,reason):
    if not path():return
    db=_connect(path(),time.time())
    try:
        db.execute('INSERT INTO sources VALUES (?,0,NULL,?) ON CONFLICT(pair) DO UPDATE SET error=excluded.error',(pair,reason))
    finally:db.close()


def collect(state,reactor,pool):
    """Bounded four READ requests on resident client, all SQLite off reactor."""
    from twisted.internet.threads import deferToThreadPool
    from twisted.internet.defer import succeed
    if not path():return succeed(None)
    client=state.client
    account=getattr(getattr(client,'_client',None),'account_id',None)
    if not client or not account or not getattr(client,'is_authorized',False) or not state.SYMBOLS_LOADED:
        return deferToThreadPool(reactor,pool,initialize)
    from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq,ProtoOAGetTrendbarsRes,ProtoOASymbolByIdReq,ProtoOASymbolByIdRes
    from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod
    d=deferToThreadPool(reactor,pool,initialize)
    def refresh(_):
        global _schedule_client,_schedule_next,_schedules
        if client is not _schedule_client:_schedule_client=client;_schedule_next=0;_schedules={}
        if time.time()<_schedule_next:return None
        _schedule_next=time.time()+300
        lights={p:state.get_symbol_details(p) for p in PAIRS}
        ids=[s.symbolId for s in lights.values() if s is not None]
        if not ids:return None
        child=client.send(ProtoOASymbolByIdReq(ctidTraderAccountId=account,symbolId=ids));child.addTimeout(10,reactor)
        def received(message):
            global _schedules
            if client is not state.client:return None
            from google.protobuf.json_format import MessageToDict
            res=ProtoOASymbolByIdRes();res.ParseFromString(message.payload)
            specs={s.symbolId:MessageToDict(s,preserving_proto_field_name=True) for s in res.symbol}
            now=time.time()
            _schedules={p:(now,dict(specs[s.symbolId],_fetched=now)) for p,s in lights.items() if s is not None and s.symbolId in specs and closure_predicate(specs[s.symbolId]) is not None}
        def failed(failure):
            global _schedules,_schedule_next
            _schedules={};_schedule_next=time.time()+60
            logger.warning('FORWARD schedule refresh failed: %s',failure.type.__name__);return None
        child.addCallback(received);child.addErrback(failed);return child
    d.addCallback(refresh)
    for pair in PAIRS:
        def request(_,pair=pair):
            if client is not state.client:return None
            symbol=state.get_symbol_details(pair)
            if symbol is None:return deferToThreadPool(reactor,pool,source_error,pair,'symbol_unavailable')
            now=time.time();cutoff=int((now-30)//300)*300
            req=ProtoOAGetTrendbarsReq(ctidTraderAccountId=account,symbolId=symbol.symbolId,
                period=ProtoOATrendbarPeriod.M5,fromTimestamp=(cutoff-6*86400)*1000,toTimestamp=cutoff*1000-1,count=2000)
            child=client.send(req);child.addTimeout(10,reactor)
            def received(message):
                if client is not state.client:return None
                res=ProtoOAGetTrendbarsRes();res.ParseFromString(message.payload)
                rows=[]
                for b in res.trendbar:
                    low=b.low
                    rows.append(dict(ts=b.utcTimestampInMinutes*60,Open=(low+b.deltaOpen)/100000,
                        High=(low+b.deltaHigh)/100000,Low=low/100000,Close=(low+b.deltaClose)/100000))
                rows.sort(key=lambda b:b['ts'])
                stamp=time.time();entry=_schedules.get(pair)
                schedule=entry[1] if entry and 0<=stamp-entry[0]<600 else None
                return deferToThreadPool(reactor,pool,store_packet,path(),pair,rows,stamp,schedule=schedule)
            def failed(failure):
                logger.warning('FORWARD research source failed for %s: %s',pair,failure.type.__name__)
                return deferToThreadPool(reactor,pool,source_error,pair,failure.type.__name__)
            child.addCallback(received);child.addErrback(failed)
            return child
        d.addCallback(request)
    def unexpected(failure):
        logger.error('FORWARD research cycle failed: %s',failure.type.__name__)
        return None
    return d.addErrback(unexpected)


def snapshot(filename,now):
    if not filename:return dict(enabled=False,status='not_started')
    if not Path(filename).is_file():return dict(enabled=True,status='starting')
    uri='file:'+uri_quote(Path(filename).resolve().as_posix(),safe='/:')+'?mode=ro'
    db=sqlite3.connect(uri,uri=True,timeout=5,isolation_level=None);db.row_factory=sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        meta=db.execute('SELECT * FROM metadata').fetchone()
        if not meta or meta['version']!=VERSION:raise ValueError('research_contract_mismatch')
        sources=[dict(r) for r in db.execute('SELECT * FROM sources ORDER BY pair')]
        counts=[dict(r) for r in db.execute('SELECT rule,scenario,status,count(*) total FROM observations GROUP BY rule,scenario,status ORDER BY rule,scenario,status')]
        recent=[json.loads(r[0]) for r in db.execute('SELECT payload FROM observations ORDER BY day DESC,pair,rule,scenario LIMIT 60')]
        bar_counts=[dict(r) for r in db.execute('SELECT pair,count(*) total FROM bars GROUP BY pair')]
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        activations=dict(db.execute('SELECT rule,activated FROM rule_activation').fetchall()) if 'rule_activation' in tables else {}
        pattern_states=[json.loads(r[0]) for r in db.execute('SELECT payload FROM pattern_states ORDER BY pair')] if 'pattern_states' in tables else []
        schedule_states=[dict(r) for r in db.execute('SELECT pair,fetched FROM schedule_snapshots ORDER BY pair')] if 'schedule_snapshots' in tables else []
        revisions=db.execute('SELECT count(*) FROM observation_revisions').fetchone()[0] if 'observation_revisions' in tables else 0
        db.execute('COMMIT')
    finally:db.close()
    collecting=len(sources)==len(PAIRS) and all(not s['error'] and 0<=now-s['checked']<180 for s in sources)
    return dict(enabled=True,status='collecting' if collecting else 'waiting_data',activated=meta['activated'],
        pairs=list(PAIRS),rules=list(RULES),sources=sources,counts=counts,recent=recent,bars=bar_counts,
        rule_activations=activations,ny_h4_states=pattern_states,
        schedules=schedule_states,revision_count=revisions,
        interval_seconds=60,real_orders=False,changes_account_balance=False,
        candles_fresh=collecting and all(s['last_bar'] is not None and now-(s['last_bar']+300)<900 for s in sources),
        mode='prospective_OHLC_observations_not_trade_execution',
        historical_FX_gate_passed=False,crypto_extension_validated=False)
