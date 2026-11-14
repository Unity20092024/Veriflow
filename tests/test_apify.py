import io
import json
import unittest
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit,parse_qs
from veriflow.apify import ApifyClient,ApifyError,StartUnknown,usd,NoRedirect
from veriflow.apify_pipeline import normalize_items,pricing_snapshot
from veriflow.connectors import CollectionError,RateLimited


class ApifyTests(unittest.TestCase):
    def test_token_only_in_header_and_paid_start_bounds(self):
        captured=[]
        def transport(req,timeout):
            captured.append(req)
            return io.BytesIO(json.dumps({'data':{'id':'test-run'}}).encode())
        client=ApifyClient('PRIVATE-TEST-TOKEN',transport)
        client.start('testactor','1.2.3',{'maxResults':20},usd('.5'),20,60)
        req=captured[0];params=parse_qs(urlsplit(req.full_url).query)
        self.assertNotIn('PRIVATE-TEST-TOKEN',req.full_url)
        self.assertNotIn('PRIVATE-TEST-TOKEN',req.data.decode())
        self.assertEqual(req.get_header('Authorization'),'Bearer PRIVATE-TEST-TOKEN')
        self.assertEqual(params['maxTotalChargeUsd'],['0.5'])
        self.assertEqual(params['forcePermissionLevel'],['LIMITED_PERMISSIONS'])
        self.assertEqual(params['restartOnError'],['false'])
        self.assertEqual(params['timeout'],['60'])

    def test_paginated_projected_export_is_bounded(self):
        calls=[]
        def transport(req,timeout):
            params=parse_qs(urlsplit(req.full_url).query);calls.append(params)
            offset=int(params['offset'][0]);limit=int(params['limit'][0])
            return io.BytesIO(json.dumps([{'id':i} for i in range(offset,offset+limit)]).encode())
        result=ApifyClient('test',transport).items('dataset',['id','reviewText'],133)
        self.assertEqual(len(result),133)
        self.assertEqual(calls[1]['offset'],['100'])
        self.assertEqual(calls[1]['limit'],['33'])
        self.assertEqual(calls[0]['skipEmpty'],['false'])
        self.assertEqual(calls[0]['fields'],['id,reviewText'])

    def test_csv_export_supported(self):
        client=ApifyClient('test',lambda req,timeout:io.BytesIO(b'id,text\n1,fixture\n'))
        self.assertTrue(client.export('dataset',['id','text'],format='csv').startswith(b'id,text'))

    def test_start_timeout_is_unknown_and_not_retried(self):
        calls=[]
        def transport(req,timeout):calls.append(req);raise URLError('private response')
        with self.assertRaises(StartUnknown):ApifyClient('test',transport).start('actor','1.0.0',{},usd(1),20,60)
        self.assertEqual(len(calls),1)

    def test_rate_limit_and_auth_errors_are_sanitized(self):
        for status,expected in [(401,'apify_authentication_failed'),(403,'apify_permission_denied'),(429,'rate_limited')]:
            def transport(req,timeout):raise HTTPError(req.full_url,status,'PRIVATE TOKEN',{'Retry-After':'180'},None)
            with self.assertRaises(CollectionError) as result:ApifyClient('test',transport).run('run')
            self.assertEqual(result.exception.code,expected)
            self.assertNotIn('PRIVATE',str(result.exception))
            if status==429:self.assertEqual(result.exception.retry_after,180)

    def test_missing_token_invalid_ids_and_nonfinite_costs_fail_closed(self):
        client=ApifyClient();client.token=None
        with self.assertRaises(ApifyError):client.run('run')
        for bad in ['../secret','name?token=bad','https://elsewhere.invalid']:
            with self.assertRaises(CollectionError):client.run(bad)
        for bad in ['NaN','Infinity','-1']:
            with self.assertRaises(CollectionError):usd(bad)
        self.assertIsNone(NoRedirect().redirect_request(None,None,None,None,None,None))

    def test_normalization_discards_identifiers_and_preserves_original_rating(self):
        binding=dict(product_key='product',field_mapping=dict(fields={
            'external_id':['id'],'software_name':['name'],'review_text':['body'],
            'rating':['stars'],'published_at':['date'],'original_url':['url']},rating_scale_constant=5))
        records=normalize_items([dict(id=42,name='Product',body='TEST FIXTURE',stars=4,date='2026-01-01T12:00:00Z',url='https://capterra.com/reviews/test',email='discard@example.invalid')],binding)
        self.assertEqual(records[0]['external_id'],'42')
        self.assertEqual(records[0]['rating'],4)
        self.assertEqual(records[0]['rating_scale'],5)
        self.assertEqual(records[0]['published_at'],'2026-01-01')
        self.assertNotIn('email',records[0])

    def test_audit_covers_exact_registry_and_disables_permission_claims(self):
        from pathlib import Path
        from veriflow.registry import load_registry
        audit=json.loads(Path('data/source-capabilities.json').read_text())
        self.assertEqual({a['source_id'] for a in audit},{s['id'] for s in load_registry()})
        self.assertTrue(all(a['collection_permission']=='not_confirmed' for a in audit))

    def test_paid_start_rejects_secret_in_input_and_invalid_bounds(self):
        client=ApifyClient('PRIVATE-TEST-TOKEN',lambda *a,**k:self.fail('Paid request must not occur'))
        with self.assertRaises(CollectionError):client.start('actor','1.0.0',{'credential':'PRIVATE-TEST-TOKEN'},usd(1),20,60)
        for cost,records,timeout in [(0,20,60),(1,1001,60),(1,20,0)]:
            with self.assertRaises(CollectionError):client.start('actor','1.0.0',{},cost,records,timeout)
