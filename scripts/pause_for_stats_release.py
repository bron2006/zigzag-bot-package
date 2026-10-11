"""Scoped maintenance pause; leaves quote capture/resolution and orders unchanged."""
import json
import logging
import sys
logging.disable(logging.CRITICAL)
import config
import requests

assert not config.AUTOTRADE_ENABLED and not config.BINOMO_EXECUTOR_ENABLED
assert config.get_chat_id() == config.DEV_USER_ID
token = config.get_admin_access_token()
assert token
url = 'http://127.0.0.1:8080/api/scanner/toggle'

def state(category=None):
    body = {'admin_token': token}
    if category:
        body['category'] = category
    response = requests.post(url, data=body, timeout=(5, 15))
    assert response.status_code == 200, response.status_code
    return response.json()

original = dict(forex=False, crypto=False, commodities=True, watchlist=True)
paused = dict.fromkeys(original, False)
before = state()
mode = sys.argv[-1]
expected, desired = (original, paused) if mode == '--pause' else (paused, original)
assert mode in ('--pause', '--resume')
assert before in (expected, desired), 'Settings changed unexpectedly; nothing toggled'
current = before
for category in desired:
    if current[category] != desired[category]:
        current = state(category)
assert current == desired
print(json.dumps(dict(mode=mode, before=before, after=current), sort_keys=True))
