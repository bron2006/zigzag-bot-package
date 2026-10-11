"""Restore explicitly requested crypto favorites via the running API.

No orders, no toggling scanners, no credentials in URLs/logs. Repeated runs
are safe: desired-state additions, not toggles. Must run in the Fly container.
"""
import json
import logging
import sys
from pathlib import Path

logging.disable(logging.CRITICAL)
import config
import requests
import psycopg2


def main():
    assert config.get_chat_id() == config.DEV_USER_ID, 'Owner/scanner identity mismatch; nothing changed'
    assert not config.AUTOTRADE_ENABLED and not config.BINOMO_EXECUTOR_ENABLED, 'Execution must remain disabled'
    token = config.get_admin_access_token()
    assert token, 'Owner authentication unavailable'
    crypto = {config.normalize_symbol_key(p) for p in config.CRYPTO_PAIRS}
    conn = psycopg2.connect(config.get_database_url().replace('postgresql+psycopg2:', 'postgresql:'),
                           connect_timeout=8, options='-c statement_timeout=8000')
    conn.set_session(readonly=True, autocommit=True)
    with conn.cursor() as cursor:
        cursor.execute('SELECT pair FROM user_watchlist WHERE user_id=%s', (config.DEV_USER_ID,))
        before = {row[0] for row in cursor.fetchall()}
    if '--apply' in sys.argv:
        response = requests.post('http://127.0.0.1:8080/api/watchlist',
                                 data=[('admin_token', token), ('enabled', 'true')] + [('pair', p) for p in sorted(crypto)],
                                 timeout=(5, 20))
        assert response.status_code == 200, f'Update failed HTTP {response.status_code}'
        payload = response.json()
        assert payload.get('success') and crypto <= set(payload['watchlist'])
    with conn.cursor() as cursor:
        cursor.execute('SELECT pair FROM user_watchlist WHERE user_id=%s', (config.DEV_USER_ID,))
        after = {row[0] for row in cursor.fetchall()}
        cursor.execute("SELECT key,value FROM app_runtime_settings WHERE key LIKE 'scanner_state_%'")
        states = dict(cursor.fetchall())
    conn.close()
    assert before <= after, 'Existing favorites were not preserved'
    if '--apply' in sys.argv:
        assert crypto <= after, 'Crypto did not persist'
    print(json.dumps(dict(before=len(before), after=len(after), crypto=len(after & crypto),
                          configured_crypto=len(crypto), scanner_states=states,
                          autotrade=False, executors=False,
                          new_api_in_source='def set_watchlist():' in Path('/app/api.py').read_text()), sort_keys=True))


if __name__ == '__main__':
    main()
