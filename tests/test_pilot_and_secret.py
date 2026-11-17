import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from veriflow.secure_config import configure_token,write_environment,SecureConfigError
from veriflow.config import read_environment
from veriflow.pilot import policy,max_records,require_paid_enabled,PaidRunsDisabled


class PilotAndSecretTests(unittest.TestCase):
    def test_approved_caps_cannot_be_raised_by_environment(self):
        self.assertEqual(policy()['max_total_usd'],'1.00')
        with patch.dict(os.environ,{'APIFY_MAX_RECORDS':'500'}):self.assertEqual(max_records(),20)
        with patch.dict(os.environ,{'APIFY_MAX_RECORDS':'5'}):self.assertEqual(max_records(),5)

    def test_paid_starts_disabled_by_default(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(PaidRunsDisabled):require_paid_enabled()
        with patch.dict(os.environ,{'APIFY_PAID_RUNS_ENABLED':'true'},clear=True):
            with self.assertRaises(PaidRunsDisabled):require_paid_enabled()

    def test_token_configuration_preserves_credentials_and_never_prints_key(self):
        token='TEST-ONLY-SECRET-NEVER-A-REAL-API-KEY'
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'runtime.env'
            write_environment(path,{'DATABASE_URL':'fixture-db-url','ADMIN_PASSWORD':'fixture-admin-password'})
            out=io.StringIO()
            with patch('sys.stdin.isatty',return_value=True),patch('getpass.getpass',return_value=token),contextlib.redirect_stdout(out):
                result=configure_token(path)
            config=read_environment(path)
            self.assertEqual(config['DATABASE_URL'],'fixture-db-url')
            self.assertEqual(config['ADMIN_PASSWORD'],'fixture-admin-password')
            self.assertEqual(config['APIFY_TOKEN'],token)
            self.assertEqual(config['APIFY_MAX_RECORDS'],'20')
            self.assertEqual(config['APIFY_PAID_RUNS_ENABLED'],'false')
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            self.assertNotIn(token,out.getvalue()+json.dumps(result))

    def test_noninteractive_prompt_and_insecure_locations_rejected(self):
        with patch('sys.stdin.isatty',return_value=False):
            with self.assertRaises(SecureConfigError):configure_token()
        with tempfile.TemporaryDirectory() as directory:
            parent=Path(directory)/'world-readable';parent.mkdir(mode=0o755);parent.chmod(0o755)
            with self.assertRaises(SecureConfigError):write_environment(parent/'runtime.env',{'APIFY_TOKEN':'test'})
        with self.assertRaises(SecureConfigError):write_environment(Path('unsafe-token.env').absolute(),{'APIFY_TOKEN':'test'})

    def test_symlink_and_control_characters_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'target.env';write_environment(target,{'APIFY_TOKEN':'test'})
            link=root/'link.env';link.symlink_to(target)
            with self.assertRaises(SecureConfigError):write_environment(link,{'APIFY_TOKEN':'replacement'})
            with self.assertRaises(SecureConfigError):write_environment(target,{'APIFY_TOKEN':'line\nbreak'})
