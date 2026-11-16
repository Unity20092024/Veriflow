"""Read-only proof against the existing Supabase schema; no credential output."""
import json
import psycopg
from .db import connect


def main():
    try:
        with connect() as conn:
            conn.execute('SET TRANSACTION READ ONLY')
            role = conn.execute('SELECT current_user AS role').fetchone()['role']
            if role != 'veriflow_app' or not conn.pgconn.ssl_in_use:
                print(json.dumps({'status': 'permission_failure',
                                  'reason': 'Dedicated application role and TLS required'}))
                return 1
            count = conn.execute('SELECT count(*) AS count FROM veriflow.sources').fetchone()['count']
            rows = conn.execute(
                'SELECT id,name,enabled FROM veriflow.sources ORDER BY name LIMIT 50'
            ).fetchall()
            print(json.dumps({'status': 'successful', 'certificate_verified': True,
                              'role': role, 'source_count': count,
                              'expected_42_sources_visible': count == 42, 'sources': rows}))
            return 0
    except ValueError:
        status, reason = 'configuration_missing_or_invalid', 'Expected Supabase secret and verified TLS configuration required'
    except psycopg.Error as exc:
        # libpq messages may contain DSNs or provider details: classify, never print.
        code = exc.sqlstate or ''
        message = str(exc).lower()
        if code.startswith('28') or 'password authentication failed' in message:
            status, reason = 'authentication_failure', 'Application-role authentication rejected'
        elif code == '42501':
            status, reason = 'permission_failure', 'Application role cannot read private sources'
        elif 'certificate' in message or 'ssl error' in message:
            status, reason = 'tls_failure', 'Certificate-verified TLS could not be established'
        elif isinstance(exc, psycopg.OperationalError):
            status, reason = 'network_or_connection_failure', 'Connection failed; inspect network, pooler, or server availability'
        else:
            status, reason = 'query_failure', 'Read-only sources query failed'
    print(json.dumps({'status': status, 'reason': reason,
                      'sources_query_verified': False}))
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
