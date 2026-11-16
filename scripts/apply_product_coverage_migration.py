"""One additive migration using existing credentials; no resets or collection."""
import json
import os
from pathlib import Path
import psycopg
from veriflow.db import connection_settings, connect


def main():
    with connect() as app:
        if app.execute("SELECT to_regclass('veriflow.product_evidence') IS NOT NULL AS present").fetchone()['present']:
            print(json.dumps({'migration':'already_applied'}))
            return 0
    settings = connection_settings()
    password = os.environ.get('VERIFLOW_RESET_POSTGRES_PASSWORD')
    if not password:
        print(json.dumps({'migration':'blocked','reason':'existing_administrator_secret_unavailable'}))
        return 2
    settings.update(user='postgres.qrejfpeclncrevmepgzx',password=password)
    try:
        with psycopg.connect(**settings,connect_timeout=10) as conn:
            conn.execute("SET LOCAL lock_timeout='5s'")
            conn.execute("SET LOCAL statement_timeout='30s'")
            sql = Path('supabase/migrations/20261115180000_product_coverage_strategy.sql').read_text()
            conn.execute(sql)
        print(json.dumps({'migration':'applied','credentials_changed':False,
                          'existing_reviews_changed':False,'existing_jobs_changed':False}))
        return 0
    except Exception as exc:
        print(json.dumps({'migration':'failed','error_type':type(exc).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
