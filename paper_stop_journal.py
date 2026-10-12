"""Persistent LOCAL paper SL/TP ledger. No broker SDK or real-order function."""
from decimal import Decimal
import json
import math
import sqlite3
from paper_cfd import size_position,net_usd


def validate_quote(quote,now,side=None):
    values=[quote.get(k) for k in ('bid','ask','bid_ts','ask_ts','ts')]
    if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in values):
        raise ValueError('invalid_quote')
    bid,ask,bt,at,ts=values
    times=(bt,at,ts) if side is None else ((bt,) if side==1 else (at,))
    if min(bid,ask)<=0 or (side is None and bid>ask) or ts!=max(bt,at) or not all(0<=now-t<=5 for t in times):
        raise ValueError('stale_future_or_crossed_quote')


class PaperStopJournal:
    VERSION='local-paper-stops-v1'

    def __init__(self,path,initial=1000):
        if not math.isfinite(initial) or initial<=0: raise ValueError('invalid_initial_balance')
        self.connection=sqlite3.connect(path,timeout=5,isolation_level=None)
        self.connection.row_factory=sqlite3.Row
        self.connection.execute('PRAGMA journal_mode=WAL')
        self.connection.execute('CREATE TABLE IF NOT EXISTS account (id INTEGER PRIMARY KEY CHECK(id=1), version TEXT NOT NULL, initial TEXT NOT NULL, balance TEXT NOT NULL)')
        self.connection.execute('CREATE TABLE IF NOT EXISTS positions (id INTEGER PRIMARY KEY, intent TEXT UNIQUE NOT NULL, pair TEXT NOT NULL, side INTEGER NOT NULL, entry REAL NOT NULL, stop REAL NOT NULL, target REAL NOT NULL, units REAL NOT NULL, fee REAL NOT NULL, entry_quote TEXT NOT NULL, last_quote TEXT NOT NULL, state TEXT NOT NULL, exit REAL, pnl TEXT, reason TEXT)')
        self.connection.execute('CREATE TABLE IF NOT EXISTS events (intent TEXT PRIMARY KEY,pair TEXT NOT NULL,ts REAL NOT NULL,status TEXT NOT NULL,reason TEXT)')
        self.connection.execute('CREATE TABLE IF NOT EXISTS runtime (id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL)')
        initial=str(Decimal(str(initial)).quantize(Decimal('.01')))
        self.connection.execute('INSERT OR IGNORE INTO account VALUES (1,?,?,?)',(self.VERSION,initial,initial))
        row=self.connection.execute('SELECT * FROM account WHERE id=1').fetchone()
        if row['version']!=self.VERSION or row['initial']!=initial:
            self.connection.close()
            raise ValueError('existing_account_contract_mismatch')

    def close(self): self.connection.close()

    def open(self,intent,pair,side,quote,now,stop,target,*,minimum,step,maximum,
             quote_currency,fee_per_unit=0):
        validate_quote(quote,now)
        if side not in (-1,1) or not intent or not pair: raise ValueError('invalid_intent')
        entry=quote['ask'] if side==1 else quote['bid']
        exit_side=quote['bid'] if side==1 else quote['ask']
        if not all(math.isfinite(v) and v>0 for v in (stop,target)):
            raise ValueError('invalid_levels')
        if side*(exit_side-stop)<=0 or side*(target-entry)<=0:
            raise ValueError('invalid_stop_target_geometry')
        risk=side*(entry-stop)
        self.connection.execute('BEGIN IMMEDIATE')
        try:
            existing=self.connection.execute('SELECT id FROM positions WHERE intent=?',(intent,)).fetchone()
            if existing:
                self.connection.execute('COMMIT')
                return dict(status='already_recorded',id=existing['id'])
            if self.connection.execute("SELECT 1 FROM positions WHERE state='open'").fetchone():
                self.connection.execute('COMMIT')
                return dict(status='skipped',reason='one_open_position')
            balance=Decimal(self.connection.execute('SELECT balance FROM account WHERE id=1').fetchone()[0])
            units=0 if balance<=0 else size_position(float(balance),entry,risk,fee_per_unit,
                minimum=minimum,step=step,maximum=maximum,quote_currency=quote_currency)
            if not units:
                self.connection.execute('COMMIT')
                return dict(status='skipped',reason='insufficient_capital_or_minimum_size')
            encoded=json.dumps(dict(quote,executed_ts=now),sort_keys=True)
            cursor=self.connection.execute("INSERT INTO positions (intent,pair,side,entry,stop,target,units,fee,entry_quote,last_quote,state) VALUES (?,?,?,?,?,?,?,?,?,?,'open')",
                (intent,pair,side,entry,stop,target,units,fee_per_unit,encoded,encoded))
            identifier=cursor.lastrowid
            self.connection.execute('COMMIT')
            return dict(status='open',id=identifier,entry=entry,units=units,stop=stop,target=target)
        except Exception:
            self.connection.execute('ROLLBACK')
            raise

    def active(self):
        row=self.connection.execute("SELECT * FROM positions WHERE state='open'").fetchone()
        return dict(row) if row else None

    def event(self,intent,pair,ts,status,reason=None):
        self.connection.execute('INSERT OR IGNORE INTO events VALUES (?,?,?,?,?)',(intent,pair,ts,status,reason))

    def mark_gap(self,reason='path_gap'):
        self.connection.execute("UPDATE positions SET reason=? WHERE state='open'",(reason,))

    def heartbeat(self,payload):
        self.connection.execute('INSERT OR REPLACE INTO runtime VALUES (1,?)',(json.dumps(payload,sort_keys=True),))

    def observe(self,pair,quote,now,*,force_reason=None):
        self.connection.execute('BEGIN IMMEDIATE')
        try:
            position=self.connection.execute("SELECT * FROM positions WHERE pair=? AND state='open'",(pair,)).fetchone()
            if not position:
                self.connection.execute('COMMIT')
                return dict(status='no_open_position')
            validate_quote(quote,now,position['side'])
            if position['reason']=='path_gap':
                self.connection.execute('COMMIT')
                return dict(status='suspended',reason='path_gap')
            last=json.loads(position['last_quote'])
            time_key='bid_ts' if position['side']==1 else 'ask_ts'
            entered=json.loads(position['entry_quote'])
            if quote[time_key]<entered.get('executed_ts',entered['ts']) or quote[time_key]<last[time_key] or (quote==last and not force_reason):
                self.connection.execute('COMMIT')
                return dict(status='ignored_old_or_duplicate_quote')
            side=position['side']
            price=quote['bid'] if side==1 else quote['ask']
            stopped=side*(price-position['stop'])<=0
            targeted=side*(price-position['target'])>=0
            encoded=json.dumps(quote,sort_keys=True)
            if not stopped and not targeted and not force_reason:
                self.connection.execute('UPDATE positions SET last_quote=? WHERE id=?',(encoded,position['id']))
                self.connection.execute('COMMIT')
                return dict(status='open',id=position['id'])
            exit_=price if stopped or (force_reason and not targeted) else position['target']
            pnl=net_usd(position['units'],side*(exit_-position['entry']),position['fee'])
            balance=Decimal(self.connection.execute('SELECT balance FROM account WHERE id=1').fetchone()[0])+pnl
            reason='stop' if stopped else 'target' if targeted else force_reason
            self.connection.execute("UPDATE positions SET state='closed',exit=?,pnl=?,reason=?,last_quote=? WHERE id=? AND state='open'",
                                    (exit_,str(pnl),reason,encoded,position['id']))
            self.connection.execute('UPDATE account SET balance=? WHERE id=1',(str(balance),))
            self.connection.execute('COMMIT')
            return dict(status='closed',id=position['id'],exit=exit_,reason=reason,pnl_usd=str(pnl),balance_usd=str(balance))
        except Exception:
            self.connection.execute('ROLLBACK')
            raise

    def status(self,now=None):
        self.connection.execute('BEGIN')
        try:
            account=dict(self.connection.execute('SELECT * FROM account WHERE id=1').fetchone())
            positions=[dict(r) for r in self.connection.execute('SELECT * FROM positions ORDER BY id')]
            self.connection.execute('COMMIT')
        except Exception:
            self.connection.execute('ROLLBACK')
            raise
        unrealized=Decimal('0.00')
        fresh=True
        for position in positions:
            if position['state']!='open': continue
            quote=json.loads(position['last_quote'])
            price=quote['bid'] if position['side']==1 else quote['ask']
            unrealized+=net_usd(position['units'],position['side']*(price-position['entry']),position['fee'])
            if now is None or not all(0<=now-quote[k]<=5 for k in ('bid_ts','ask_ts')):
                fresh=False
        account.update(positions=positions,real_orders=False,marks_fresh=fresh,
                       unrealized_usd=str(unrealized) if fresh else None,
                       equity_usd=str(Decimal(account['balance'])+unrealized) if fresh else None,
                       quote_sampling='observed_quotes_not_guaranteed_broker_fills')
        return account
