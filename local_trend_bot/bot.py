"""Standalone PUBLIC-data diagnostic paper bot. No real-order API exists."""
import argparse
from datetime import datetime,timezone
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from urllib.parse import urlencode
from urllib.request import urlopen
from .strategy import DAY,SYMBOLS,RULES,VERSION,latest_decision

ROOT=Path(__file__).resolve().parents[1]
HOST='https://data-api.binance.vision/api/v3/'


def get_public(route,**params):
    if route not in ('time','klines','ticker/bookTicker'):
        raise ValueError('Only public market-data routes allowed')
    with urlopen(HOST+route+'?'+urlencode(params),timeout=10) as response:
        return json.load(response)


def fetch_public():
    now=int(time.time()*1000)
    server=int(get_public('time')['serverTime'])
    if abs(server-now)>60000:
        raise ValueError('Local and exchange clocks differ by more than 60 seconds')
    result=dict(observed_ms=now,symbols={})
    for symbol in SYMBOLS:
        rows=[]
        cursor=1546300800000  # 2019-01-01 UTC; same initial rule state as research.
        while cursor<now:
            batch=get_public('klines',symbol=symbol,interval='1d',startTime=cursor,endTime=now,limit=1000)
            if not isinstance(batch,list) or not batch:
                raise ValueError('Incomplete public history')
            rows.extend(batch)
            next_cursor=int(batch[-1][0])+DAY
            if next_cursor<=cursor: raise ValueError('Non-advancing data cursor')
            cursor=next_cursor
        quote=get_public('ticker/bookTicker',symbol=symbol)
        result['symbols'][symbol]=dict(rows=rows,bid=float(quote['bidPrice']),ask=float(quote['askPrice']),quote_ms=int(time.time()*1000))
    return result


def bounded_fetch():
    result=subprocess.run([sys.executable,'-m','local_trend_bot.bot','--fetch-worker'],
                          cwd=ROOT,capture_output=True,text=True,timeout=45)
    if result.returncode:
        raise RuntimeError('Public fetch failed: '+result.stderr[-1000:])
    return json.loads(result.stdout)


