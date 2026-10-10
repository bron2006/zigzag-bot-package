"""Run read-only checks plus an explicitly ROLLED BACK journal roundtrip on Fly.

Never prints credentials or changes runtime trading settings. No broker calls.
"""
import json
import logging
import os
import hashlib
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

logging.disable(logging.CRITICAL)
import config
import db
from sqlalchemy import text
from sqlalchemy.orm import scoped_session, sessionmaker

result = {"autotrade_enabled": bool(config.AUTOTRADE_ENABLED)}
with db.engine.connect() as conn:
    role = conn.execute(text("SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user")).scalar_one()
    result["backend_bypasses_rls"] = bool(role)
    result["source_hashes"] = {name: hashlib.sha256(Path('/app', name).read_bytes()).hexdigest()
                               for name in ('app.py','db.py','scanner.py','state.py','signal_tracking.py',
                                            'endpoint_sampler.py','signal_accounting.py','measurement_health.py','webapp/script.js')}
    conn.rollback()
    transaction = conn.begin()
    try:
        row_id = conn.execute(text("INSERT INTO signal_outcomes (pair,timeframe,verdict,score,entry_price,horizon_seconds,outcome) VALUES ('__AUDIT_PROBE__','1m','BUY',0,100,300,'pending') RETURNING id")).scalar_one()
        payload = json.dumps({"version":"live_mid_v1","entry_quote":{"mid":100},"endpoint":{"mid":101}})
        conn.execute(text("INSERT INTO signal_evidence (signal_id,payload) VALUES (:id,:payload)"), dict(id=row_id,payload=payload))
        readback = conn.execute(text("SELECT payload FROM signal_evidence WHERE signal_id=:id"),dict(id=row_id)).scalar_one()
        assert json.loads(readback)["endpoint"]["mid"] == 101
        result["journal_roundtrip"] = "passed_then_rolled_back"
    finally:
        transaction.rollback()
    result["probe_removed"] = not conn.execute(text("SELECT EXISTS (SELECT 1 FROM signal_outcomes WHERE id=:id)"),dict(id=row_id)).scalar_one()

# Exercise the real resolver and accounting against PostgreSQL using savepoints
# joined to ONE outer transaction. Even inner session commits cannot publish
# these synthetic rows: the outer transaction is rolled back below.
import signal_tracking
import signal_accounting
import endpoint_sampler
from state import AppState
conn = db.engine.connect()
outer = conn.begin()
old_sessions = db.SessionLocal
joined_sessions = scoped_session(sessionmaker(bind=conn, expire_on_commit=False,
                                             join_transaction_mode="create_savepoint"))
db.SessionLocal = joined_sessions
probe_ids = []
try:
    state = AppState.__new__(AppState)
    state._state_lock = threading.RLock()
    state.live_prices = {}
    state._outcome_quotes = {}
    state._outcome_quote_sides = {}
    entry = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=306)
    deadline = entry.replace(tzinfo=timezone.utc).timestamp() + 300
    for status, exit_ in (("win",101),("loss",99),("refund",100),("unknown",None)):
        pair = "__RELEASE_" + status.upper() + "__"
        id_ = db.create_signal_outcome(pair=pair,timeframe="1m",verdict="BUY",score=20,
                                      entry_price=100,horizon_seconds=300,entry_ts=entry,
                                      evidence=dict(version="live_mid_v1",entry_quote=dict(mid=100)))
        assert id_ is not None
        probe_ids.append(id_)
        if exit_ is not None:
            state.update_live_price(pair,dict(quote_ts=deadline+0.5,bid=exit_-0.1,ask=exit_+0.1))
    actual_pending = db.get_pending_signal_outcomes
    with patch.object(signal_tracking,"app_state",state), \
         patch.object(endpoint_sampler,"register"), \
         patch.object(db,"get_pending_signal_outcomes",side_effect=lambda: [r for r in actual_pending() if r["id"] in probe_ids]):
        signal_tracking.resolve_pending_signals()
    with db.get_db() as session:
        rows = session.query(db.SignalOutcome).filter(db.SignalOutcome.id.in_(probe_ids)).all()
        evidence = {r.signal_id:json.loads(r.payload) for r in session.query(db.SignalEvidence).filter(db.SignalEvidence.signal_id.in_(probe_ids)).all()}
        stats = signal_accounting.summarize(rows,evidence)
        assert stats["counts"] == dict(win=1,loss=1,refund=1,unknown=1), stats["counts"]
        assert stats["scenario"]["measured_balance"] == 998
        assert not stats["scenario"]["complete"]
        result["postgres_pipeline_test"] = dict(counts=stats["counts"],balance=998,complete=False)
finally:
    joined_sessions.remove()
    db.SessionLocal = old_sessions
    outer.rollback()
    conn.close()
with db.get_db() as session:
    result["pipeline_probes_removed"] = session.query(db.SignalOutcome).filter(db.SignalOutcome.id.in_(probe_ids)).count() == 0
    assert result["pipeline_probes_removed"]

# Exercise deployed API handlers against the real database without sending the
# admin credential through a URL/access log or launching another trading bot.
from flask import Flask
import api
app = Flask("release-verification")
api.register_routes(app)
client = app.test_client()
response = client.get('/api/stats/signals', query_string={"days":30,"admin_token":config.get_admin_access_token()})
data = response.get_json()
assert response.status_code == 200 and data.get("ok") and data.get("success")
assert "measurement_audit" in data
result["stats_api"] = dict(status=response.status_code,total=data["total"],
                           new_cohort=data["measurement_audit"]["total"],
                           scenario=data["measurement_audit"]["scenario"],
                           pairs=len(data["by_pair"]))
print(json.dumps(result, sort_keys=True))
