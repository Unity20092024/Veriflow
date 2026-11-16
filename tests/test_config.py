import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from veriflow.config import load_environment
from veriflow.db import connect


class ConfigTests(unittest.TestCase):
    def test_owner_only_environment_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'runtime.env'
            path.write_text('COMPOSIO_USER_ID=test-user\n')
            path.chmod(0o644)
            with patch.dict(os.environ,{'VERIFLOW_ENV_FILE':str(path)},clear=True):
                with self.assertRaises(ValueError):load_environment()
                path.chmod(0o600)
                load_environment()
                self.assertEqual(os.environ['COMPOSIO_USER_ID'],'test-user')

    def test_project_guard_rejects_owner_wrong_project_and_insecure_tls(self):
        for url in ['postgresql://postgres:secret@db.qrejfpeclncrevmepgzx.supabase.co/postgres?sslmode=verify-full',
                    'postgresql://veriflow_app:secret@db.other-project.supabase.co/postgres?sslmode=verify-full',
                    'postgresql://veriflow_app:secret@db.qrejfpeclncrevmepgzx.supabase.co/postgres?sslmode=require']:
            with patch.dict(os.environ,{'DATABASE_URL':url,'SUPABASE_PROJECT_REF':'qrejfpeclncrevmepgzx'},clear=True):
                with patch('veriflow.db.psycopg.connect') as transport:
                    with self.assertRaises(ValueError):connect()
                    transport.assert_not_called()

    def test_database_url_accepts_official_application_role_with_verified_tls(self):
        url = ('postgresql://veriflow_app.qrejfpeclncrevmepgzx:fixture-password'
               '@aws-1-us-west-2.pooler.supabase.com:5432/postgres?sslmode=verify-full')
        with patch.dict(os.environ, {'DATABASE_URL': url}, clear=True):
            with patch('veriflow.db.psycopg.connect') as transport:
                connect()
                settings = transport.call_args.kwargs
                self.assertEqual(settings['host'], 'aws-1-us-west-2.pooler.supabase.com')
                self.assertEqual(settings['user'], 'veriflow_app.qrejfpeclncrevmepgzx')
                self.assertEqual(settings['sslmode'], 'verify-full')
                self.assertEqual(settings['sslrootcert'], 'system')

    def test_app_password_secret_overrides_url_password_without_changing_target(self):
        url = ('postgresql://veriflow_app.qrejfpeclncrevmepgzx:stale-fixture'
               '@aws-1-us-west-2.pooler.supabase.com:5432/postgres?sslmode=verify-full')
        with patch.dict(os.environ, {
            'SUPABASE_DATABASE_URL': url,
            'VERIFLOW_APP_PASSWORD': 'current-fixture-password',
            'SUPABASE_SSL_ROOT_CERT': '/trusted/supabase-ca.crt',
        }, clear=True):
            with patch('veriflow.db.psycopg.connect') as transport:
                connect()
                settings = transport.call_args.kwargs
                self.assertEqual(settings['password'], 'current-fixture-password')
                self.assertEqual(settings['host'], 'aws-1-us-west-2.pooler.supabase.com')
                self.assertEqual(settings['user'], 'veriflow_app.qrejfpeclncrevmepgzx')
                self.assertEqual(settings['dbname'], 'postgres')
                self.assertEqual(settings['sslmode'], 'verify-full')
                self.assertEqual(settings['sslrootcert'], '/trusted/supabase-ca.crt')

    def test_external_secret_takes_precedence_over_managed_database_url(self):
        external = ('postgresql://veriflow_app.qrejfpeclncrevmepgzx:fixture-password'
                    '@aws-1-us-west-2.pooler.supabase.com/postgres?sslmode=verify-full')
        with patch.dict(os.environ, {
            'DATABASE_URL': 'postgresql://local:fixture-password@localhost/managed',
            'SUPABASE_DATABASE_URL': external,
            'SUPABASE_SSL_ROOT_CERT': '/trusted/supabase-ca.crt',
        }, clear=True):
            with patch('veriflow.db.psycopg.connect') as transport:
                connect()
                self.assertEqual(transport.call_args.kwargs['sslrootcert'],
                                 '/trusted/supabase-ca.crt')

    def test_wrong_endpoint_and_target_overrides_never_connect(self):
        base = ('postgresql://veriflow_app.qrejfpeclncrevmepgzx:fixture-password'
                '@aws-1-us-west-2.pooler.supabase.com/postgres?sslmode=verify-full')
        for url in [base.replace('us-west-2', 'us-east-1'),
                    base + '&hostaddr=127.0.0.1',
                    base.replace('/postgres?', '/other?'),
                    base.replace('.com/postgres', '.com:6543/postgres')]:
            with patch.dict(os.environ, {'DATABASE_URL': url}, clear=True):
                with patch('veriflow.db.psycopg.connect') as transport:
                    with self.assertRaises(ValueError):
                        connect()
                    transport.assert_not_called()
