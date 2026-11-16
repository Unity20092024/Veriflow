import os
import psycopg
from psycopg.rows import dict_row
from psycopg.conninfo import conninfo_to_dict
from .config import load_environment

PROJECT_REF = 'qrejfpeclncrevmepgzx'
POOLER_HOST = 'aws-1-us-west-2.pooler.supabase.com'


def connection_settings():
    """Accept only the existing project's app login, never a managed DB fallback."""
    load_environment()
    url = os.environ.get('SUPABASE_DATABASE_URL') or os.environ.get('DATABASE_URL')
    if not url:
        raise ValueError('Supabase connection secret is missing')
    config = conninfo_to_dict(url)
    # Keep the normal connection URL intact while using the dedicated app-role
    # password secret after a password rotation. Never log this parsed config.
    app_password = os.environ.get('VERIFLOW_APP_PASSWORD')
    if app_password:
        config['password'] = app_password
    project = os.environ.get('SUPABASE_PROJECT_REF', PROJECT_REF)
    if project != PROJECT_REF:
        raise ValueError('Unexpected Supabase project')
    direct = (config.get('host') == f'db.{project}.supabase.co'
              and config.get('user') == 'veriflow_app')
    pooler = (config.get('host') == POOLER_HOST
              and config.get('user') == f'veriflow_app.{project}')
    if not (direct or pooler):
        raise ValueError('Require the existing Supabase project application login')
    if config.get('port', '5432') != '5432' or config.get('dbname') != 'postgres':
        raise ValueError('Require the official PostgreSQL session endpoint')
    if config.get('sslmode') != 'verify-full':
        raise ValueError('Require certificate and hostname verification')
    # Do not allow a URI to redirect libpq around the validated target.
    if config.get('hostaddr') or config.get('service'):
        raise ValueError('Connection target overrides are not allowed')
    root_cert = os.environ.get('SUPABASE_SSL_ROOT_CERT')
    if root_cert:
        config['sslrootcert'] = root_cert
    config.setdefault('sslrootcert', 'system')
    return config


def connect():
    return psycopg.connect(**connection_settings(), row_factory=dict_row,
                          connect_timeout=10, options='-c statement_timeout=30000')


def seed(conn):
    from .registry import load_registry
    for s in load_registry():
        conn.execute('''INSERT INTO veriflow.sources
            (id,name,url,category,aliases,provenance,collection_method,access_status,
             enabled,schedule_seconds,minimum_interval_seconds,full_text_allowed,policy_notes)
            VALUES (%(id)s,%(name)s,%(url)s,%(category)s,%(aliases)s,%(provenance)s,
            %(collection_method)s,%(access_status)s,%(enabled)s,%(schedule_seconds)s,
            %(minimum_interval_seconds)s,%(full_text_allowed)s,%(policy_notes)s)
            ON CONFLICT (id) DO NOTHING''', s)
