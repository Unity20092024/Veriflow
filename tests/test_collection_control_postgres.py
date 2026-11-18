"""Opt-in LOCAL PostgreSQL checks. Never accepts a remote database endpoint.

VERIFLOW_LOCAL_OPS_DSN must point to postgres on 127.0.0.1:55432. An empty,
uniquely named logical database is created; existing databases are never reset.
Existing test-cluster roles must already exist; no login/password is changed.
"""
import json
import os
from pathlib import Path
import re
import unittest
import uuid
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from tests import test_database
from tests.test_connectors import fixture
from veriflow.bounded_collection import BATCH_ID, tick, stop
from veriflow.collection_control import control
from veriflow.connectors import AccessDenied
from veriflow.jobs import _refresh_job, run_one_collection_page
from veriflow.worker import enqueue, run_one
from veriflow.worker_runtime import WORKER_LOCK, run_cycle


@unittest.skipUnless(os.environ.get('VERIFLOW_LOCAL_OPS_DSN'), 'Opt-in local disposable PostgreSQL only')
class LocalOperationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = conninfo_to_dict(os.environ['VERIFLOW_LOCAL_OPS_DSN'])
        if (config.get('host') != '127.0.0.1' or config.get('port') != '55432'
                or config.get('dbname') != 'postgres' or config.get('user') != 'postgres'
                or config.get('hostaddr') or config.get('service')):
            raise RuntimeError('Refusing non-local test cluster')
        owner = psycopg.connect(**config, autocommit=True, row_factory=dict_row)
        cls.db_name = 'veriflow_ops_' + uuid.uuid4().hex
        try:
            roles = {r['rolname'] for r in owner.execute('SELECT rolname FROM pg_roles')}
            if not {'veriflow_runtime', 'veriflow_app', 'veriflow_test_login',
                    'anon', 'authenticated'} <= roles:
                raise RuntimeError('Pre-existing local test roles required')
            owner.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.db_name)))
        finally:
            owner.close()
        config['dbname'] = cls.db_name
        cls.url = psycopg.conninfo.make_conninfo(**config)
        cls.admin = psycopg.connect(cls.url, autocommit=True, row_factory=dict_row)
        for migration in sorted(Path('supabase/migrations').glob('*.sql')):
            # Roles are cluster-wide and already present. Apply only database-local DDL.
            content = re.sub(r'^CREATE ROLE .*;\n', '', migration.read_text(), flags=re.M)
            content = re.sub(r'^GRANT veriflow_runtime TO veriflow_app;\n', '', content, flags=re.M)
            cls.admin.execute(content)

    @classmethod
    def tearDownClass(cls):
        cls.admin.close()
        # Retain this uniquely named synthetic test DB for inspection. Never drop
        # or truncate an existing database as test cleanup.

    setUp = test_database.DatabaseTests.setUp
    tearDown = test_database.DatabaseTests.tearDown

    def job(self, cursor='next-page', state='awaiting_ingest'):
        job = self.conn.execute("INSERT INTO veriflow.collection_jobs(scope,state) "
                                "VALUES ('all_eligible','running') RETURNING id").fetchone()['id']
        item = self.conn.execute('''INSERT INTO veriflow.collection_job_items
            (job_id,source_id,product_id,product_key,authorization_id,state,cursor_url,pages_fetched)
            VALUES (%s,%s,%s,'test-product',%s,%s,%s,1) RETURNING id''',
            (job, self.source, self.product, self.grant, state, cursor)).fetchone()['id']
        self.conn.commit()
        return job, item

    def queue(self, item=None):
        batch = enqueue(self.conn, self.source, self.grant, json.dumps([fixture()]), 'json',
                        collection_job_item_id=item)
        self.conn.commit()
        return batch

    def test_stop_preserves_cursor_and_pending_import_until_same_job_resumes(self):
        job, item = self.job()
        batch = self.queue(item)
        before = self.conn.execute('SELECT * FROM veriflow.collection_job_items WHERE id=%s', (item,)).fetchone()
        control(self.conn, 'stop', job_id=job)
        self.conn.commit()
        run_one(self.conn)
        self.conn.commit()
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM veriflow.reviews').fetchone()['n'], 0)
        self.assertEqual(self.conn.execute('SELECT status FROM veriflow.import_batches WHERE id=%s', (batch,)).fetchone()['status'], 'pending')
        self.assertEqual(before, self.conn.execute('SELECT * FROM veriflow.collection_job_items WHERE id=%s', (item,)).fetchone())
        control(self.conn, 'resume', job_id=job)
        self.conn.commit()
        # Simulate process replacement with a new independent DB session.
        self.conn.close()
        self.conn = psycopg.connect(self.url, row_factory=dict_row)
        self.conn.execute('SET ROLE veriflow_test_login')
        self.assertEqual(run_one(self.conn)['inserted'], 1)
        self.conn.commit()
        saved = self.conn.execute('SELECT state,cursor_url FROM veriflow.collection_job_items WHERE id=%s', (item,)).fetchone()
        self.assertEqual(saved, dict(state='queued', cursor_url='next-page'))
        self.queue()  # Replay same synthetic record after restart: native unique constraints protect it.
        self.conn.execute('UPDATE veriflow.sources SET next_run_at=now() WHERE id=%s', (self.source,))
        self.assertEqual(run_one(self.conn)['duplicates'], 1)
        self.conn.commit()
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM veriflow.reviews').fetchone()['n'], 1)

    def test_stopped_import_poll_does_not_change_source_schedule(self):
        job, item = self.job()
        self.queue(item)
        control(self.conn, 'stop', job_id=job)
        self.conn.commit()
        before = self.admin.execute('SELECT * FROM veriflow.sources WHERE id=%s', (self.source,)).fetchone()
        self.assertIsNone(run_one(self.conn))
        self.conn.commit()
        self.assertEqual(before, self.admin.execute('SELECT * FROM veriflow.sources WHERE id=%s', (self.source,)).fetchone())
        control(self.conn, 'resume', job_id=job)
        self.conn.commit()
        self.assertEqual(run_one(self.conn)['inserted'], 1)

    def test_resume_recovers_legacy_idle_deferral_without_timestamp_reset(self):
        job, item = self.job()
        self.queue(item)
        # Reproduce a persisted row left by the previous worker's idle polling.
        self.conn.execute("""UPDATE veriflow.sources SET last_status='idle',
            last_run_at=now()-interval '2 minutes',next_run_at=now()-interval '2 minutes'+
              greatest(schedule_seconds,minimum_interval_seconds)*interval '1 second'
            WHERE id=%s""", (self.source,))
        control(self.conn, 'stop', job_id=job)
        self.conn.commit()
        control(self.conn, 'resume', job_id=job)
        self.conn.commit()
        self.assertEqual(run_one(self.conn)['inserted'], 1)

    def test_resume_preserves_real_rate_limit_error_and_success_schedules(self):
        job, item = self.job()
        self.queue(item)
        for status in ('rate_limited', 'error', 'success', 'idle'):
            with self.subTest(status=status):
                self.conn.execute('''UPDATE veriflow.sources SET last_status=%s,
                    last_run_at=now()-interval '2 hours',next_run_at=now()+interval '1 hour'
                    WHERE id=%s''', (status, self.source))
                control(self.conn, 'stop', job_id=job)
                self.conn.commit()
                before = self.admin.execute('SELECT * FROM veriflow.sources WHERE id=%s', (self.source,)).fetchone()
                control(self.conn, 'resume', job_id=job)
                self.conn.commit()
                self.assertIsNone(run_one(self.conn))
                self.conn.commit()
                self.assertEqual(before, self.admin.execute('SELECT * FROM veriflow.sources WHERE id=%s', (self.source,)).fetchone())
        self.assertEqual(self.admin.execute('SELECT count(*) AS n FROM veriflow.reviews').fetchone()['n'], 0)

    def test_legacy_idle_recovery_preserves_minimum_interval(self):
        self.queue()
        self.conn.execute("""UPDATE veriflow.sources SET last_status='idle',
            last_run_at=now(),next_run_at=now()+interval '1 day' WHERE id=%s""", (self.source,))
        self.conn.commit()
        before = self.admin.execute('SELECT * FROM veriflow.sources WHERE id=%s', (self.source,)).fetchone()
        self.assertIsNone(run_one(self.conn))
        self.conn.commit()
        self.assertEqual(before, self.admin.execute('SELECT * FROM veriflow.sources WHERE id=%s', (self.source,)).fetchone())

    def test_stopped_source_does_not_starve_other_eligible_sources(self):
        job, item = self.job()
        self.queue(item)
        control(self.conn, 'stop', job_id=job)
        self.conn.execute("UPDATE veriflow.sources SET enabled=true,access_status='approved',full_text_allowed=true WHERE id='g2'")
        self.conn.execute("INSERT INTO veriflow.source_products VALUES ('g2','g2-test',%s,'Test Product')", (self.product,))
        grant = self.conn.execute('''INSERT INTO veriflow.authorizations
            (source_id,method,evidence,product_keys,full_text_allowed,approved_by,expires_at)
            VALUES ('g2','approved_import','SYNTHETIC LOCAL ONLY',ARRAY['g2-test'],true,
                    'fixture',now()+interval '1 day') RETURNING id''').fetchone()['id']
        row = fixture()
        row.update(product_key='g2-test', original_url='https://g2.com/reviews/test')
        enqueue(self.conn, 'g2', grant, json.dumps([row]), 'json')
        self.conn.commit()
        result = run_one(self.conn)
        self.assertEqual(result['source'], 'g2')
        self.assertEqual(result['inserted'], 1)

    def test_resumed_idle_import_still_requires_current_authorization(self):
        job, item = self.job()
        self.queue(item)
        control(self.conn, 'stop', job_id=job)
        self.conn.execute("UPDATE veriflow.authorizations SET revoked_at=now() WHERE id=%s", (self.grant,))
        self.conn.execute("""UPDATE veriflow.sources SET last_status='idle',
            last_run_at=now()-interval '2 minutes',next_run_at=now()-interval '2 minutes'+
              greatest(schedule_seconds,minimum_interval_seconds)*interval '1 second'
            WHERE id=%s""", (self.source,))
        self.conn.commit()
        control(self.conn, 'resume', job_id=job)
        self.conn.commit()
        self.assertEqual(run_one(self.conn)['error_code'], 'access_denied')
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM veriflow.reviews').fetchone()['n'], 0)

    def test_rollback_then_retry_inserts_exactly_once(self):
        self.queue()
        self.assertEqual(run_one(self.conn)['inserted'], 1)
        self.conn.rollback()  # Equivalent database effect of process death before commit.
        self.conn.close()
        self.conn = psycopg.connect(self.url, row_factory=dict_row)
        self.conn.execute('SET ROLE veriflow_test_login')
        self.assertEqual(run_one(self.conn)['inserted'], 1)
        self.conn.commit()
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM veriflow.reviews').fetchone()['n'], 1)

    def test_completed_job_is_not_reclaimed_or_resumed(self):
        job, item = self.job(cursor=None, state='completed')
        _refresh_job(self.conn, job)
        self.conn.commit()
        with self.assertRaises(AccessDenied):
            control(self.conn, 'resume', job_id=job)
        self.assertIsNone(run_one_collection_page(self.conn))
        self.assertEqual(self.conn.execute('SELECT state FROM veriflow.collection_jobs WHERE id=%s', (job,)).fetchone()['state'], 'completed')

    def test_late_refresh_cannot_reopen_paused_parent(self):
        job, item = self.job()
        control(self.conn, 'pause', job_id=job)
        _refresh_job(self.conn, job)
        row = self.conn.execute('SELECT state,error_code FROM veriflow.collection_jobs WHERE id=%s', (job,)).fetchone()
        self.assertEqual(row, dict(state='cancelled', error_code='operator_paused'))

    def test_collection_dashboard_renders_existing_start_and_checkpoint_controls(self):
        from veriflow.admin import page
        job, item = self.job()
        control(self.conn, 'pause', job_id=job)
        self.conn.commit()
        body = page(self.conn, '/collection', {}, 'fixture-csrf')
        for action in ('start', 'pause', 'stop', 'resume'):
            self.assertIn('/collection/' + action, body)
        self.assertIn('paused', body)
        self.assertIn('breadth_first', body)
        reviews = page(self.conn, '/reviews', {}, 'fixture-csrf')
        for extension in ('csv', 'xlsx', 'json', 'jsonl'):
            self.assertIn('/exports/reviews.' + extension, reviews)

    def crawl_fixture(self):
        self.conn.execute("UPDATE veriflow.sources SET collection_method='permitted_crawl' WHERE id=%s", (self.source,))
        self.conn.execute("UPDATE veriflow.authorizations SET method='permitted_crawl' WHERE id=%s", (self.grant,))
        job, item = self.job(cursor='saved-page', state='fetching')
        self.conn.execute("UPDATE veriflow.collection_job_items SET lease_until=now()-interval '1 second' WHERE id=%s", (item,))
        self.conn.commit()
        return job, item

    def test_expired_fetch_lease_recovers_saved_cursor_then_completes(self):
        job, item = self.crawl_fixture()
        with patch('veriflow.jobs.extract_page', return_value={'records': [], 'next_url': 'following-page'}) as extract:
            result = run_one_collection_page(self.conn)
        self.conn.commit()
        self.assertEqual(extract.call_args.args[-1], 'saved-page')
        self.assertEqual(result['state'], 'queued')
        self.conn.close()
        self.conn = psycopg.connect(self.url, row_factory=dict_row)
        self.conn.execute('SET ROLE veriflow_test_login')
        with patch('veriflow.jobs.extract_page', return_value={'records': [], 'next_url': None}) as extract:
            result = run_one_collection_page(self.conn)
        self.conn.commit()
        self.assertEqual(extract.call_args.args[-1], 'following-page')
        self.assertEqual(result['job_state'], 'completed')
        self.assertIsNone(run_one_collection_page(self.conn))

    def test_stop_during_http_checkpoints_page_without_reopening_parent(self):
        job, item = self.crawl_fixture()
        def in_flight(*args):
            with psycopg.connect(self.url, row_factory=dict_row) as operator:
                operator.execute('SET ROLE veriflow_test_login')
                control(operator, 'stop', job_id=job)
            return {'records': [], 'next_url': 'following-page'}
        with patch('veriflow.jobs.extract_page', side_effect=in_flight):
            result = run_one_collection_page(self.conn)
        self.conn.commit()
        self.assertEqual(result['job_state'], 'cancelled')
        parent = self.conn.execute('SELECT state,error_code FROM veriflow.collection_jobs WHERE id=%s', (job,)).fetchone()
        saved = self.conn.execute('SELECT state,cursor_url FROM veriflow.collection_job_items WHERE id=%s', (item,)).fetchone()
        self.assertEqual(parent, dict(state='cancelled', error_code='operator_stopped'))
        self.assertEqual(saved, dict(state='queued', cursor_url='following-page'))
        with patch('veriflow.jobs.extract_page') as transport:
            self.assertIsNone(run_one_collection_page(self.conn))
        transport.assert_not_called()

    def test_free_batch_stop_preserves_limits_and_blocks_pending_ingest(self):
        self.conn.execute('''INSERT INTO veriflow.free_batches(id,authorization_id,requests)
                             VALUES (%s,%s,7)''', (BATCH_ID, self.grant))
        self.conn.commit()
        self.queue()
        before = self.conn.execute('SELECT requests,started_at,expires_at FROM veriflow.free_batches').fetchone()
        control(self.conn, 'stop', batch_id=BATCH_ID)
        self.conn.commit()
        with patch('veriflow.bounded_collection.client_for') as transport:
            tick(self.conn)
        transport.assert_not_called()
        run_one(self.conn)
        self.conn.commit()
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM veriflow.reviews').fetchone()['n'], 0)
        stop(self.conn, 'limited', 'late_callback')
        control(self.conn, 'resume', batch_id=BATCH_ID)
        self.conn.commit()
        self.assertEqual(before, self.conn.execute('SELECT requests,started_at,expires_at FROM veriflow.free_batches').fetchone())

    def test_global_worker_lock_uses_real_session_ownership(self):
        self.conn.execute('SELECT pg_advisory_lock(%s)', (WORKER_LOCK,))
        self.conn.commit()
        with psycopg.connect(self.url, row_factory=dict_row) as other:
            with patch('veriflow.worker.run_one') as ingest:
                self.assertEqual(run_cycle(other), [])
                ingest.assert_not_called()
        self.conn.close()  # Session loss automatically frees ownership.
        self.conn = psycopg.connect(self.url, row_factory=dict_row)
        self.conn.execute('SET ROLE veriflow_test_login')
        with patch('veriflow.worker.run_one', return_value=None) as ingest, \
                patch('veriflow.jobs.run_one_collection_page', return_value=None), \
                patch('veriflow.bounded_collection.tick', return_value=None):
            self.assertEqual(run_cycle(self.conn), [])
            ingest.assert_called_once_with(self.conn)
