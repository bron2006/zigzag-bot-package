"""Light resident HTTP evidence; no second app/models/DB or synthetic signals."""
import hashlib
import json
from pathlib import Path
import time
import config
import requests
from strategy_mode import legacy_enabled,paper_entries_enabled

assert not legacy_enabled() and not paper_entries_enabled()
assert not config.AUTOTRADE_ENABLED and not config.BINOMO_EXECUTOR_ENABLED
base='http://127.0.0.1:8080'
params=dict(admin_token=config.get_admin_access_token())
response=requests.get(base+'/api/stats/paper_stops',params=params,timeout=(5,20))
response.raise_for_status();paper=response.json();research=paper['forward_research']
assert paper['balance']==999.37 and not paper['open_positions'] and len(paper['closed_positions'])==1
assert research['status']=='collecting' and research['candles_fresh']
assert len(research['sources'])==4 and all(s['error'] is None for s in research['sources'])
assert all(0<=time.time()-s['checked']<180 for s in research['sources'])
assert not research['changes_account_balance'] and not research['real_orders']
assert research['mode']=='prospective_OHLC_observations_not_trade_execution'
assert not research['historical_FX_gate_passed'] and not research['crypto_extension_validated']
assert 'ny_h4_close_reclaim_v1' in research['rules'] and len(research['rules'])==4
assert research['rule_activations']['ny_h4_close_reclaim_v1']>=research['activated']
assert len(research['ny_h4_states'])==4
assert all(r['intent']['ts']>=research['rule_activations'][r['intent']['rule']] for r in research['recent'])
assert 'script.js?v=20261012-compact-dashboard' in requests.get(base+'/',timeout=(5,20)).text
flags=requests.post(base+'/api/scanner/toggle',data=params,timeout=(5,20))
flags.raise_for_status();assert not any(flags.json().values())
assert requests.get(base+'/api/stats/paper_stops',timeout=(5,20)).status_code==401
names=('app.py','api.py','forward_structure_research.py','price_structure_candidates.py','ny_h4_reclaim.py','webapp/script.js','webapp/index.html')
print(json.dumps(dict(verified_utc=time.time(),research=research,old_strategy=False,paper_entries=False,
                     balance=paper['balance'],scanners=flags.json(),real_orders=False,
                     hashes={name:hashlib.sha256(Path('/app',name).read_bytes()).hexdigest() for name in names}),sort_keys=True))
