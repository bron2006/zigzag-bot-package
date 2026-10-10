"""One-off post-upgrade maintenance for the verified ZigZag database.

Rebuild indexes before acknowledging changed collation rules. No data deletion,
credential output, schema grants, or application configuration changes.
"""
import json
from pathlib import Path

import psycopg2
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
PROJECT = 'nrozqijadhvmgvhzmxqm'


def main():
    url = make_url(dotenv_values(ROOT / '.env')['DATABASE_URL'])
    if PROJECT not in (url.host or '') and PROJECT not in (url.username or ''):
        raise SystemExit('Wrong project; nothing changed.')
    conn = psycopg2.connect(host=url.host, port=url.port or 5432,
                           dbname=url.database, user=url.username, password=url.password,
                           sslmode=url.query.get('sslmode', 'require'), connect_timeout=8,
                           application_name='zigzag_post_upgrade_collation_repair')
    conn.autocommit = True  # Concurrent reindex cannot run in a transaction.
    try:
        with conn.cursor() as cursor:
            cursor.execute("SET statement_timeout='90s'")
            cursor.execute("SET lock_timeout='5s'")
            cursor.execute("SELECT current_database(), current_setting('server_version'), "
                           "datcollversion, pg_database_collation_actual_version(oid), "
                           "pg_get_userbyid(datdba)=current_user FROM pg_database "
                           "WHERE datname=current_database()")
            name, version, recorded, actual, owner = cursor.fetchone()
            if name != 'postgres' or not version.startswith('17.11') or not owner:
                raise SystemExit('Unexpected database/version/owner; nothing changed.')
            if recorded == actual:
                print(json.dumps(dict(status='already_current', version=actual)))
                return
            cursor.execute("SELECT count(*) FROM pg_index JOIN pg_class "
                           "ON pg_class.oid=indrelid JOIN pg_namespace "
                           "ON pg_namespace.oid=relnamespace WHERE nspname "
                           "NOT IN ('pg_catalog','information_schema') "
                           "AND (NOT indisvalid OR indisexclusion)")
            if cursor.fetchone()[0]:
                raise SystemExit('Invalid/exclusion indexes need manual handling; nothing changed.')
            conn.notices.clear()
            cursor.execute('REINDEX DATABASE CONCURRENTLY postgres')
            if any('WARNING:' in notice or 'skipping' in notice.lower() for notice in conn.notices):
                raise SystemExit('Reindex produced warnings; collation version NOT refreshed.')
            cursor.execute("SELECT count(*) FROM pg_index WHERE NOT indisvalid")
            if cursor.fetchone()[0]:
                raise SystemExit('Invalid indexes after rebuild; collation version NOT refreshed.')
            cursor.execute('ALTER DATABASE postgres REFRESH COLLATION VERSION')
            cursor.execute("SELECT datcollversion, pg_database_collation_actual_version(oid) "
                           "FROM pg_database WHERE datname=current_database()")
            new_recorded, new_actual = cursor.fetchone()
            assert new_recorded == new_actual
            print(json.dumps(dict(status='reindexed_and_refreshed', before=recorded,
                                  after=new_recorded, invalid_indexes=0)))
    finally:
        conn.close()


if __name__ == '__main__':
    main()
