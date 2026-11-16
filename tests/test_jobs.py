import unittest
import uuid
from contextlib import nullcontext
from unittest.mock import patch

from veriflow.connectors import CollectionError
from veriflow.jobs import _eligible_targets, run_one_collection_page, start_job


class _Result:
    def __init__(self, rows=None, row=None):
        self.rows = rows or []
        self.row = row

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.row


class _NoEligibleDatabase:
    def __init__(self):
        self.job_id = uuid.UUID('00000000-0000-4000-8000-000000000001')
        self.statements = []

    def transaction(self):
        return nullcontext()

    def execute(self, sql, params=()):
        self.statements.append(sql)
        if 'FROM veriflow.sources s' in sql:
            return _Result(rows=[])
        if 'INSERT INTO veriflow.collection_jobs' in sql:
            return _Result(row={'id':self.job_id})
        if 'FROM veriflow.collection_job_items WHERE job_id=%s' in sql and 'item_count' in sql:
            return _Result(row={'item_count':0,'terminal':0,'completed':0,'failed':0,
                                'pages':0,'retrieved':0,'inserted':0,'duplicates':0})
        if 'GROUP BY source_id HAVING' in sql:
            return _Result(row={'count':0})
        if 'UPDATE veriflow.collection_jobs SET' in sql:
            return _Result(row=None)
        raise AssertionError('Unexpected database operation')


class CollectionJobTests(unittest.TestCase):
    def test_authorized_api_source_and_scoped_product_are_eligible(self):
        external_key = 'com.example.app'
        row = {
            'source_id': 'google-play',
            'category': 'app_marketplace',
            'source_url': 'https://play.google.com',
            'enabled': True,
            'access_status': 'approved',
            'collection_method': 'authorized_api',
            'source_full_text_allowed': False,
            'required_license_id': None,
            'attribution_required': False,
            'authorization_id': uuid.UUID('00000000-0000-4000-8000-000000000001'),
            'grant_method': 'authorized_api',
            'product_keys': [external_key],
            'license_id': None,
            'terms_url': None,
            'grant_full_text_allowed': False,
            'expires_at': None,
            'product_id': uuid.UUID('00000000-0000-4000-8000-000000000002'),
            'external_key': external_key,
            'expected_name': 'Example App',
        }

        class EligibleDatabase:
            sql = ''

            def execute(self, sql, _params):
                self.sql = sql
                return _Result(rows=[row])

        conn = EligibleDatabase()
        targets = _eligible_targets(conn, 'all_eligible')
        self.assertIn("'authorized_api'", conn.sql)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]['source_id'], 'google-play')
        self.assertIsNone(targets[0]['start_url'])

    def test_authorized_api_job_uses_matching_grant_and_persists_next_cursor(self):
        source = {
            'id': 'google-play',
            'enabled': True,
            'access_status': 'approved',
            'collection_method': 'authorized_api',
        }
        external_key = 'com.example.app'
        item = {
            'id': uuid.UUID('00000000-0000-4000-8000-000000000003'),
            'job_id': uuid.UUID('00000000-0000-4000-8000-000000000004'),
            'source_id': 'google-play',
            'authorization_id': uuid.UUID('00000000-0000-4000-8000-000000000005'),
            'product_id': uuid.UUID('00000000-0000-4000-8000-000000000006'),
            'product_key': external_key,
            'cursor_url': None,
            'attempts': 1,
        }
        mapping = {'external_key': external_key, 'expected_name': 'Example App'}
        grant = {'product_keys': [external_key]}
        review_rows = [{
            'external_id': 'review-id',
            'product_key': external_key,
            'software_name': 'Example App',
            'review_text': None,
            'rating': 5,
            'rating_scale': 5,
            'published_at': '2026-01-01',
            'original_url': 'https://play.google.com/store/apps/details?id=com.example.app',
        }]

        class ApiConnector:
            def fetch_page(self, actual_source, actual_grant, actual_mapping, cursor):
                self.args = (actual_source, actual_grant, actual_mapping, cursor)
                return review_rows, 'pageToken:next'

        connector = ApiConnector()

        class Registry:
            def get(self, method, actual_source):
                self.args = (method, actual_source)
                return connector

        registry = Registry()

        class ApiJobDatabase:
            def __init__(self):
                self.updated_item = None

            def transaction(self):
                return nullcontext()

            def execute(self, sql, params=()):
                if 'WITH candidate AS' in sql:
                    return _Result(row=item)
                if 'SELECT * FROM veriflow.sources' in sql:
                    return _Result(row=source)
                if 'SELECT * FROM veriflow.source_products' in sql:
                    return _Result(row=mapping)
                if 'UPDATE veriflow.collection_job_items SET state=%s,cursor_url=%s' in sql:
                    self.updated_item = params
                    return _Result(row=None)
                if 'SELECT count(*) AS item_count' in sql:
                    return _Result(row={
                        'item_count': 1, 'terminal': 0, 'completed': 0, 'failed': 0,
                        'pages': 1, 'retrieved': 1, 'inserted': 0, 'duplicates': 0,
                    })
                if 'GROUP BY source_id HAVING bool_and' in sql:
                    return _Result(row={'count': 0})
                return _Result(row=None)

        conn = ApiJobDatabase()
        with patch('veriflow.jobs.CONNECTORS', registry), \
                patch('veriflow.jobs.authorization', return_value=grant) as authorize, \
                patch('veriflow.worker.enqueue', return_value='batch-id') as enqueue:
            result = run_one_collection_page(conn)

        authorize.assert_called_once_with(
            conn, 'google-play', item['authorization_id'], 'authorized_api'
        )
        self.assertEqual(registry.args, ('authorized_api', source))
        self.assertEqual(connector.args, (source, grant, mapping, None))
        enqueue.assert_called_once()
        self.assertEqual(conn.updated_item[1], 'pageToken:next')
        self.assertEqual(result['state'], 'awaiting_ingest')

    def test_invalid_product_id_fails_before_database_access(self):
        with self.assertRaises(CollectionError):
            start_job(None,'product',product_id='not-a-product-id')

    def test_research_category_cannot_start_a_review_job(self):
        with self.assertRaises(CollectionError):
            start_job(None,'category',category='market_research')

    def test_empty_eligibility_is_recorded_without_fabricating_sources(self):
        conn = _NoEligibleDatabase()
        result = start_job(conn,'all_eligible')
        self.assertEqual(result['state'],'failed')
        self.assertEqual(result['eligible_sources'],0)
        self.assertEqual(result['eligible_products'],0)
        self.assertEqual(result['error_code'],'no_eligible_sources')
        self.assertTrue(any('INSERT INTO veriflow.collection_jobs' in sql for sql in conn.statements))
        self.assertFalse(any('INSERT INTO veriflow.collection_job_items' in sql for sql in conn.statements))


if __name__ == '__main__':
    unittest.main()
