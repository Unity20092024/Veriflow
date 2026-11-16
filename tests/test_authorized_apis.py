import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from veriflow.connectors import (
    AccessDenied,
    AppleAppStoreReviewsConnector,
    CollectionError,
    ConnectorRegistry,
    GooglePlayReviewsConnector,
)


class AuthorizedApiConnectorTests(unittest.TestCase):
    def setUp(self):
        self.google_source = {
            'id': 'google-play',
            'url': 'https://play.google.com',
            'collection_method': 'authorized_api',
            'full_text_allowed': True,
        }
        self.apple_source = {
            'id': 'apple-app-store',
            'url': 'https://apps.apple.com',
            'collection_method': 'authorized_api',
            'full_text_allowed': True,
        }
        self.grant = {'method': 'authorized_api', 'full_text_allowed': True}

    def test_google_play_pages_reviews_and_discards_reviewer_identity(self):
        requests = []

        def mocked_request(url, token):
            requests.append((url, token))
            if len(requests) == 1:
                return {
                    'reviews': [
                        {
                            'reviewId': 'review-1',
                            'reviewer': {'displayName': 'Must not be stored'},
                            'comments': [{
                                'userComment': {
                                    'text': 'A useful review',
                                    'originalText': 'A useful review',
                                    'starRating': 4,
                                    'lastModified': {'seconds': '1767225600'},
                                },
                            }],
                        },
                        {
                            'reviewId': 'review-1',
                            'comments': [{
                                'userComment': {
                                    'text': 'Duplicate',
                                    'starRating': 4,
                                    'lastModified': {'seconds': '1767225600'},
                                },
                            },
                            ],
                        },
                    ],
                    'tokenPagination': {'nextPageToken': 'next-page-secret'},
                }
            return {'reviews': []}

        connector = GooglePlayReviewsConnector(mocked_request)
        mapping = {
            'external_key': 'com.example.app',
            'expected_name': 'Example App',
        }
        with patch.dict('os.environ', {'GOOGLE_PLAY_ACCESS_TOKEN': 'test-token'}):
            rows, cursor = connector.fetch_page(
                self.google_source, self.grant, mapping
            )
            validated = connector.collect(json.dumps(rows), 'json', self.google_source, self.grant)
            next_rows, next_cursor = connector.fetch_page(
                self.google_source, self.grant, mapping, cursor
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(validated), 1)
        self.assertEqual(validated[0].external_id, 'review-1')
        self.assertEqual(validated[0].text, 'A useful review')
        self.assertEqual(validated[0].rating, 4)
        self.assertEqual(validated[0].published_at, '2026-01-01')
        self.assertIn('reviewId=review-1', validated[0].original_url)
        self.assertEqual(cursor, 'pageToken:next-page-secret')
        self.assertIsNone(next_cursor)
        self.assertEqual(next_rows, [])
        self.assertEqual(requests[0][1], 'test-token')
        self.assertEqual(parse_qs(urlsplit(requests[1][0]).query)['token'], ['next-page-secret'])
        self.assertEqual(parse_qs(urlsplit(requests[0][0]).query)['maxResults'], ['100'])
        self.assertNotIn('test-token', requests[0][0])

    def test_google_play_suppresses_text_without_explicit_full_text_grant(self):
        connector = GooglePlayReviewsConnector(lambda _url, _token: {
            'reviews': [{
                'reviewId': 'review-2',
                'comments': [{
                    'userComment': {
                        'text': 'Not authorized to retain',
                        'starRating': 5,
                        'lastModified': {'seconds': '1767225600'},
                    },
                }],
            }],
        })
        source = dict(self.google_source, full_text_allowed=False)
        with patch.dict('os.environ', {'GOOGLE_PLAY_ACCESS_TOKEN': 'test-token'}):
            rows, _ = connector.fetch_page(
                source, self.grant, {'external_key': 'com.example.app', 'expected_name': 'Example'}
            )
        self.assertIsNone(rows[0]['review_text'])

    def test_apple_store_paginates_and_uses_public_listing_attribution(self):
        requests = []

        def mocked_request(url, token):
            requests.append((url, token))
            return {
                'data': [
                    {
                        'id': 'apple-review-1',
                        'attributes': {
                            'rating': 5,
                            'title': 'Works',
                            'body': 'As expected',
                            'createdDate': '2026-02-03T04:05:06Z',
                            'reviewerNickname': 'Never collect this',
                        },
                    },
                ],
                'links': {'next': 'https://api.appstoreconnect.apple.com/v1/apps/12345/customerReviews?cursor=abc'},
            }

        connector = AppleAppStoreReviewsConnector(mocked_request)
        mapping = {
            'external_key': 'https://apps.apple.com/us/app/example/id12345',
            'expected_name': 'Example App',
        }
        with patch.dict('os.environ', {'APP_STORE_CONNECT_TOKEN': 'test-token'}):
            rows, cursor = connector.fetch_page(self.apple_source, self.grant, mapping)
        self.assertEqual(rows[0]['review_text'], 'Works\n\nAs expected')
        self.assertEqual(rows[0]['original_url'], mapping['external_key'])
        self.assertEqual(cursor, 'https://api.appstoreconnect.apple.com/v1/apps/12345/customerReviews?cursor=abc')
        self.assertEqual(requests[0][1], 'test-token')

    def test_apple_rejects_pagination_urls_outside_provider_api(self):
        connector = AppleAppStoreReviewsConnector(lambda *_: self.fail('must not request'))
        with patch.dict('os.environ', {'APP_STORE_CONNECT_TOKEN': 'test-token'}):
            with self.assertRaises(CollectionError):
                connector.fetch_page(
                    self.apple_source, self.grant,
                    {'external_key': '12345', 'expected_name': 'Example'},
                    'https://attacker.example/v1/apps/12345/customerReviews',
                )

    def test_api_connectors_require_a_matching_source_grant_and_credential(self):
        connector = GooglePlayReviewsConnector(lambda *_: self.fail('must not request'))
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(CollectionError) as missing:
                connector.fetch_page(
                    self.google_source, self.grant,
                    {'external_key': 'com.example.app', 'expected_name': 'Example'},
                )
        self.assertEqual(missing.exception.code, 'api_credentials_missing')
        with patch.dict('os.environ', {'GOOGLE_PLAY_ACCESS_TOKEN': 'test-token'}):
            with self.assertRaises(AccessDenied):
                connector.fetch_page(
                    dict(self.google_source, id='apple-app-store'),
                    self.grant,
                    {'external_key': 'com.example.app', 'expected_name': 'Example'},
                )
        self.assertEqual(
            ConnectorRegistry().get('authorized_api', self.google_source).source_id,
            'google-play',
        )


if __name__ == '__main__':
    unittest.main()