class PaperBot:
    def __init__(self,path,diagnostic=False):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=open(str(self.path)+'.lock','a+b')
        if self.lock.seek(0,2)==0: self.lock.write(b'0');self.lock.flush()
        self.lock.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.lock.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            raise RuntimeError('Another local trend bot already owns this journal')
        self.db=sqlite3.connect(self.path,timeout=.5)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS books(rule TEXT,symbol TEXT,cash REAL,units REAL,PRIMARY KEY(rule,symbol));
          CREATE TABLE IF NOT EXISTS decisions(day INTEGER,rule TEXT,symbol TEXT,data TEXT,PRIMARY KEY(day,rule,symbol));
          CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,ts INTEGER,kind TEXT,data TEXT);
          CREATE TABLE IF NOT EXISTS health(key TEXT PRIMARY KEY,data TEXT);
        ''')
        self.diagnostic=diagnostic
        with self.db:
            for rule in RULES:
                for symbol in SYMBOLS:
                    self.db.execute('INSERT OR IGNORE INTO books VALUES(?,?,500,0)',(rule,symbol))

    def close(self):
        self.db.close()
        self.lock.close()

    def error(self,message):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO health VALUES(?,?)',('last_error',json.dumps(dict(ts=int(time.time()*1000),message=message))))

    def cycle(self,data,now_ms):
        # Validate all inputs BEFORE a transaction: no half-executed portfolio.
        if not 0<=now_ms-data['observed_ms']<=45000:
            raise ValueError('Stale/future fetch')
        inputs=[]
        for symbol in SYMBOLS:
            source=data['symbols'][symbol]
            bid,ask=source['bid'],source['ask']
            if not all(math.isfinite(v) and v>0 for v in (bid,ask)) or bid>ask:
                raise ValueError('Invalid observed bid/ask')
            if not 0<=now_ms-source['quote_ms']<=45000:
                raise ValueError('Stale/future quote')
            for rule in RULES:
                decision=latest_decision(source['rows'],rule,now_ms)
                inputs.append((rule,symbol,bid,ask,decision))
        records=[]
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            for rule,symbol,bid,ask,decision in inputs:
                day=decision['day']
                duplicate=self.db.execute('SELECT 1 FROM decisions WHERE day=? AND rule=? AND symbol=?',(day,rule,symbol)).fetchone()
                cash,units=self.db.execute('SELECT cash,units FROM books WHERE rule=? AND symbol=?',(rule,symbol)).fetchone()
                if duplicate:
                    action='already_processed'
                else:
                    prior=self.db.execute('SELECT MAX(day) FROM decisions WHERE rule=? AND symbol=?',(rule,symbol)).fetchone()[0]
                    action='bootstrap_cash' if prior is None else 'observe_only'
                    # Diagnostic explicitly permits testing a rejected rule, not
                    # a claim that a failed historical gate magically passed.
                    if prior is not None and self.diagnostic:
                        action='hold' if units else 'cash'
                        if decision['desired'] and not units:
                            units,cash=cash*.997/ask,0.
                            action='paper_buy'
                        elif not decision['desired'] and units:
                            cash,units=units*bid*.997,0.
                            action='paper_sell'
                        self.db.execute('UPDATE books SET cash=?,units=? WHERE rule=? AND symbol=?',(cash,units,rule,symbol))
                    decision.update(action=action,observed_ms=now_ms,diagnostic_paper=self.diagnostic,
                                    missed_days=max(0,(day-prior)//DAY-1) if prior is not None else 0)
                    self.db.execute('INSERT INTO decisions VALUES(?,?,?,?)',(day,rule,symbol,json.dumps(decision)))
                    if action in ('paper_buy','paper_sell'):
                        self.db.execute('INSERT INTO events(ts,kind,data) VALUES(?,?,?)',
                                        (now_ms,action,json.dumps(dict(rule=rule,symbol=symbol,bid=bid,ask=ask,cash=cash,units=units,fee=.003))))
                records.append(dict(rule=rule,symbol=symbol,action=action,desired=decision['desired'],cash=cash,units=units,
                                    net_liquidation=cash+units*bid*.997))
            summary=dict(version=VERSION,mode='diagnostic_paper' if self.diagnostic else 'signals_only',
                         observed_ms=now_ms,real_orders_possible=False,proven_edge=False,records=records)
            self.db.execute('INSERT OR REPLACE INTO health VALUES(?,?)',('last_success',json.dumps(summary)))
            self.db.execute('DELETE FROM health WHERE key=?',('last_error',))
        return summary


def status(path):
    if not Path(path).exists(): return dict(exists=False)
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=.5)
    try:
        result=dict(exists=True,health={k:json.loads(v) for k,v in db.execute('SELECT key,data FROM health')},
                    paper_trades=db.execute('SELECT count(*) FROM events').fetchone()[0])
        return result
    finally: db.close()


def main():
    parser=argparse.ArgumentParser(description='Локальний дослідницький бот. Реальні ордери неможливі.')
    parser.add_argument('--fetch-worker',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--loop',action='store_true')
    parser.add_argument('--diagnostic-paper',action='store_true')
    parser.add_argument('--status',action='store_true')
    parser.add_argument('--journal',type=Path,default=ROOT/'logs'/'local_trend_bot.sqlite3')
    args=parser.parse_args()
    if args.fetch_worker:
        print(json.dumps(fetch_public(),allow_nan=False));return
    if args.status:
        print(json.dumps(status(args.journal),indent=2,ensure_ascii=False));return
    bot=PaperBot(args.journal,args.diagnostic_paper)
    try:
        while True:
            try:
                summary=bot.cycle(bounded_fetch(),int(time.time()*1000))
                print(json.dumps(summary,ensure_ascii=False,allow_nan=False),flush=True)
            except Exception as error:
                bot.error(str(error))
                print('No paper orders: '+str(error),file=sys.stderr,flush=True)
                if not args.loop: raise SystemExit(1)
            if not args.loop: break
            time.sleep(900)
    finally: bot.close()


if __name__=='__main__': main()
