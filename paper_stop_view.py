"""Read-only bounded view of an existing LOCAL paper journal; never creates one."""
import json
import math
from pathlib import Path
import sqlite3
from urllib.parse import quote
from decimal import Decimal


def snapshot(path,now,quotes=None,*,before=None):
    if not path:
        return dict(ok=True,status='not_started',planned_initial=1000,balance=None,equity=None,
                    unrealized=None,open_positions=[],closed_positions=[],by_pair=[],real_orders=False)
    if not Path(path).is_file():
        raise FileNotFoundError('configured_paper_journal_missing')
    uri='file:'+quote(Path(path).resolve().as_posix(),safe='/:')+'?mode=ro'
    connection=sqlite3.connect(uri,uri=True,timeout=5,isolation_level=None)
    connection.row_factory=sqlite3.Row
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        account=connection.execute('SELECT * FROM account WHERE id=1').fetchone()
        if not account or account['version']!='local-paper-stops-v1':
            raise ValueError('paper_account_contract_mismatch')
        rows=[dict(r) for r in connection.execute("SELECT * FROM positions WHERE state='open' ORDER BY id")]
        closed_rows=[dict(r) for r in connection.execute(
            "SELECT * FROM positions WHERE state='closed'"+(' AND id<?' if before else '')+" ORDER BY id DESC LIMIT 100",(before,) if before else ())]
        rows+=closed_rows
        groups=[dict(r) for r in connection.execute("SELECT pair,count(*) total,sum(state='open') opened,sum(state='closed') closed,sum(CASE WHEN state='closed' THEN CAST(pnl AS REAL) ELSE 0 END) pnl FROM positions GROUP BY pair ORDER BY pair")]
        tables={r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        runtime_row=connection.execute('SELECT payload FROM runtime WHERE id=1').fetchone() if 'runtime' in tables else None
        runtime=json.loads(runtime_row[0]) if runtime_row else None
        skipped=[dict(r) for r in connection.execute("SELECT reason,count(*) total FROM events WHERE status='skipped' GROUP BY reason ORDER BY total DESC")] if 'events' in tables else []
        connection.execute('COMMIT')
    finally:
        connection.close()
    balance=float(account['balance'])
    if not math.isfinite(balance): raise ValueError('invalid_paper_balance')
    opened,closed=[],[]
    unrealized=Decimal('0.00')
    fresh=True
    for row in rows:
        last=((quotes or {}).get(row['pair']) if row['state']=='open' else None) or json.loads(row['last_quote'])
        key='bid_ts' if row['side']==1 else 'ask_ts'
        valid=isinstance(last.get(key),(int,float)) and math.isfinite(last[key]) and 0<=now-last[key]<=5 and last.get('bid',0)>0 and last.get('ask',0)>0 and row['reason']!='path_gap'
        view={k:row[k] for k in ('id','pair','side','entry','stop','target','units','state','exit','reason')}
        entry_quote=json.loads(row['entry_quote'])
        view.update(entry_ts=entry_quote.get('executed_ts',entry_quote['ts']),exit_ts=last[key] if row['state']=='closed' else None,
                    pnl=float(row['pnl']) if row['pnl'] is not None else None,
                    fee_usd=float(Decimal(str(row['units']))*Decimal(str(row['fee']))))
        if row['state']=='open':
            price=last['bid'] if row['side']==1 else last['ask']
            floating=(Decimal(str(row['units']))*(Decimal(str(row['side']*(price-row['entry'])))-Decimal(str(row['fee'])))).quantize(Decimal('.01'))
            view.update(current=price if valid else None,pnl=float(floating) if valid else None,quote_ts=last['ts'],quote_fresh=valid)
            unrealized+=floating
            fresh=fresh and valid
            opened.append(view)
        else:
            closed.append(view)
    if runtime and (not isinstance(runtime.get('heartbeat'),(int,float)) or not 0<=now-runtime['heartbeat']<10):
        runtime['status']='not_ready'
    return dict(ok=True,status='account_available',initial=float(account['initial']),balance=balance,
                equity=balance+float(unrealized) if fresh else None,unrealized=float(unrealized) if fresh else None,
                open_positions=opened,closed_positions=closed,by_pair=groups,marks_fresh=fresh,
                real_orders=False,history_limit=100,sampled_quotes=True,
                runtime=runtime,skipped=skipped,
                next_before=closed_rows[-1]['id'] if len(closed_rows)==100 else None)
