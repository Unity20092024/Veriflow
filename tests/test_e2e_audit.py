"""Audit-only local HTTP -> worker -> PostgreSQL tests; no live source calls."""
import base64
import csv
import io
import json
import os
import re
import threading
import unittest
import zipfile
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler
from xml.etree import ElementTree

import psycopg
from psycopg.rows import dict_row
from psycopg import sql
from veriflow import admin
from veriflow.mangrove_live import SOURCE_DEFINITION
from veriflow.worker_runtime import run_cycle
from tests import test_collection_control_postgres as local_ops
from tests import test_database
from tests.test_mangrove_worker import entry


@unittest.skipUnless(os.environ.get('VERIFLOW_LOCAL_OPS_DSN'), 'Local disposable database only')
class LocalHttpAudit(unittest.TestCase):
    setUpClass = classmethod(local_ops.LocalOperationsTests.setUpClass.__func__)
    tearDownClass = classmethod(local_ops.LocalOperationsTests.tearDownClass.__func__)

    def connect(self):
        conn = psycopg.connect(self.url, row_factory=dict_row)
        conn.execute('SET ROLE veriflow_test_login')
        conn.commit()
        return conn

    def setUp(self):
        test_database.DatabaseTests.setUp(self)
        self.admin.execute('UPDATE veriflow.sources SET enabled=false')
        definition = dict(SOURCE_DEFINITION, enabled=True, access_status='approved',
                          full_text_allowed=True, provenance='SYNTHETIC LOCAL TEST ONLY')
        self.conn.execute(sql.SQL('INSERT INTO veriflow.sources ({}) VALUES ({})').format(
            sql.SQL(',').join(map(sql.Identifier, definition)),
            sql.SQL(',').join(sql.Placeholder() for _ in definition)), list(definition.values()))
        self.conn.execute("UPDATE veriflow.products SET name='Bitwarden' WHERE id=%s", (self.product,))
        self.conn.execute("INSERT INTO veriflow.source_products VALUES ('mangrove-reviews','https://bitwarden.com',%s,'Bitwarden')", (self.product,))
        self.conn.execute("""INSERT INTO veriflow.authorizations
            (source_id,method,evidence,product_keys,full_text_allowed,approved_by,expires_at,license_id,terms_url)
            VALUES ('mangrove-reviews','authorized_api','SYNTHETIC LOCAL TEST ONLY',
              ARRAY['https://bitwarden.com'],true,'fixture',now()+interval '1 day',
              'CC-BY-4.0','https://mangrove.reviews/terms')""")
        self.conn.commit()
        self.policy = patch('veriflow.mangrove_live.MangroveClient.verify_policy', return_value='fixture-policy')
        self.page = patch('veriflow.mangrove_live.MangroveClient.page', return_value=[entry('A'*86)])
        self.policy.start()
        self.transport = self.page.start()
        self.addCleanup(self.policy.stop)
        self.addCleanup(self.page.stop)
        self.server_ready = threading.Event()
        def factory(address, handler):
            self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
            self.server_ready.set()
            return self.server
        self.server_patch = patch('veriflow.admin.ThreadingHTTPServer', side_effect=factory)
        self.database_patch = patch('veriflow.admin.connect', side_effect=self.connect)
        self.env_patch = patch.dict(os.environ, {'ADMIN_USERNAME':'fixture',
                                                'ADMIN_PASSWORD':'SYNTHETIC-local-password-only'}, clear=True)
        for p in (self.server_patch, self.database_patch, self.env_patch):
            p.start()
            self.addCleanup(p.stop)
        self.thread = threading.Thread(target=admin.serve, daemon=True)
        self.thread.start()
        if not self.server_ready.wait(3):
            raise RuntimeError('Local HTTP fixture did not start')
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)
        self.opener = build_opener(ProxyHandler({}))  # Never proxy local test traffic.
        self.auth = 'Basic '+base64.b64encode(b'fixture:SYNTHETIC-local-password-only').decode()
        self.csrf = re.search('name="csrf" value="([a-f0-9]+)"', self.request('/collection').decode()).group(1)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.conn.close()

    def request(self, path, data=None, authorized=True):
        headers = {'Authorization': self.auth} if authorized else {}
        if data is not None:
            headers.update({'Origin':self.base, 'Content-Type':'application/x-www-form-urlencoded'})
        request = Request(self.base+path, headers=headers,
                          data=urlencode(data).encode() if data is not None else None)
        with self.opener.open(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
            return response.read()

    def start(self):
        self.request('/collection/start', dict(csrf=self.csrf,scope='product',product_id=str(self.product),
                                              strategy='breadth_first',target_reviews='1'))
        return self.admin.execute('SELECT id FROM veriflow.collection_jobs').fetchone()['id']

    def action(self, action, job):
        self.request('/collection/'+action, dict(csrf=self.csrf,job_id=str(job)))

    def cycle(self):
        with self.connect() as conn:
            return run_cycle(conn)

    def count(self):
        return self.admin.execute('SELECT count(*) AS n FROM veriflow.reviews').fetchone()['n']

    def test_start_worker_ingest_all_exports_and_completed_protection(self):
        with self.assertRaises(HTTPError) as error:
            self.request('/sources', authorized=False)
        self.assertEqual(error.exception.code, 401)
        job = self.start()
        self.cycle()  # Actual source adapter with synthetic transport -> durable pending import.
        self.cycle()  # Actual ingestion -> PostgreSQL and license row.
        self.assertEqual(self.count(), 1)
        license = self.admin.execute('SELECT license_id,attribution_url FROM veriflow.review_licenses').fetchone()
        self.assertEqual(license['license_id'], 'CC-BY-4.0')
        self.assertTrue(license['attribution_url'].startswith('https://api.mangrove.reviews/review/'))
        query='?product='+str(self.product)
        for extension in ('csv','xlsx','json','jsonl'):
            with self.assertRaises(HTTPError) as error:
                self.request('/exports/reviews.'+extension+query, authorized=False)
            self.assertEqual(error.exception.code, 401)
        csv_rows=list(csv.DictReader(io.StringIO(self.request('/exports/reviews.csv'+query).decode('utf-8-sig'))))
        self.assertEqual(len(csv_rows), 1)
        self.assertEqual(csv_rows[0]['license_id'], 'CC-BY-4.0')
        self.assertEqual(len(json.loads(self.request('/exports/reviews.json'+query))), 1)
        self.assertEqual(len([json.loads(line) for line in self.request('/exports/reviews.jsonl'+query).splitlines()]), 1)
        with zipfile.ZipFile(io.BytesIO(self.request('/exports/reviews.xlsx'+query))) as workbook:
            root=ElementTree.fromstring(workbook.read('xl/worksheets/sheet1.xml'))
            self.assertEqual(len(root.findall('.//{*}row')), 2)
        calls=self.transport.call_count
        with self.assertRaises(HTTPError) as error:
            self.action('resume', job)
        self.assertEqual(error.exception.code, 400)
        self.cycle()
        self.assertEqual(self.transport.call_count, calls)
        self.assertEqual(self.count(), 1)

    def test_stop_pending_import_then_resume_progress_without_manual_db_edits(self):
        job = self.start()
        self.action('pause', job)
        self.cycle()
        self.transport.assert_not_called()
        self.action('resume', job)
        self.cycle()
        self.assertEqual(self.admin.execute("SELECT count(*) n FROM veriflow.import_batches WHERE status='pending'").fetchone()['n'], 1)
        self.action('stop', job)
        self.cycle()
        self.assertEqual(self.count(), 0)
        self.action('resume', job)
        self.cycle()
        # Resume should not require an operator to rewrite source next_run_at.
        delay = self.admin.execute("SELECT extract(epoch FROM next_run_at-now()) AS seconds FROM veriflow.sources WHERE id='mangrove-reviews'").fetchone()['seconds']
        self.assertEqual(self.count(), 1, 'Pending import deferred %.0f seconds after Resume' % delay)
