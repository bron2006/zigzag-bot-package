"""Read-only current experiment/API verification. No synthetic signals or orders."""
import json
import logging
logging.disable(logging.CRITICAL)
import config
import requests

assert not config.AUTOTRADE_ENABLED and not config.BINOMO_EXECUTOR_ENABLED
def read(scope):
    params = {'scope':scope, 'days':30, 'admin_token':config.get_admin_access_token()}
    if scope == 'current_test':
        params['valuation']='asof60'
    response = requests.get('http://127.0.0.1:8080/api/stats/signals',
                            params=params, timeout=(5,20))
    assert response.status_code == 200
    return response.json()

current = read('current_test')
history = read('history')
assert current['ok'] and history['ok']
assert current['scope'] == 'current_test'
assert current['total'] == current['measurement_audit']['total']
assert current['measurement_audit']['valuation'] == 'asof60'
assert current['measurement_audit']['cohort'] == 'asof60_v1'
assert current['measurement_audit']['asof_comparison']['affects_balance'] is True
assert current['original_measurement_audit']['valuation'] == 'strict'
assert current['original_measurement_audit']['total'] == current['total']
print(json.dumps(dict(current_total=current['total'], counts=current['measurement_audit']['counts'],
                      publication_audit=current['measurement_audit'].get('publication_audit', {}),
                      asof_comparison=current['measurement_audit'].get('asof_comparison', {}),
                      scenario=current['measurement_audit']['scenario'],
                      original_counts=current['original_measurement_audit']['counts'],
                      start=current['test_started'], old_report_total=history['total'],
                      api_status=200, orders_enabled=False), sort_keys=True))
