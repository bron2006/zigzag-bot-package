"""Light resident-HTTP verification, no second app/DB/model or fake positions."""
import hashlib
import json
import os
import time
from pathlib import Path
import config
import requests

assert not config.AUTOTRADE_ENABLED and not config.BINOMO_EXECUTOR_ENABLED
base='http://127.0.0.1:8080'
auth=dict(admin_token=config.get_admin_access_token())
def get(path,params):
    response=requests.get(base+path,params=params,timeout=(5,20))
    assert response.status_code==200,(path,response.status_code)
    return response
paper=get('/api/stats/paper_stops',auth).json()
assert paper['ok'] and paper['real_orders'] is False
if paper['status']=='not_started':
    assert paper['balance'] is None and paper['equity'] is None
    assert not paper['open_positions'] and not paper['closed_positions']
else:
    assert paper['status']=='account_available' and paper['initial']==1000
    assert paper['runtime']['status'] in ('running','suspended_path_gap')
    assert time.time()-paper['runtime']['heartbeat']<10
    assert os.path.ismount('/data')
    assert os.getenv('PAPER_STOP_JOURNAL_PATH')=='/data/paper_stops_v1.sqlite3'
    assert paper['runtime']['real_orders'] is False
    assert paper['runtime']['eligible_pairs'], 'No verified symbol sizing terms'
current=get('/api/stats/signals',dict(auth,scope='current_test',valuation='asof60')).json()
assert current['ok'] and current['measurement_audit']['valuation']=='asof60'
html=get('/',{}).text
js=get('/script.js',{}).text
assert 'script.js?v=20261012-paper-stops' in html
assert 'renderTradingDashboard' in js and 'Попередній тест напрямку' in js
assert requests.get(base+'/api/stats/paper_stops',timeout=(5,20)).status_code==401
quotes=get('/api/live_price',dict(auth,pairs='EURUSD',format='paper')).json()
assert quotes['success'] and quotes['sampled']
for quote in quotes['quotes'].values():
    assert quote['source']=='cTrader' and quote['bid']<=quote['ask']
    assert quote['ts']==max(quote['bid_ts'],quote['ask_ts'])
hashes={name:hashlib.sha256(Path('/app',name).read_bytes()).hexdigest()
        for name in ('api.py','app.py','scanner.py','state.py','paper_stop_view.py','paper_stop_runtime.py','paper_stop_journal.py','paper_cfd.py','webapp/script.js','webapp/index.html')}
print(json.dumps(dict(paper=paper,legacy_balance=current['measurement_audit']['scenario']['measured_balance'],
                      current_counts=current['measurement_audit']['counts'],quote_count=len(quotes['quotes']),
                      hashes=hashes,real_orders=False,api_status=200),sort_keys=True))
