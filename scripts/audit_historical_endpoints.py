"""Read-only by default. --recover writes only validated unknown endpoints."""
import json
import logging
import sys
import time
logging.disable(logging.CRITICAL)
import config
import requests

assert not config.AUTOTRADE_ENABLED and not config.BINOMO_EXECUTOR_ENABLED
recover = '--recover' in sys.argv
entry = '--entry' in sys.argv
assert not (recover and entry), 'Entry audits are read-only'
ids = [int(x) for x in sys.argv[1:] if x not in ('--recover', '--entry')]
assert 1 <= len(ids) <= 500
for identifier in ids:
    for attempt in range(5):
        response = requests.post('http://127.0.0.1:8080/api/admin/endpoint-audit',
                                 data=dict(admin_token=config.get_admin_access_token(), id=identifier,
                                           phase='entry' if entry else 'expiry'), timeout=(5, 20))
        if response.status_code != 503:
            break
        time.sleep(3)
    if response.status_code != 200:
        print(json.dumps(dict(id=identifier, status=response.status_code)), flush=True)
        continue
    data = response.json()
    history = data['history']
    saved, quote = data['saved'], history['endpoint']
    result = dict(id=identifier, pair=data['pair'], status=data['outcome'], counts=history['counts'],
                  historical=quote, saved=saved,
                  saved_match=(all(abs(saved[k] - quote[k]) < 1e-8 for k in ('ts', 'bid', 'ask', 'mid'))
                               if saved and quote else None))
    if recover and data['outcome'] == 'unknown':
        import db
        result['recovered'] = db.recover_signal_endpoint(identifier, history) if quote else False
        if not quote:
            result['history_check_saved'] = db.record_signal_history_check(identifier, history)
    print(json.dumps(result), flush=True)
    time.sleep(1.1)
