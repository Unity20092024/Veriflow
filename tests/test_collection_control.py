"""Offline checks for operator controls and worker ownership; no collection."""
import base64
import hashlib
import hmac
import io
import os
import unittest
import uuid
from contextlib import nullcontext
from email.message import Message
from unittest.mock import Mock, patch
from urllib.parse import urlencode

from veriflow.collection_control import control, import_allowed
from veriflow.connectors import AccessDenied, CollectionError
from veriflow.worker_runtime import run_cycle


class ControlTests(unittest.TestCase):
    def connection(self, state='running', error=None, expired=False):
        conn = Mock()
        conn.transaction.side_effect = nullcontext
        conn.execute.return_value.fetchone.return_value = dict(
            id='fixture', state=state, error_code=error, expired=expired)
        return conn

    def test_stop_pause_and_resume_only_change_control_metadata(self):
        for action, state, error in [('pause', 'running', None),
                                     ('stop', 'running', None),
                                     ('resume', 'cancelled', 'operator_paused'),
                                     ('resume', 'cancelled', 'operator_stopped')]:
            with self.subTest(action=action, error=error):
                conn = self.connection(state, error)
                control(conn, action, job_id=str(uuid.uuid4()))
                sql = conn.execute.call_args.args[0]
                self.assertIn('SET state=%s,error_code=%s,updated_at=now()', sql)
                for field in ('cursor_url=', 'attempts=', 'created_at=', 'expires_at=',
                              'requests=', 'authorization_id=', 'target_reviews='):
                    self.assertNotIn(field, sql)

    def test_terminal_and_policy_stopped_jobs_cannot_resume(self):
        for state in ('completed', 'partial', 'failed', 'cancelled'):
            with self.subTest(state=state):
                conn = self.connection(state)
                with self.assertRaises(AccessDenied):
                    control(conn, 'resume', job_id=str(uuid.uuid4()))
                self.assertEqual(conn.execute.call_count, 1)

    def test_deadline_is_not_renewed_by_resume(self):
        with self.assertRaises(AccessDenied):
            control(self.connection('cancelled', 'operator_paused', True),
                    'resume', job_id=str(uuid.uuid4()))

    def test_invalid_selection_never_touches_database(self):
        conn = self.connection()
        for args in ({}, {'job_id': 'invalid'},
                     {'job_id': str(uuid.uuid4()), 'batch_id': 'anything'}):
            with self.assertRaises(CollectionError):
                control(conn, 'resume', **args)
        conn.execute.assert_not_called()

    def test_only_original_free_batch_can_be_controlled(self):
        with self.assertRaises(AccessDenied):
            control(self.connection(), 'pause', batch_id='other-batch')

    def test_pending_import_from_stopped_parent_is_not_ingested(self):
        conn = self.connection('cancelled', 'operator_stopped')
        self.assertFalse(import_allowed(conn, dict(collection_job_item_id='fixture')))
        self.assertIn('FOR SHARE', conn.execute.call_args.args[0])

    def test_pending_free_batch_import_obeys_pause(self):
        conn = self.connection()
        conn.execute.return_value.fetchall.return_value = [
            dict(state='blocked', error_code='operator_paused')]
        self.assertFalse(import_allowed(conn, dict(authorization_id='fixture')))

    def test_second_worker_skips_entire_cycle(self):
        conn = self.connection()
        conn.execute.return_value.fetchone.return_value = {'acquired': False}
        with patch('veriflow.worker.run_one') as ingest:
            self.assertEqual(run_cycle(conn), [])
        ingest.assert_not_called()

    def test_single_session_owns_all_three_worker_phases(self):
        conn = self.connection()
        conn.closed = False
        conn.execute.return_value.fetchone.return_value = {'acquired': True}
        with patch('veriflow.worker.run_one', return_value={'ingest': True}) as ingest, \
                patch('veriflow.jobs.run_one_collection_page', return_value=None) as fetch, \
                patch('veriflow.bounded_collection.tick', return_value=None) as batch:
            self.assertEqual(run_cycle(conn), [{'ingest': True}])
        for operation in (ingest, fetch, batch):
            operation.assert_called_once_with(conn)
        self.assertIn('pg_advisory_unlock', conn.execute.call_args.args[0])

    def test_worker_failure_releases_lock(self):
        conn = self.connection()
        conn.closed = False
        conn.execute.return_value.fetchone.return_value = {'acquired': True}
        with patch('veriflow.worker.run_one', side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError):
                run_cycle(conn)
        self.assertIn('pg_advisory_unlock', conn.execute.call_args.args[0])


class DashboardControlTests(unittest.TestCase):
    def setUp(self):
        from veriflow.admin import serve
        self.username, self.password = 'fixture', 'fixture-password-only-24-characters'
        with patch.dict(os.environ, ADMIN_USERNAME=self.username, ADMIN_PASSWORD=self.password), \
                patch('veriflow.config.load_environment'), \
                patch('veriflow.admin.ThreadingHTTPServer') as server:
            serve()
        self.handler_class = server.call_args.args[1]

    def request(self, action, *, authenticated=True, valid_csrf=True, origin='https://fixture.invalid'):
        token = hmac.new(f'{self.username}:{self.password}'.encode(),
                         b'veriflow-collection-start', hashlib.sha256).hexdigest()
        data = urlencode(dict(csrf=token if valid_csrf else 'bad', job_id=str(uuid.uuid4()))).encode()
        handler = object.__new__(self.handler_class)
        handler.path = '/collection/' + action
        handler.headers = Message()
        handler.headers['Host'] = 'fixture.invalid'
        handler.headers['Origin'] = origin
        handler.headers['Content-Type'] = 'application/x-www-form-urlencoded'
        handler.headers['Content-Length'] = str(len(data))
        if authenticated:
            handler.headers['Authorization'] = 'Basic ' + base64.b64encode(
                f'{self.username}:{self.password}'.encode()).decode()
        handler.rfile = io.BytesIO(data)
        handler.send_response = Mock()
        handler.send_error = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        with patch('veriflow.admin.connect') as connect, \
                patch('veriflow.collection_control.control') as apply:
            handler.do_POST()
        return handler, connect, apply

    def test_pause_stop_resume_routes_reuse_existing_auth_and_csrf(self):
        for action in ('pause', 'stop', 'resume'):
            handler, connect, apply = self.request(action)
            handler.send_response.assert_called_once_with(303)
            self.assertEqual(apply.call_args.args[1], action)
            handler.send_header.assert_any_call('Location', '/collection')

    def test_missing_auth_blocks_control_before_database(self):
        handler, connect, apply = self.request('stop', authenticated=False)
        handler.send_response.assert_called_once_with(401)
        connect.assert_not_called()
        apply.assert_not_called()

    def test_bad_csrf_or_origin_blocks_control_before_database(self):
        for kwargs in ({'valid_csrf': False}, {'origin': 'https://other.invalid'}):
            handler, connect, apply = self.request('resume', **kwargs)
            handler.send_error.assert_called_once_with(403)
            connect.assert_not_called()
            apply.assert_not_called()
