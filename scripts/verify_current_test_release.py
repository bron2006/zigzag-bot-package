"""Read-only current experiment/API verification. No synthetic signals or orders."""
import json
import logging
logging.disable(logging.CRITICAL)
import config
import db
import api
from flask import Flask

assert not config.AUTOTRADE_ENABLED and not config.BINOMO_EXECUTOR_ENABLED
current = db.get_signal_outcome_stats(current_test=True)
history = db.get_signal_outcome_stats(30, historical_only=True)
assert current['ok'] and history['ok']
assert current['scope'] == 'current_test'
assert current['total'] == current['measurement_audit']['total']
app = Flask('current-test-read-verification')
api.register_routes(app)
response = app.test_client().get('/api/stats/signals', query_string={
    'scope':'current_test', 'admin_token':config.get_admin_access_token()})
assert response.status_code == 200 and response.json['scope'] == 'current_test'
assert response.json['total'] == current['total']
print(json.dumps(dict(current_total=current['total'], counts=current['measurement_audit']['counts'],
                      publication_audit=current['measurement_audit'].get('publication_audit', {}),
                      scenario=current['measurement_audit']['scenario'],
                      start=current['test_started'], old_report_total=history['total'],
                      api_status=response.status_code, orders_enabled=False), sort_keys=True))
