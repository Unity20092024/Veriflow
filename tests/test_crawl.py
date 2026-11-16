import unittest
from unittest.mock import patch

from veriflow.crawl import extract_page


class PermittedCrawlTests(unittest.TestCase):
    def setUp(self):
        self.source = {
            'url':'https://reviews.example/',
            'collection_method':'permitted_crawl',
            'full_text_allowed':True,
            'required_license_id':None,
        }
        self.grant = {'method':'permitted_crawl','full_text_allowed':True}
        self.mapping = {
            'external_key':'https://reviews.example/product',
            'expected_name':'Fixture Product',
        }
        self.html = b'''<html><head><link rel="next" href="/product?page=2"></head><body>
          <script type="application/ld+json">
          {"@type":"Review","@id":"https://reviews.example/review/fixture",
           "datePublished":"2026-01-04","reviewBody":"FIXTURE ONLY",
           "reviewRating":{"ratingValue":"4","bestRating":"5"}}
          </script></body></html>'''

    @patch('veriflow.crawl._robots_allowed',return_value=True)
    @patch('veriflow.crawl._read_url')
    def test_extracts_one_page_and_returns_same_source_cursor(self, read_url, _robots):
        read_url.return_value = (
            200,{'Content-Type':'text/html; charset=utf-8'},
            'https://reviews.example/product?page=1',self.html,
        )
        page = extract_page(self.source,self.grant,self.mapping)
        self.assertEqual(len(page['records']),1)
        self.assertEqual(page['records'][0]['external_id'],'https://reviews.example/review/fixture')
        self.assertEqual(page['records'][0]['software_name'],'Fixture Product')
        self.assertEqual(page['records'][0]['review_text'],'FIXTURE ONLY')
        self.assertEqual(page['next_url'],'https://reviews.example/product?page=2')

    @patch('veriflow.crawl._robots_allowed',return_value=True)
    @patch('veriflow.crawl._read_url')
    def test_metadata_only_mode_does_not_store_review_text(self, read_url, _robots):
        self.source['full_text_allowed']=False
        read_url.return_value = (
            200,{'Content-Type':'text/html'},
            'https://reviews.example/product',self.html,
        )
        page = extract_page(self.source,self.grant,self.mapping)
        self.assertIsNone(page['records'][0]['review_text'])

    @patch('veriflow.crawl._robots_allowed',return_value=True)
    @patch('veriflow.crawl._read_url')
    def test_cross_source_pagination_is_ignored(self, read_url, _robots):
        html = self.html.replace(b'/product?page=2',b'https://other.example/page')
        read_url.return_value = (200,{'Content-Type':'text/html'},
                                 'https://reviews.example/product',html)
        page = extract_page(self.source,self.grant,self.mapping)
        self.assertIsNone(page['next_url'])

    @patch('veriflow.crawl._robots_allowed',return_value=True)
    def test_product_page_must_belong_to_authorized_source(self, _robots):
        self.mapping['external_key']='https://other.example/product'
        with self.assertRaises(Exception):
            extract_page(self.source,self.grant,self.mapping)


if __name__ == '__main__':
    unittest.main()
