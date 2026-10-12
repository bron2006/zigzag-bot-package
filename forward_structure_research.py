"""Prospective OHLC observations, NOT an executor or funded paper account.

All three frozen structure rules are diagnostic hypotheses. No proven edge.
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

from price_structure_candidates import RULES,generate
from paper_cfd import simulate_stop_trade

logger=logging.getLogger(__name__)
PAIRS=('EURUSD','GBPUSD','BTCUSD','ETHUSD')
VERSION='prospective_structure_observation_v1'


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


def outcome(intent,bars,now,scenario,*,crypto=False):
    end=intent['day']*86400+(86400 if crypto else 16*3600)
    available=[b for b in bars if intent['ts']<=b['ts']<end]
    if not available or available[0]['ts']!=intent['ts']:
        return dict(status='unknown' if now-intent['ts']>3600 else 'pending',reason='missing_entry_bar')
    entry=available[0]['Open'];side=intent['side']
    cost=entry*(.001 if scenario=='base' else .002) if crypto else (.0002 if scenario=='base' else .0004)
    distance=2*intent['atr'];multiple=1.5
    if intent['stop'] is not None:
        distance=side*(entry-intent['stop']);reward=side*(intent['target']-entry)
        if distance<=0 or reward<=0 or (reward-cost)/(distance+cost)<1.5:
            return dict(status='skipped',reason='invalid_entry_or_net_RR')
        multiple=reward/distance
    trade=simulate_stop_trade(available,0,side,distance,multiple)
    if trade['status']=='unknown':return trade
    if trade['reason']=='session_end' and available[-1]['ts']+300<end:
        return dict(status='unknown' if now>end+3600 else 'pending',reason='waiting_for_closed_bars')
    points=Decimal(side)*(Decimal(str(trade['exit']))-Decimal(str(entry)))
    net_R=float((points-Decimal(str(cost)))/(Decimal(str(distance))+Decimal(str(cost))))
    # USD5 risk-unit illustration, NOT money credited to any account.
    return dict(status='closed',**{k:v for k,v in trade.items() if k!='status'},
                cost_assumed_points=cost,net_R=net_R,hypothetical_risk5_usd=round(5*net_R,2),
                executable=False,venue='cTrader_midpoint_OHLC_conditional')


def store_packet(filename,pair,bars,now,*,require_mount=True):
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
        activation=db.execute('SELECT activated FROM metadata').fetchone()[0]
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
        for rule in RULES:
            for intent in generate(hours,rule,end_hour=23 if crypto else 15,start_hour=1 if crypto else 9):
                if intent['ts']<activation:continue
                for scenario in ('base','stress'):
                    key=(pair,rule,intent['day'],scenario)
                    prior=db.execute('SELECT status FROM observations WHERE pair=? AND rule=? AND day=? AND scenario=?',key).fetchone()
                    if prior and prior[0]!='pending':continue
                    result=outcome(intent,retained,now,scenario,crypto=crypto)
                    payload=dict(intent=intent,pair=pair,scenario=scenario,**result)
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
    from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAGetTrendbarsReq,ProtoOAGetTrendbarsRes
    from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod
    d=deferToThreadPool(reactor,pool,initialize)
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
                return deferToThreadPool(reactor,pool,store_packet,path(),pair,rows,time.time())
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
        db.execute('COMMIT')
    finally:db.close()
    collecting=len(sources)==len(PAIRS) and all(not s['error'] and 0<=now-s['checked']<180 for s in sources)
    return dict(enabled=True,status='collecting' if collecting else 'waiting_data',activated=meta['activated'],
        pairs=list(PAIRS),rules=list(RULES),sources=sources,counts=counts,recent=recent,bars=bar_counts,
        interval_seconds=60,real_orders=False,changes_account_balance=False,
        candles_fresh=collecting and all(s['last_bar'] is not None and now-(s['last_bar']+300)<900 for s in sources),
        mode='prospective_OHLC_observations_not_trade_execution',
        historical_FX_gate_passed=False,crypto_extension_validated=False)
