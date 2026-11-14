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
