import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock,patch
from scripts.reset_app_password import reset_role_password,main

class PasswordResetTests(unittest.TestCase):
    def role(self):
        return dict(rolcanlogin=True,rolsuper=False,rolbypassrls=False,
                    rolcreaterole=False,rolcreatedb=False,runtime_member=True)

    def test_only_fixed_role_password_is_changed_and_plaintext_not_sql(self):
        conn=Mock();conn.execute.return_value.fetchone.return_value=self.role()
        conn.pgconn.encrypt_password.return_value=b'SCRAM-SHA-256$fixture-verifier'
        password='aB3'*12
        reset_role_password(conn,password)
        query=conn.execute.call_args.args[0].as_string()
        self.assertTrue(query.startswith('ALTER ROLE veriflow_app PASSWORD '))
        self.assertNotIn(password,query)
        self.assertNotIn('postgres',query)
        self.assertEqual(conn.execute.call_count,2)

    def test_unexpected_or_absent_role_is_never_modified(self):
        for r in (None,dict(self.role(),rolsuper=True),dict(self.role(),runtime_member=False)):
            conn=Mock();conn.execute.return_value.fetchone.return_value=r
            with self.assertRaises(ValueError):reset_role_password(conn,'aB3'*12)
            conn.pgconn.encrypt_password.assert_not_called()
            self.assertEqual(conn.execute.call_count,1)

    def test_missing_confirmation_blocks_network_and_secret_output(self):
        password='aB3'*12
        with patch.dict(os.environ,{'VERIFLOW_APP_PASSWORD':password,'VERIFLOW_RESET_POSTGRES_PASSWORD':'admin-fixture'},clear=True):
            out=io.StringIO()
            with patch('scripts.reset_app_password.psycopg.connect') as connect,redirect_stdout(out):
                self.assertEqual(main(),1)
                connect.assert_not_called()
            self.assertNotIn(password,out.getvalue())
            self.assertNotIn('admin-fixture',out.getvalue())
