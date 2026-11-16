import unittest
from unittest.mock import Mock, patch
from veriflow.connectors import AccessDenied
from veriflow.free_collection import (
    BASE, SOURCE_ID, PRODUCT_URL, PRODUCT_NAME, fetch_test_page, reserve_test_job,
)


class FreeTestScopeTests(unittest.TestCase):
    def setUp(self):
        self.source = dict(id=SOURCE_ID, url=BASE, enabled=True, access_status='approved',
                           collection_method='permitted_crawl', required_license_id='CC-BY-SA-4.0',
                           attribution_required=True, full_text_allowed=True)
        self.grant = dict(method='permitted_crawl', full_text_allowed=True,
                          license_id='CC-BY-SA-4.0', terms_url=BASE+'/terms',
                          product_keys=[PRODUCT_URL])
        self.mapping = dict(external_key=PRODUCT_URL, expected_name=PRODUCT_NAME,
                            authorization_id='fixture-grant')

    def test_one_review_and_no_automatic_followup(self):
        client = Mock()
        client.collect.return_value = {'records':[], 'truncated':True}
        page = fetch_test_page(self.source,self.grant,self.mapping,PRODUCT_URL,client)
        client.collect.assert_called_once_with(PRODUCT_URL, PRODUCT_NAME, max_reviews=1, max_pages=1)
        self.assertIsNone(page['next_url'])

    def test_another_product_or_missing_credit_policy_cannot_collect(self):
        for key,value in [('external_key',BASE+'/other'),('expected_name','Other')]:
            mapping=dict(self.mapping,**{key:value})
            with self.assertRaises(AccessDenied):
                fetch_test_page(self.source,self.grant,mapping,PRODUCT_URL,Mock())
        source=dict(self.source,attribution_required=False)
        with self.assertRaises(AccessDenied):
            fetch_test_page(source,self.grant,self.mapping,PRODUCT_URL,Mock())
        grant=dict(self.grant,product_keys=[PRODUCT_URL,BASE+'/other'])
        with self.assertRaises(AccessDenied):
            fetch_test_page(self.source,grant,self.mapping,PRODUCT_URL,Mock())

    @patch('veriflow.worker.authorization')
    def test_third_job_is_denied_without_network_or_extra_records(self, authorize):
        authorize.return_value=self.grant
        conn=Mock()
        conn.execute.return_value.fetchone.side_effect=[self.source,{'count':2}]
        with self.assertRaises(AccessDenied):
            reserve_test_job(conn,self.mapping)
