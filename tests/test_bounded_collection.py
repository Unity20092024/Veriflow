import json
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from veriflow.bounded_collection import (
    BATCH_ID, BatchLimit, activate, permitted_candidate, reserve_http, tick,
)
from veriflow.exports import render_jsonl, render_csv, render_xlsx, HEADERS
import io
import csv
import zipfile
from xml.etree import ElementTree as ET


class Transaction:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class BoundedCollectionTests(unittest.TestCase):
    def test_reservation_charged_before_transport_and_refuses_exhausted_budget(self):
        conn = Mock()
        conn.transaction.side_effect = Transaction
        now = datetime.now(timezone.utc)
        conn.execute.return_value.fetchone.side_effect = [
            {'state': 'running', 'next_http_at': now, 'db_now': now}, None, None,
        ]
        with self.assertRaises(BatchLimit):
            reserve_http(conn)
        reservation = conn.execute.call_args_list[-2]
        sql = reservation.args[0]
        self.assertIn('requests<max_requests', sql)
        self.assertIn('expires_at>now()', sql)
        self.assertIn("state='running'", sql)
        self.assertIn("interval '1 second'", sql)
        self.assertEqual(reservation.args[1][0], 3)

    def test_unique_limit_stops_without_network(self):
        conn = Mock()
        conn.transaction.side_effect = Transaction
        conn.execute.return_value.fetchone.side_effect = [
            {'acquired': True}, None,
        ]
        with patch('veriflow.bounded_collection.progress', return_value={
                'state': 'running', 'new_unique_reviews': 500}), \
                patch('veriflow.bounded_collection.client_for') as client, \
                patch('veriflow.bounded_collection.stop') as stop:
            result = tick(conn)
        stop.assert_called_once_with(conn, 'limited', 'unique_review_limit')
        client.assert_not_called()
        self.assertEqual(result['state'], 'limited')

    def test_restart_activation_never_renews_previous_expiry_or_counters(self):
        conn = Mock()
        conn.transaction.side_effect = Transaction
        conn.execute.return_value.fetchone.return_value = {'id': BATCH_ID, 'state': 'completed'}
        self.assertTrue(activate(conn)['already_activated'])
        for call in conn.execute.call_args_list:
            self.assertNotIn('UPDATE', call.args[0])
            self.assertNotIn('INSERT', call.args[0])

    def test_pending_import_prevents_another_unique_reservation(self):
        conn = Mock()
        conn.transaction.side_effect = Transaction
        conn.execute.return_value.fetchone.side_effect = [
            {'acquired': True}, {'id': 1, 'status': 'pending'},
        ]
        with patch('veriflow.bounded_collection.progress', return_value={
                'state': 'running', 'new_unique_reviews': 499}), \
                patch('veriflow.bounded_collection.client_for') as client:
            self.assertIsNone(tick(conn))
        client.assert_not_called()

    def test_expired_original_deadline_stops_before_network(self):
        from datetime import timedelta
        conn = Mock()
        conn.transaction.side_effect = Transaction
        conn.execute.return_value.fetchone.side_effect = [{'acquired': True}, None]
        with patch('veriflow.bounded_collection.progress', return_value={
                'state': 'running', 'new_unique_reviews': 10,
                'expires_at': datetime.now(timezone.utc)-timedelta(seconds=1)}), \
                patch('veriflow.bounded_collection.client_for') as client, \
                patch('veriflow.bounded_collection.stop') as stop:
            tick(conn)
        stop.assert_called_once_with(conn, 'expired', 'original_48_hour_limit')
        client.assert_not_called()

    def test_unknown_software_classification_excluded(self):
        self.assertFalse(permitted_candidate({'name': 'Book', 'category': None}))
        self.assertFalse(permitted_candidate({'name': 'Libre Game Night', 'category': 'Software'}))
        self.assertTrue(permitted_candidate({'name': 'Mozilla Firefox', 'category': 'Web browsers'}))

    def test_unsupported_search_link_is_not_followed_or_allowed_to_hide_valid_matches(self):
        from veriflow.libreviews_live import PublicPages
        parser = PublicPages(skip_unsupported_search_links=True)
        parser.feed('<h3 class="search-match-heading"><a href="/invalid/subject/path">Ignore</a></h3>'
                    '<h3 class="search-match-heading"><a href="/mozilla-firefox">Firefox</a></h3>')
        self.assertEqual(parser.products[0]['url'], '')
        self.assertEqual(parser.products[1]['url'], 'https://lib.reviews/mozilla-firefox')

    def test_500_row_export_formats_offline_only(self):
        # Synthetic format fixtures only: never imported into any database.
        rows = [dict.fromkeys(HEADERS) for _ in range(500)]
        for index, row in enumerate(rows):
            row.update(review_id=str(index), product='Format fixture',
                       review_text='=formula\nUnicode ✓', public_credit='Fixture author',
                       license_id='CC-BY-SA-4.0')
        self.assertEqual(len([json.loads(line) for line in render_jsonl(rows).splitlines()]), 500)
        parsed = list(csv.DictReader(io.StringIO(render_csv(rows).decode('utf-8-sig'))))
        self.assertEqual(len(parsed), 500)
        self.assertTrue(parsed[0]['review_text'].startswith("'="))
        with zipfile.ZipFile(io.BytesIO(render_xlsx(rows))) as workbook:
            root = ET.fromstring(workbook.read('xl/worksheets/sheet1.xml'))
            self.assertEqual(len(root.findall('.//{*}row')), 501)
            self.assertEqual(root.findall('.//{*}f'), [])
