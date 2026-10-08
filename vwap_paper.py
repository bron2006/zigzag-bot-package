"""Local durable LONG/LIMIT quote model. No broker, config or network imports.

Prices are observed quotes, not guaranteed executions. PnL is in R, not cash.
One immutable intention per symbol/session; restart or known feed loss makes
active outcomes unknown rather than fabricating a path through missing data.
"""
import json
import math
from pathlib import Path
import sqlite3
import os

class JournalInUse(RuntimeError):
    pass

VERSION = 'vwap-paper-quote-market-v1'
ACTIVE = ('pending', 'open')

class PaperJournal:
    def __init__(self, path, *, max_positions=5, quote_age=15., gap_seconds=120., restart_ts=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = open(str(self.path)+'.lock','a+b')
        if self._lock.seek(0,2)==0:
            self._lock.write(b'0'); self._lock.flush()
        self._lock.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self._lock.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self._lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as error:
            self._lock.close()
            raise JournalInUse('Another paper writer owns this journal') from error
        self.db = sqlite3.connect(str(self.path), timeout=.2)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=NORMAL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS paper_orders (
                key TEXT PRIMARY KEY, symbol TEXT NOT NULL, session TEXT NOT NULL,
                status TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS paper_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL,
                ts REAL NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL);
        ''')
        self.max_positions = max_positions
        self.quote_age = quote_age
        self.gap_seconds = gap_seconds
        self.orders = {key: json.loads(data) for key, data in self.db.execute('SELECT key,data FROM paper_orders')}
        self.active_keys = {key for key,o in self.orders.items() if o['status'] in ACTIVE}
        self.quotes = {}
        self.targets = {}
        if restart_ts is not None:
            self.gap(restart_ts, 'process_restart')

    def close(self):
        self.db.close()
        self._lock.close()

    def _event(self, order, ts, kind, detail):
        self.db.execute('INSERT INTO paper_events(key,ts,kind,data) VALUES(?,?,?,?)',
                        (order['key'], ts, kind, json.dumps(detail, allow_nan=False)))

    def _save(self, order):
        self.db.execute('INSERT OR REPLACE INTO paper_orders VALUES(?,?,?,?,?)',
                        (order['key'], order['symbol'], order['session'], order['status'], json.dumps(order, allow_nan=False)))

    def signal(self, *, symbol, session, ts, end_ts, limit, stop, fee_price, target, target_asof, volume=0):
        if not all(math.isfinite(v) for v in (ts,end_ts,limit,stop,fee_price,target,target_asof)):
            raise ValueError('Nonfinite paper intention')
        if not 0 < stop < limit or fee_price < 0 or target_asof > ts:
            raise ValueError('Invalid risk, fee or future target')
        if not end_ts-4*3600 <= ts < end_ts:
            return False
        key = f'{session}:{symbol}'
        # BEGIN IMMEDIATE + key uniqueness also protects overlapping processes.
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self.db.execute('SELECT 1 FROM paper_orders WHERE key=?', (key,)).fetchone():
                return False
            count = self.db.execute("SELECT count(*) FROM paper_orders WHERE status IN ('pending','open')").fetchone()[0]
            order = dict(key=key,symbol=symbol,session=session,signal_ts=ts,end_ts=end_ts,
                         limit=limit,stop=stop,fee_price=fee_price,volume=volume,
                         status='pending' if count<self.max_positions else 'skipped_capacity',
                         strategy_version=VERSION,execution_model='observed_quotes_market_exit',
                         guaranteed_broker_execution=False)
            order.update(initial_target=target,initial_target_asof=target_asof)
            self._save(order)
            self._event(order,ts,'signal',dict(order))
        self.orders[key] = order
        if order['status']=='skipped_capacity':
            return False
        self.active_keys.add(key)
        self.target(symbol, ts=ts, value=target, asof=target_asof)
        return True

    def target(self, symbol, *, ts, value, asof):
        if not all(math.isfinite(v) for v in (ts,value,asof)) or value <= 0 or asof > ts:
            raise ValueError('Invalid or future VWAP')
        previous = self.targets.get(symbol)
        if previous and asof <= previous['asof']:
            return
        self.targets[symbol] = dict(value=value,asof=asof,observed_ts=ts)
        with self.db:
            for order in self._active_orders():
                if order['symbol'] == symbol and order['status'] in ACTIVE:
                    self._event(order,ts,'target',self.targets[symbol])

    def _finish(self, order, ts, status, reason, price=None):
        order.update(status=status,exit_ts=ts,exit_reason=reason)
        if price is not None:
            order['exit_price'] = price
            order['r'] = (price-order['fill_price']-order['fee_price'])/(order['limit']-order['stop'])
        self._save(order)
        self._event(order,ts,status,dict(order))
        self.active_keys.discard(order['key'])

    def _active_orders(self):
        return [self.orders[key] for key in tuple(self.active_keys)]

    def gap(self, ts, reason):
        with self.db:
            for order in self._active_orders():
                if order['status'] in ACTIVE:
                    self._finish(order,ts,'unknown',reason)
        self.quotes.clear()
        self.targets.clear()

    def advance(self, ts):
        with self.db:
            for order in self._active_orders():
                if order['status'] not in ACTIVE or ts < order['end_ts']:
                    continue
                if order['status'] == 'pending':
                    q=self.quotes.get(order['symbol'],{})
                    covered=all(0 <= order['end_ts']-q.get(side+'_ts',float('-inf')) <= self.quote_age
                                and q.get(side+'_ts',0)>order['signal_ts'] for side in ('bid','ask'))
                    covered = covered and q['bid'] <= q['ask']
                    self._finish(order,ts,'expired' if covered else 'unknown',
                                 'session_end_unfilled' if covered else 'missing_quotes_for_expiration')
                    continue
                q = self.quotes.get(order['symbol'], {})
                bid_ts = q.get('bid_ts', float('-inf'))
                if q.get('bid_valid',False) and 0 <= order['end_ts']-bid_ts <= self.quote_age:
                    self._finish(order,ts,'closed','session_end_last_observed_bid',q['bid'])
                else:
                    self._finish(order,ts,'unknown','missing_bid_at_session_end')

    def halt(self, ts):
        with self.db:
            for order in self._active_orders():
                if order['status']=='pending':
                    self._finish(order,ts,'cancelled','paper_manual_stop')
                else:
                    q=self.quotes.get(order['symbol'],{})
                    if q.get('bid_valid',False) and 0<=ts-q.get('bid_ts',float('-inf'))<=self.quote_age:
                        self._finish(order,ts,'closed','paper_manual_stop',q['bid'])
                    else:
                        self._finish(order,ts,'unknown','missing_bid_for_manual_stop')

    def quote(self, symbol, *, ts, bid=None, ask=None):
        if not math.isfinite(ts) or any(v is not None and (not math.isfinite(v) or v <= 0) for v in (bid,ask)):
            raise ValueError('Invalid paper quote')
        self.advance(ts)  # No fills at/after session end, no later price used for past exit.
        q = self.quotes.setdefault(symbol,{})
        if ts < q.get('last_ts', ts):
            return
        active = [o for o in self._active_orders() if o['symbol']==symbol]
        baseline=max(q.get('last_ts',ts),min((o['signal_ts'] for o in active),default=ts))
        if active and ts-baseline > self.gap_seconds:
            with self.db:
                for order in active:
                    self._finish(order,ts,'unknown','quote_stream_gap')
            q.clear()
            active = []
        q['last_ts'] = ts
        for side,value in (('bid',bid),('ask',ask)):
            if value is not None:
                q[side],q[side+'_ts'] = value,ts
        if bid is not None:
            q['bid_valid'] = ask is None or bid<=ask
        if active:
            with self.db:
                for order in active:
                    self._event(order,ts,'quote',dict(bid=bid,ask=ask,observed=dict(q)))
        if 'bid' not in q or 'ask' not in q or q['bid'] > q['ask']:
            if ask is not None and 'bid' not in q:
                with self.db:
                    for order in active:
                        if order['status']=='pending' and ts>order['signal_ts'] and ask<=order['limit']:
                            self._finish(order,ts,'unknown','missing_bid_at_possible_fill')
            # An open long can sell on a fresh BID-only event; the old ASK
            # need not have updated yet. Invalid combined quotes cannot exit.
            if not any(o['status']=='open' for o in active) or bid is None or not q.get('bid_valid',False):
                return
        if not active:
            return
        with self.db:
            for order in active:
                fresh = all(0 <= ts-q[side+'_ts'] <= self.quote_age for side in ('bid','ask'))
                if order['status']=='pending':
                    if ts > order['signal_ts'] and ask is not None and ask<=order['limit'] and not fresh:
                        self._finish(order,ts,'unknown','missing_bid_at_possible_fill')
                        continue
                    if ts <= order['signal_ts'] or not fresh or q['ask'] > order['limit']:
                        continue
                    order.update(status='open',fill_ts=ts,fill_price=order['limit'])
                    self._save(order)
                    self._event(order,ts,'filled',dict(order))
                # A new BID is required for an exit; never recycle a past BID
                # as a new target execution. At fill, both sides must be fresh.
                can_exit = bid is not None or order.get('fill_ts')==ts
                if not can_exit or not q.get('bid_valid',False) or ts-q['bid_ts'] > self.quote_age:
                    continue
                if q['bid'] <= order['stop']:
                    self._finish(order,ts,'closed','stop',q['bid'])
                    continue
                target = self.targets.get(symbol)
                if target and ts >= target['observed_ts'] and q['bid'] >= target['value']:
                    self._finish(order,ts,'closed','vwap_observed_market_bid',q['bid'])

def read_summary(path):
    path = Path(path)
    if not path.exists():
        return dict(exists=False,orders=0,statuses={})
    # Read-only URI: reporting must not create or modify the journal.
    db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.2)
    try:
        records = [json.loads(r[0]) for r in db.execute('SELECT data FROM paper_orders')]
        statuses = {}
        for r in records:
            statuses[r['status']] = statuses.get(r['status'],0)+1
        closed = [r for r in records if r['status']=='closed']
        values = [r['r'] for r in closed]
        gains,losses = sum(v for v in values if v>0),-sum(v for v in values if v<0)
        days={}
        for record in records:
            day=days.setdefault(record['session'],dict(statuses={},closed=0,total_r=None))
            status=record['status']
            day['statuses'][status]=day['statuses'].get(status,0)+1
            if status=='closed':
                day['closed']+=1
                day['total_r']=(day['total_r'] or 0)+record['r']
        return dict(exists=True,orders=len(records),statuses=statuses,closed=len(closed),days=days,
                    total_r=sum(values) if values else None,pf=gains/losses if losses else None,
                    records=records,guaranteed_broker_execution=False)
    finally:
        db.close()
