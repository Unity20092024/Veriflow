import io
import json
import unittest
from urllib.parse import parse_qs,urlsplit
from urllib.error import HTTPError
from veriflow.composio import ComposioClient,DiscoveryUnavailable
from veriflow.connectors import RateLimited


class DiscoveryTests(unittest.TestCase):
    def test_missing_credentials_never_calls_network(self):
        c=ComposioClient(transport=lambda *a,**k:self.fail('network called'))
        c.api_key=None;c.user_id=None
        with self.assertRaises(DiscoveryUnavailable): c.discover()

    def test_paginated_connected_inventory_and_google_trends(self):
        calls=[]
        def transport(request,timeout):
            calls.append(request)
            url=urlsplit(request.full_url);params=parse_qs(url.query)
            if url.path.endswith('connected_accounts'):
                self.assertEqual(params['user_ids'],['veriflow-operator'])
                body={'items':[{'id':'account-test','status':'ACTIVE','toolkit':{'slug':'example'},'credentials':'DO NOT KEEP'}],'next_cursor':'p2'} if 'cursor' not in params else {'items':[]}
            else:
                body={'items':[{'slug':'EXAMPLE_RESEARCH','toolkit':{'slug':'example'},'name':'Example research','version':'test-version','input_parameters':{'type':'object'}}]}
            return io.BytesIO(json.dumps(body).encode())
        result=ComposioClient('test-key','veriflow-operator',transport).discover()
        self.assertEqual(len(calls),4)
        self.assertNotIn('DO NOT KEEP',json.dumps(result))
        self.assertFalse(result['execution_enabled'])
        self.assertEqual(result['tools'][0]['version'],'test-version')

    def test_429_retry_after(self):
        def transport(request,timeout):
            raise HTTPError(request.full_url,429,'rate limit',{'Retry-After':'180'},None)
        with self.assertRaises(RateLimited) as result: ComposioClient('test','user',transport).discover()
        self.assertEqual(result.exception.retry_after,180)

    def test_repeated_cursor_is_error(self):
        client=ComposioClient('test','user')
        client._get=lambda *a:{'items':[],'next_cursor':'same'}
        with self.assertRaises(DiscoveryUnavailable): client.discover()

    def test_current_sdk_uses_paginated_user_scoped_endpoints(self):
        from types import SimpleNamespace
        calls=[]
        def accounts(**params):
            calls.append(('accounts',params))
            return {'items':[{'id':'test-account','status':'ACTIVE','toolkit':{'slug':'test-provider'}}]} if 'cursor' in params else {'items':[],'next_cursor':'page2'}
        def tools(**params):
            calls.append(('tools',params))
            return {'items':[{'slug':'TEST_READ','version':'test-v1','toolkit':{'slug':'test-provider'},'input_parameters':{'type':'object'}}]}
        sdk=SimpleNamespace(client=SimpleNamespace(connected_accounts=SimpleNamespace(list=accounts),tools=SimpleNamespace(list=tools)))
        result=ComposioClient('test-key','test-user',sdk=sdk).discover()
        self.assertEqual(result['connected_services'][0]['toolkit'],'test-provider')
        self.assertEqual(calls[0][1]['user_ids'],['test-user'])
        self.assertEqual(calls[1][1]['cursor'],'page2')
        self.assertIn(('tools',{'query':'Google Trends','limit':100}),calls)

    def test_sdk_authentication_failure_is_sanitized(self):
        class AuthError(Exception):
            status_code=401
        with self.assertRaises(DiscoveryUnavailable) as result:
            ComposioClient._sdk_error(AuthError('private provider response'))
        self.assertEqual(result.exception.code,'authentication_failed')
        self.assertNotIn('private',str(result.exception))

    def test_trends_normalization_drops_private_fields(self):
        from veriflow.integrations import normalize_trends
        result=normalize_trends({'rows':[{'day':'2026-01-01','interest':25,'account_email':'discard@example.invalid'}]},
                                {'rows_path':['rows'],'date_key':'day','value_key':'interest'})
        self.assertEqual(result,{'series':[{'date':'2026-01-01','value':25}]})
        for invalid in [float('nan'),float('inf'),101,True]:
            with self.assertRaises(Exception):
                normalize_trends([{'day':'2026-01-01','interest':invalid}],{'date_key':'day','value_key':'interest'})

    def test_sdk_disables_tracking_implicit_files_and_log_propagation(self):
        from unittest.mock import patch
        with patch('composio.Composio') as constructor:
            ComposioClient('test-key','test-user')._ensure_sdk()
            config=constructor.call_args.kwargs
            self.assertFalse(config['allow_tracking'])
            self.assertFalse(config['dangerously_allow_auto_upload_download_files'])
            self.assertFalse(config['file_upload_dirs'])
            self.assertFalse(config['logger'].propagate)
