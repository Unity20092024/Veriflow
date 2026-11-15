import json
import unittest
from dataclasses import asdict
from veriflow.registry import load_registry
from veriflow.connectors import ApprovedImportConnector, AccessDenied, CollectionError, ConnectorRegistry, Unsupported
from veriflow.admin import authorized, table


def fixture(**overrides):
    return dict(external_id='fixture-1',product_key='test-product',software_name='Test Product',
                review_text='TEST FIXTURE — not a real review',rating=4,rating_scale=5,
                published_at='2026-01-01',original_url='https://www.capterra.com/reviews/test-1',
                reviewer_email='discard@example.invalid',reviewer_name='Discard',**overrides)


class ConnectorTests(unittest.TestCase):
    def setUp(self):
        self.source = next(s for s in load_registry() if s['id']=='capterra-reviews')
        self.source['full_text_allowed'] = True
        self.grant = dict(method='approved_import',full_text_allowed=True)
        self.connector = ApprovedImportConnector()

    def collect(self,row):
        return self.connector.collect(json.dumps([row]),'json',self.source,self.grant)[0]

    def test_registry_completeness_and_safe_defaults(self):
        sources = load_registry()
        self.assertEqual(len(sources),42)
        self.assertEqual(sum(s['provenance']=='REVIEWS PLATFORMS.pdf' for s in sources),33)
        self.assertFalse(any(s['enabled'] or s['full_text_allowed'] for s in sources))
        self.assertEqual(len({s['url'] for s in sources}),42)

    def test_identity_fields_are_discarded(self):
        record = asdict(self.collect(fixture()))
        self.assertNotIn('reviewer_email',record)
        self.assertNotIn('reviewer_name',record)

    def test_full_text_requires_both_permissions(self):
        for source_allowed,grant_allowed in [(False,True),(True,False),(False,False)]:
            self.source['full_text_allowed']=source_allowed
            self.grant['full_text_allowed']=grant_allowed
            with self.assertRaises(AccessDenied): self.collect(fixture())

    def test_metadata_only_without_text_authorization(self):
        self.source['full_text_allowed']=False
        row=fixture();row['review_text']=None
        self.assertIsNone(self.collect(row).text)

    def test_invalid_urls_dates_and_ratings(self):
        for key,value in [('original_url','https://capterra.com.attacker.invalid/1'),
                          ('original_url','http://capterra.com/1'),
                          ('original_url','https://user:password@capterra.com/1'),
                          ('rating',float('nan')),('rating',float('inf')),('rating',6),
                          ('published_at','2099-01-01')]:
            row=fixture();row[key]=value
            with self.assertRaises((CollectionError,ValueError)): self.collect(row)

    def test_duplicate_fingerprint_normalizes_text(self):
        a=fixture();b=fixture();b['review_text']='  TEST  FIXTURE — NOT A REAL REVIEW '
        b['external_id']='fixture-2'
        self.assertEqual(self.collect(a).fingerprint,self.collect(b).fingerprint)

    def test_csv(self):
        csv='external_id,product_key,software_name,published_at,original_url\nfixture,test-product,Test Product,2026-01-01,https://capterra.com/review/fixture\n'
        self.assertEqual(self.connector.collect(csv,'csv',self.source,self.grant)[0].product_key,'test-product')

    def test_unsupported_connectors_fail_closed(self):
        with self.assertRaises(Unsupported): ConnectorRegistry().get('authorized_api')

    def test_private_dashboard_escaping_and_auth(self):
        import base64
        header='Basic '+base64.b64encode(b'admin:password').decode()
        self.assertTrue(authorized(header,'admin','password'))
        self.assertFalse(authorized(header,'admin','wrong'))
        self.assertFalse(authorized('Basic ???','admin','password'))
        self.assertIn('&lt;script&gt;',table([{'text':'<script>'}]))
