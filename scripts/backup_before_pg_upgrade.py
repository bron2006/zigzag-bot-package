"""Create and read-validate a private logical backup; never print credentials.

Uses an official PostgreSQL 17 client provided by --client-dir. Does not import
db.py, mutate the database, or restore anything into production.
"""
import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

import psycopg2
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

PROJECT = 'nrozqijadhvmgvhzmxqm'
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--client-dir', required=True)
    parser.add_argument('--destination', required=True)
    args = parser.parse_args()
    client = Path(args.client_dir).resolve()
    destination = Path(args.destination).resolve()
    raw_url = dotenv_values(ROOT / '.env').get('DATABASE_URL')
    if not raw_url:
        raise SystemExit('No local database connection configured; nothing changed.')
    url = make_url(raw_url)
    if PROJECT not in (url.host or '') and PROJECT not in (url.username or ''):
        raise SystemExit('Database project does not match; nothing changed.')
    env = dict(os.environ, PGHOST=url.host, PGPORT=str(url.port or 5432),
               PGDATABASE=url.database or 'postgres', PGUSER=url.username or '',
               PGPASSWORD=url.password or '', PGCONNECT_TIMEOUT='8',
               PGSSLMODE=str(url.query.get('sslmode', 'require')))
    # Preflight validates the exact target without printing connection details.
    try:
        connection = psycopg2.connect(host=env['PGHOST'], port=env['PGPORT'],
                                     dbname=env['PGDATABASE'], user=env['PGUSER'],
                                     password=env['PGPASSWORD'], sslmode=env['PGSSLMODE'],
                                     connect_timeout=8, options='-c statement_timeout=8000')
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_setting('server_version'), pg_database_size(current_database())")
                version, size = cursor.fetchone()
                cursor.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public'")
                tables = cursor.fetchone()[0]
        finally:
            connection.close()
    except Exception:
        raise SystemExit('Database preflight failed; no upgrade or backup attempted.') from None
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / 'before-postgres-upgrade.dump'
    if archive.exists():
        raise SystemExit('Backup already exists; refusing to overwrite it.')
    command = [str(client / 'pg_dump.exe'), '--format=custom', '--no-owner', '--no-acl',
               '--lock-wait-timeout=8s', '--file', str(archive)]
    result = subprocess.run(command, env=env, capture_output=True, timeout=180)
    if result.returncode:
        raise SystemExit('Logical backup failed; partial archive must not be used for upgrade.')
    listing = subprocess.run([str(client / 'pg_restore.exe'), '--list', str(archive)],
                             capture_output=True, timeout=30)
    scan = subprocess.run([str(client / 'pg_restore.exe'), '--file=NUL', str(archive)],
                          capture_output=True, timeout=90)
    if listing.returncode or scan.returncode:
        raise SystemExit('Backup read validation failed; do not upgrade.')
    listing_text = listing.stdout.decode('utf-8', errors='replace')
    public_tables = sum(' TABLE public ' in line for line in listing_text.splitlines())
    if public_tables != tables:
        raise SystemExit('Backup table count mismatch; do not upgrade.')
    print(json.dumps(dict(project=PROJECT, server_version=version, database_bytes=size,
                          public_tables=tables, backup_bytes=archive.stat().st_size,
                          sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                          archive_read_validation='passed', restore_executed=False)))


if __name__ == '__main__':
    main()
