"""Bounded READ ONLY snapshot, no db/config/application imports or writes."""
import ast
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def worker():
    from dotenv import dotenv_values
    from sqlalchemy import create_engine, event, text
    source = ast.parse((ROOT/'db.py').read_text(encoding='utf-8-sig'))
    functions = [node for node in source.body if isinstance(node, ast.FunctionDef)
                 and node.name in {'_is_sqlite_url', '_build_engine', '_set_transaction_deadlines'}]
    namespace = dict(create_engine=create_engine, event=event)
    exec(compile(ast.Module(body=functions, type_ignores=[]), 'read-engine', 'exec'), namespace)
    env = dotenv_values(ROOT/'.env')
    url = env.get('DATABASE_URL')
    if not url or not url.startswith(('postgresql:', 'postgresql+psycopg2:')):
        raise ValueError('Postgres configuration absent; no fallback')
    engine = namespace['_build_engine'](url)
    try:
        with engine.connect() as conn:
            conn.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
            now = conn.execute(text('SELECT CURRENT_TIMESTAMP')).scalar_one().astimezone(timezone.utc).replace(tzinfo=None)
            limits = dict(statement=conn.execute(text('SHOW statement_timeout')).scalar_one(),
                          lock=conn.execute(text('SHOW lock_timeout')).scalar_one(),
                          readonly=conn.execute(text('SHOW transaction_read_only')).scalar_one())
            assert limits['readonly'] == 'on'
            params = dict(since=now-timedelta(days=365), now=now, cap=50001)
            signals = [dict(r) for r in conn.execute(text('''SELECT id,pair,timeframe,verdict,score,
                entry_price,entry_ts,horizon_seconds,exit_price,resolved_at,outcome
                FROM signal_outcomes WHERE entry_ts >= :since AND entry_ts <= :now
                ORDER BY entry_ts,id LIMIT :cap'''), params).mappings()]
            trades = [dict(r) for r in conn.execute(text('''SELECT id,pair,direction,amount,entry_ts,
                account_mode,result,payout_amount,resolved_at,signal_outcome_id,
                requested_expiry_seconds,expiry_seconds,expiry_mismatch
                FROM binomo_trades WHERE entry_ts >= :since AND entry_ts <= :now
                ORDER BY entry_ts,id LIMIT :cap'''), params).mappings()]
            watchlist = []
            uid = env.get('DEV_USER_ID') or env.get('CHAT_ID')
            if uid:
                watchlist = list(conn.execute(text('SELECT pair FROM user_watchlist WHERE user_id = :uid ORDER BY pair'), {'uid': int(uid)}).scalars())
            conn.rollback()
        if len(signals) >= 50001 or len(trades) >= 50001:
            raise ValueError('Read cap reached, refuse incomplete report')
        out = dict(snapshot_utc=now.isoformat()+'Z', readonly=True, limits=limits,
                   signals=signals, binomo_trades=trades, owner_db_watchlist=watchlist)
        (HERE/'snapshot.json').write_text(json.dumps(out, default=lambda v: v.isoformat() if isinstance(v, datetime) else str(v), allow_nan=False), encoding='utf-8')
        print(json.dumps(dict(ok=True, snapshot_utc=out['snapshot_utc'], signals=len(signals), trades=len(trades), limits=limits)))
    finally:
        engine.dispose()


if __name__ == '__main__':
    if '--worker' in sys.argv:
        try:
            worker()
        except Exception as error:
            print(json.dumps(dict(ok=False, error_type=type(error).__name__)))
            sys.exit(1)
    else:
        try:
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker'], capture_output=True, text=True, timeout=50)
            for line in result.stdout.splitlines():
                if line.startswith('{'):
                    print(line)
            sys.exit(result.returncode)
        except subprocess.TimeoutExpired:
            print('{"ok":false,"error_type":"50_second_child_deadline"}')
            sys.exit(1)
