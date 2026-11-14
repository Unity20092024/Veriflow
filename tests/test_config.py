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
