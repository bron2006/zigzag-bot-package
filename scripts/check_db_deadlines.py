"""Read-only live probe in a killable child; never imports db/schema initialization."""
import ast
import json
from pathlib import Path
import subprocess
import sys
import time


def probe():
    from dotenv import dotenv_values
    from sqlalchemy import create_engine, event, text
    from sqlalchemy.exc import DBAPIError
    project = Path(__file__).resolve().parents[1]
    source = ast.parse((project / "db.py").read_text(encoding="utf-8-sig"))
    functions = [n for n in source.body if isinstance(n, ast.FunctionDef)
                 and n.name in {"_is_sqlite_url", "_build_engine", "_set_transaction_deadlines"}]
    namespace = {"create_engine": create_engine, "event": event}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "db-engine-probe", "exec"), namespace)
    url = dotenv_values(project / ".env").get("DATABASE_URL")
    if not url:
        print(json.dumps({"ok": False, "error": "DATABASE_URL_missing"}))
        return 1
    engine = namespace["_build_engine"](url)
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            assert connection.execute(text("SELECT 1")).scalar() == 1
            statement_limit = connection.execute(text("SHOW statement_timeout")).scalar()
            lock_limit = connection.execute(text("SHOW lock_timeout")).scalar()
            started = time.monotonic()
            try:
                connection.execute(text("SELECT pg_sleep(9)"))
            except DBAPIError:
                elapsed = time.monotonic() - started
                connection.rollback()
                ok = 6 <= elapsed <= 11
                print(json.dumps({"ok": ok, "select_1": True,
                                  "statement_timeout": statement_limit, "lock_timeout": lock_limit,
                                  "sleep_cancelled_seconds": round(elapsed, 2)}))
                return 0 if ok else 1
            print(json.dumps({"ok": False, "error": "statement_deadline_not_enforced",
                              "statement_timeout": statement_limit, "lock_timeout": lock_limit}))
            return 1
    except Exception as error:
        print(json.dumps({"ok": False, "error": type(error).__name__}))
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    if "--worker" in sys.argv:
        try:
            exit_code = probe()
        except Exception as error:
            print(json.dumps({"ok": False, "error": type(error).__name__}))
            exit_code = 1
        sys.exit(exit_code)
    try:
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker"],
                                capture_output=True, text=True, timeout=25)
    except subprocess.TimeoutExpired:
        print('{"ok": false, "error": "probe_exceeded_25_seconds_child_killed"}')
        sys.exit(1)
    # Only publish our JSON, never a traceback containing a connection URL.
    for line in result.stdout.splitlines():
        if line.startswith("{"):
            print(line)
    if not result.stdout.strip():
        print('{"ok": false, "error": "probe_failed_without_safe_result"}')
    sys.exit(result.returncode)
