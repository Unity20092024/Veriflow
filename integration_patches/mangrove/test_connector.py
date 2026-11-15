"""Synthetic fixtures only. Never query Mangrove, Supabase or a live worker."""
import io
import json
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from integration_patches.mangrove.connector import (
    API_URL, TERMS_URL, ConnectorError, MangrovePageConnector,
    SoftwareProduct, normalize_review, terms_digest,
)

TERMS = ('Dataset reuse commercially under a license. '
         'When no license is specified, CC-BY-4.0 applies. Attribution by hyperlink.')
DIGEST = terms_digest(TERMS)[0]
PRODUCT = SoftwareProduct('https://fixture-software.example', 'Synthetic Software Fixture')


def entry(signature='A' * 86, **updates):
    payload = dict(sub=PRODUCT.subject, iat=1767225600, rating=75,
                   opinion='SYNTHETIC TEST FIXTURE ONLY', metadata={})
    payload.update(updates)
    return dict(signature=signature, payload=payload, jwt='OMIT PRIVATE DATA',
                kid='OMIT PRIVATE DATA', alias='OMIT PRIVATE DATA')


class ConnectorTests(unittest.TestCase):
    def client(self, rows=None, *, enabled=True, max_requests=8, terms=TERMS):
        self.requests, self.waits = [], []
        def transport(request, timeout):
            self.requests.append(request)
            self.assertEqual(timeout, 20)
            if request.full_url == TERMS_URL:
                return io.BytesIO(terms.encode())
            self.assertTrue(request.full_url.startswith(API_URL + '?'))
            self.assertEqual(request.get_header('Accept'), 'application/json')
            return io.BytesIO(json.dumps({'reviews': rows or []}).encode())
        return MangrovePageConnector(reviewed_terms_sha256=DIGEST,
            enabled=enabled, max_requests=max_requests, transport=transport,
            clock=lambda: 0, wait=self.waits.append)

    def test_default_disabled_and_missing_or_denied_permission_make_no_requests(self):
        client = self.client([entry()], enabled=False)
        with self.assertRaisesRegex(ConnectorError, 'connector_disabled'):
            client.fetch_page(PRODUCT, authorize=lambda *_: True)
        self.assertEqual(self.requests, [])
        client = self.client([entry()])
        for authorize in (None, lambda *_: False):
            with self.assertRaisesRegex(ConnectorError, 'worker_authorization_required'):
                client.fetch_page(PRODUCT, authorize=authorize)
        self.assertEqual(self.requests, [])

    def test_breadth_default_fetches_one_page_for_worker_selected_software(self):
        client = self.client([entry()])
        result = client.fetch_page(PRODUCT, authorize=lambda *_: True)
        self.assertEqual(len(self.requests), 2)
        query = parse_qs(urlsplit(self.requests[1].full_url).query)
        self.assertEqual(query['limit'], ['1'])
        self.assertEqual(query['sub'], [PRODUCT.subject])
        self.assertEqual(query['issuers'], ['false'])
        self.assertEqual(result['next_offset'], 1)
        self.assertEqual(result['requests_used'], 2)
        row = result['records'][0]
        self.assertEqual((row['rating'], row['rating_scale']), (75, 100))
        self.assertEqual(row['license_metadata']['attribution_url'], row['original_url'])
        self.assertNotIn('OMIT PRIVATE DATA', json.dumps(result))
        self.assertEqual(self.waits, [2])

    def test_incompatible_rows_advance_cursor_without_auto_fetching_next_page(self):
        client = self.client([entry(metadata={'license': 'CC-BY-SA-4.0'})])
        result = client.fetch_page(PRODUCT, authorize=lambda *_: True, offset=7)
        self.assertEqual(result['records'], [])
        self.assertEqual(result['next_offset'], 8)
        self.assertEqual(result['skipped'], {'unsupported_license': 1})
        self.assertEqual(len(self.requests), 2)

    def test_page_deduplication_and_wrong_product_rejection(self):
        client = self.client([entry(), entry(), entry('B' * 86, sub='https://unmapped.example')])
        result = client.fetch_page(PRODUCT, authorize=lambda *_: True, page_size=3)
        self.assertEqual(len(result['records']), 1)
        self.assertEqual(result['skipped'], {'duplicate_native_id': 1, 'wrong_subject_or_action': 1})
        self.assertEqual(result['next_offset'], 3)

    def test_explicit_unknown_null_or_conflicting_license_never_gets_default(self):
        for values in ({'metadata': {'license': None}}, {'license': 'unknown'},
                       {'license': 'CC-BY-SA-4.0', 'metadata': {'license': 'CC-BY-4.0'}}):
            with self.assertRaisesRegex(ConnectorError, 'unsupported_license'):
                normalize_review(entry(**values), PRODUCT)
        for rating in (True, float('nan'), float('inf'), 10**1000):
            with self.assertRaisesRegex(ConnectorError, 'invalid_native_rating'):
                normalize_review(entry(rating=rating), PRODUCT)

    def test_changed_terms_or_revocation_stops_before_api_request(self):
        client = self.client([entry()], terms=TERMS + ' Changed conditions.')
        with self.assertRaisesRegex(ConnectorError, 'source_terms_need_review'):
            client.fetch_page(PRODUCT, authorize=lambda *_: True)
        self.assertEqual(len(self.requests), 1)
        client = self.client([entry()])
        answers = iter((True, False))
        with self.assertRaisesRegex(ConnectorError, 'worker_authorization_required'):
            client.fetch_page(PRODUCT, authorize=lambda *_: next(answers))
        self.assertEqual(len(self.requests), 1)

    def test_revocation_before_return_discards_rows_and_callback_errors_are_safe(self):
        client = self.client([entry()])
        answers = iter((True, True, False))
        with self.assertRaisesRegex(ConnectorError, 'worker_authorization_required'):
            client.fetch_page(PRODUCT, authorize=lambda *_: next(answers))
        def unavailable(*_):
            raise RuntimeError('PRIVATE CREDENTIAL MUST NOT ESCAPE')
        with self.assertRaisesRegex(ConnectorError, '^worker_authorization_unavailable$'):
            client.fetch_page(PRODUCT, authorize=unavailable)

    def test_budget_and_page_bounds_fail_before_unbounded_source_calls(self):
        client = self.client([], max_requests=2)
        for kwargs in ({'offset': -1}, {'page_size': 21}, {'page_size': True}):
            with self.assertRaisesRegex(ConnectorError, 'invalid_page_limits'):
                client.fetch_page(PRODUCT, authorize=lambda *_: True, **kwargs)
        self.assertEqual(self.requests, [])
        result = client.fetch_page(PRODUCT, authorize=lambda *_: True)
        self.assertIsNone(result['next_offset'])
        with self.assertRaisesRegex(ConnectorError, 'request_budget_exhausted'):
            client.fetch_page(PRODUCT, authorize=lambda *_: True)
        self.assertEqual(len(self.requests), 2)
        client = self.client([entry(), entry('B' * 86)])
        with self.assertRaisesRegex(ConnectorError, 'invalid_source_page'):
            client.fetch_page(PRODUCT, authorize=lambda *_: True)

    def test_rate_limit_redirect_and_timeout_are_safe_without_retries(self):
        for status, code in ((429, 'source_rate_limited'), (302, 'source_access_denied'), (403, 'source_access_denied')):
            calls = []
            def transport(request, timeout):
                calls.append(request.full_url)
                raise HTTPError(request.full_url, status, 'PRIVATE BODY', {'Retry-After': '90'}, None)
            client = MangrovePageConnector(reviewed_terms_sha256=DIGEST, enabled=True, transport=transport)
            with self.assertRaises(ConnectorError) as caught:
                client.fetch_page(PRODUCT, authorize=lambda *_: True)
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(len(calls), 1)
            self.assertNotIn('PRIVATE', str(caught.exception))
            if status == 429:
                self.assertEqual(caught.exception.retry_after_seconds, 90)
        def timeout(request, timeout):
            raise TimeoutError('PRIVATE REQUEST')
        client = MangrovePageConnector(reviewed_terms_sha256=DIGEST, enabled=True, transport=timeout)
        with self.assertRaisesRegex(ConnectorError, '^source_unavailable$'):
            client.fetch_page(PRODUCT, authorize=lambda *_: True)


if __name__ == '__main__':
    unittest.main()
