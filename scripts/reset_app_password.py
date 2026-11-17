"""One-time server-only maintenance; no web route and no secret output."""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import psycopg
from psycopg import sql
from psycopg.rows import dict_row

PROJECT='qrejfpeclncrevmepgzx'
HOST='aws-1-us-west-2.pooler.supabase.com'
ROLE='veriflow_app'


def reset_role_password(conn,password):
    if not re.fullmatch(r'[A-Za-z0-9]{32,128}',password or ''):
        raise ValueError('Use a password-manager password of 32-128 ASCII letters and digits')
    role=conn.execute('''SELECT rolcanlogin,rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,
        pg_has_role('veriflow_app','veriflow_runtime','MEMBER') AS runtime_member
        FROM pg_roles WHERE rolname='veriflow_app' ''').fetchone()
    if not role or not role['rolcanlogin'] or not role['runtime_member'] or any(role[k] for k in ('rolsuper','rolbypassrls','rolcreaterole','rolcreatedb')):
        raise ValueError('Unexpected application role; no changes made')
    # Like psql's password command: encrypt locally; never put plaintext in SQL.
    verifier=conn.pgconn.encrypt_password(password.encode(),ROLE.encode(),b'scram-sha-256').decode()
    conn.execute(sql.SQL('ALTER ROLE veriflow_app PASSWORD {}').format(sql.Literal(verifier)))


def main():
    password=os.environ.get('VERIFLOW_APP_PASSWORD','')
    admin_password=os.environ.get('VERIFLOW_RESET_POSTGRES_PASSWORD','')
    if not password or not admin_password or os.environ.get('VERIFLOW_RESET_CONFIRM')!=PROJECT+':'+ROLE:
        print(json.dumps({'status':'blocked','code':'maintenance_secrets_or_confirmation_missing'}))
        return 1
    settings=dict(host=HOST,port=5432,dbname='postgres',sslmode='verify-full',
                  sslrootcert='system',connect_timeout=10)
    committed=False
    try:
        with psycopg.connect(**settings,user='postgres.'+PROJECT,password=admin_password,row_factory=dict_row) as conn:
            if not conn.pgconn.ssl_in_use or conn.execute('SELECT current_user AS role').fetchone()['role']!='postgres':
                raise ValueError('Require verified project administrator connection')
            reset_role_password(conn,password)
        committed=True
        with psycopg.connect(**settings,user=ROLE+'.'+PROJECT,password=password,row_factory=dict_row) as app:
            from veriflow.health import database_health
            health=database_health(app)
        print(json.dumps({'password_updated':True,'role':ROLE,'healthy':health['healthy'],
                          'sources':health['sources'],'tls':health['tls'],
                          'application_role':health['application_role']}))
        return 0 if health['healthy'] else 1
    except Exception:
        # No SQL text, DSN, passwords, SCRAM verifier or provider payloads.
        print(json.dumps({'status':'error','code':'reset_or_verification_failed',
                          'password_change':'committed' if committed else 'unconfirmed',
                          'role':ROLE}))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
