import os
import unittest
from unittest.mock import patch
from veriflow.admin import serve

class AdminDeploymentTests(unittest.TestCase):
    def test_managed_port_preserves_loopback_default_and_auth_requirement(self):
        with patch.dict(os.environ,{'PORT':'9123','ADMIN_USERNAME':'operator','ADMIN_PASSWORD':'fixture-password-over-24-characters'},clear=True):
            with patch('veriflow.admin.ThreadingHTTPServer') as server:
                serve()
                self.assertEqual(server.call_args.args[0],('127.0.0.1',9123))
                serve(9124,host='0.0.0.0')
                self.assertEqual(server.call_args.args[0],('0.0.0.0',9124))

    def test_external_binding_still_rejects_missing_admin_credentials(self):
        with patch.dict(os.environ,{},clear=True):
            with patch('veriflow.admin.ThreadingHTTPServer') as server:
                with self.assertRaises(ValueError):serve(9123,host='0.0.0.0')
                server.assert_not_called()

    def test_invalid_port_or_host_never_opens_a_listener(self):
        for port,host in ((-1,'127.0.0.1'),(65536,'0.0.0.0'),(9123,'example.invalid')):
            with patch('veriflow.admin.ThreadingHTTPServer') as server:
                with self.assertRaises(ValueError):serve(port,host)
                server.assert_not_called()
