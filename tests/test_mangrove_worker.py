import io
import json
import unittest
from urllib.parse import urlsplit
from urllib.request import Request

from veriflow.connectors import AccessDenied, CollectionError, ConnectorRegistry
from veriflow.mangrove_live import MangroveAPIConnector, MangroveClient, SOURCE_DEFINITION


SUBJECT = 'https://bitwarden.com'
TERMS = 'Share commercially under a license. When no license is specified, CC-BY-4.0 applies. Attribution through hyperlink to the review.'


def entry(signature, license_id=None, subject=SUBJECT):
    metadata = {} if license_id is None else {'license': license_id}
    return {
        'signature': signature,
        'kid': 'NEVER RETAIN',
        'jwt': 'NEVER RETAIN',
        'payload': {
            'sub': subject,
            'iat': 1767225600,
            'rating': 75,
            'opinion': 'A real-looking test fixture, not collected data.',
            'metadata': metadata,
        },
    }


def source(enabled=True, access_status='approved'):
    return dict(SOURCE_DEFINITION, enabled=enabled, access_status=access_status,
                full_text_allowed=True)


def grant():
    return {
        'method': 'authorized_api',
        'license_id': 'CC-BY-4.0',
        'terms_url': 'https://mangrove.reviews/terms',
        'full_text_allowed': True,
        'product_keys': [SUBJECT],
    }


def mapping():
    return {'external_key': SUBJECT, 'expected_name': 'Bitwarden'}


class FakeClient:
    def __init__(self, rows):
        self.rows = rows
        self.offsets = []

    def verify_policy(self):
        return 'test-terms-hash'

    def page(self, params):
        self.offsets.append(params['offset'])
        return self.rows


class MangroveWorkerConnectorTests(unittest.TestCase):
    def test_registered_for_existing_authorized_api_worker(self):
        self.assertIsInstance(ConnectorRegistry().get('authorized_api', {'id': 'mangrove-reviews'}),
                              MangroveAPIConnector)

    def test_records_are_normalized_and_license_checked_by_normal_ingestion(self):
        client = FakeClient([entry('A' * 86)])
        connector = MangroveAPIConnector(client_factory=lambda: client)
        page = connector.fetch_page(source(), grant(), mapping())
        rows = page['records']
        self.assertIsNone(page['next_url'])
        self.assertEqual(len(rows), 1)
        self.assertNotIn('NEVER RETAIN', json.dumps(rows))
        normalized = connector.collect(json.dumps(rows), 'json', source(), grant())
        self.assertEqual(normalized[0].rating, 75)
        self.assertEqual(normalized[0].license_metadata['license_id'], 'CC-BY-4.0')
        self.assertEqual(normalized[0].license_metadata['public_credit'], 'Original review on Mangrove')
        self.assertTrue(normalized[0].original_url.startswith(
            'https://api.mangrove.reviews/review/'))

    def test_pagination_skips_incompatible_license_and_advances_offset(self):
        client = FakeClient([entry('B' * 86, 'CC-BY-SA-4.0')] * 20)
        connector = MangroveAPIConnector(client_factory=lambda: client)
        page = connector.fetch_page(source(), grant(), mapping())
        rows, cursor = page['records'], page['next_url']
        self.assertEqual(rows, [])
        self.assertEqual(cursor, 'mangrove-offset:20')
        connector.fetch_page(source(), grant(), mapping(), cursor)
        self.assertEqual(client.offsets, [0, 20])

    def test_unapproved_source_or_mapping_is_rejected(self):
        connector = MangroveAPIConnector(client_factory=lambda: self.fail('network must not run'))
        with self.assertRaises(AccessDenied):
            connector.fetch_page(source(False), grant(), mapping())
        with self.assertRaises(AccessDenied):
            connector.fetch_page(source(), grant(), {'external_key': 'https://unknown.invalid',
                                                     'expected_name': 'Unknown'})

    def test_discovery_returns_only_allowlisted_subjects_with_real_eligible_records(self):
        candidates = [
            entry('C' * 86),
            entry('D' * 86, subject='https://unreviewed.invalid'),
            entry('E' * 86, 'CC-BY-SA-4.0', subject='https://github.com'),
            entry('F' * 86, subject='https://github.com'),
        ]
        def transport(request: Request, timeout):
            if urlsplit(request.full_url).path == '/terms':
                return io.BytesIO(TERMS.encode())
            return io.BytesIO(json.dumps({'reviews': candidates}).encode())

        connector = MangroveAPIConnector(
            client_factory=lambda: MangroveClient(transport=transport, wait=lambda _: None))
        self.assertEqual(connector.discover_products('software'), [
            {'name': 'Bitwarden', 'url': SUBJECT, 'category': 'Password managers'},
            {'name': 'GitHub', 'url': 'https://github.com', 'category': 'Developer platforms'},
        ])
        with self.assertRaises(CollectionError):
            connector.discover_products('software', 6)

    def test_cursor_cannot_escape_fixed_source_pagination(self):
        connector = MangroveAPIConnector(client_factory=lambda: self.fail('network must not run'))
        with self.assertRaises(CollectionError):
            connector.fetch_page(source(), grant(), mapping(), 'https://evil.invalid/')

    def test_source_definition_is_disabled_and_unapproved_by_default(self):
        self.assertFalse(SOURCE_DEFINITION['enabled'])
        self.assertFalse(SOURCE_DEFINITION['full_text_allowed'])
        self.assertEqual(SOURCE_DEFINITION['access_status'], 'pending_authorization')


if __name__ == '__main__':
    unittest.main()
