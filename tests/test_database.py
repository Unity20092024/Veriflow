"""Integration tests require a disposable PostgreSQL database, never production."""
import json
import os
import unittest
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from veriflow.db import seed
from veriflow.worker import enqueue,run_one
from veriflow.admin import page
from veriflow.connectors import AccessDenied,CollectionError,RateLimited
from tests.test_connectors import fixture


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'Set TEST_DATABASE_URL to a disposable database')
class DatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url=os.environ['TEST_DATABASE_URL']
        cls.admin=psycopg.connect(cls.url,autocommit=True,row_factory=dict_row)
        # Refuse to overwrite an existing installation.
        exists=cls.admin.execute("SELECT to_regnamespace('veriflow') AS schema").fetchone()['schema']
        if exists: raise RuntimeError('Tests require an empty disposable database')
        sql=next(Path('supabase/migrations').glob('*.sql')).read_text()
        cls.admin.execute(sql)
        cls.admin.execute('CREATE ROLE veriflow_test_login LOGIN')
        cls.admin.execute('GRANT veriflow_runtime TO veriflow_test_login')
        cls.admin.execute('CREATE ROLE anon NOLOGIN')
        cls.admin.execute('CREATE ROLE authenticated NOLOGIN')

    @classmethod
    def tearDownClass(cls):
        cls.admin.close()

    def setUp(self):
        self.admin.execute('TRUNCATE veriflow.sources,veriflow.products CASCADE')
        self.conn=psycopg.connect(self.url,row_factory=dict_row)
        self.conn.execute('SET ROLE veriflow_test_login')
        seed(self.conn)
        self.source='capterra-reviews'
        self.conn.execute("UPDATE veriflow.sources SET enabled=true,access_status='approved',full_text_allowed=true WHERE id=%s",(self.source,))
        self.product=self.conn.execute("INSERT INTO veriflow.products(name,vendor) VALUES ('Test Product','Test Vendor') RETURNING id").fetchone()['id']
        self.conn.execute("INSERT INTO veriflow.source_products VALUES (%s,'test-product',%s,'Test Product')",(self.source,self.product))
        self.grant=self.conn.execute('''INSERT INTO veriflow.authorizations
            (source_id,method,evidence,product_keys,full_text_allowed,approved_by,expires_at)
            VALUES (%s,'approved_import','TEST ONLY: synthetic fixtures; no live collection rights',
            ARRAY['test-product'],true,'test operator',now()+interval '1 day') RETURNING id''',(self.source,)).fetchone()['id']
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def queue(self,rows=None):
        batch=enqueue(self.conn,self.source,self.grant,json.dumps(rows or [fixture()]),'json')
        self.conn.commit()
        return batch

    def test_capterra_import_roundtrip_and_duplicates(self):
        batch=self.queue()
        result=run_one(self.conn);self.conn.commit()
        self.assertEqual(result['inserted'],1)
        review=self.conn.execute('SELECT * FROM veriflow.reviews').fetchone()
        self.assertEqual(review['product_id'],self.product)
        self.assertEqual(review['source_id'],'capterra-reviews')
        self.assertIsNotNone(review['collected_at'])
        self.assertEqual(self.conn.execute('SELECT records FROM veriflow.import_batches WHERE id=%s',(batch,)).fetchone()['records'],[])
        self.queue()
        self.conn.execute('UPDATE veriflow.sources SET next_run_at=now() WHERE id=%s',(self.source,))
        result=run_one(self.conn);self.conn.commit()
        self.assertEqual(result['duplicates'],1)
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM veriflow.reviews').fetchone()['n'],1)
        self.assertIn('TEST FIXTURE',page(self.conn,'/reviews',{'source':[self.source]}))
        for route in ['/','/sources','/errors','/trends']:
            self.assertIn('Veriflow',page(self.conn,route,{}))

    def test_privacy_projection_before_storage(self):
        batch=self.queue()
        records=self.conn.execute('SELECT records FROM veriflow.import_batches WHERE id=%s',(batch,)).fetchone()['records']
        self.assertNotIn('reviewer_',json.dumps(records))
        self.assertNotIn('discard@example',json.dumps(records))

    def test_revoked_or_expired_grant_blocks_collection(self):
        self.queue()
        self.conn.execute('UPDATE veriflow.authorizations SET expires_at=now()-interval \'1 second\' WHERE id=%s',(self.grant,))
        result=run_one(self.conn);self.conn.commit()
        self.assertEqual(result['error_code'],'access_denied')
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM veriflow.reviews').fetchone()['n'],0)

    def test_full_text_permission_rechecked_after_queue(self):
        self.queue()
        self.conn.execute('UPDATE veriflow.sources SET full_text_allowed=false WHERE id=%s',(self.source,))
        self.assertEqual(run_one(self.conn)['error_code'],'access_denied')
        self.conn.commit()

    def test_unmapped_product_rejected(self):
        row=fixture();row['software_name']='Different Product'
        with self.assertRaises(CollectionError): self.queue([row])

    def test_pending_source_is_not_collectible(self):
        self.conn.execute("UPDATE veriflow.sources SET access_status='pending_authorization' WHERE id=%s",(self.source,))
        with self.assertRaises(AccessDenied): self.queue()

    def test_source_lock_prevents_concurrent_workers(self):
        self.queue()
        self.conn.execute('SELECT id FROM veriflow.sources WHERE id=%s FOR UPDATE',(self.source,))
        with psycopg.connect(self.url,row_factory=dict_row) as other:
            other.execute('SET ROLE veriflow_test_login')
            self.assertIsNone(run_one(other))
        self.conn.rollback()
        self.assertEqual(run_one(self.conn)['inserted'],1)
        self.conn.commit()

    def test_rate_limit_reschedules_and_preserves_batch(self):
        from veriflow.worker import CONNECTORS
        self.queue()
        original=CONNECTORS._connectors['approved_import']
        class Limited:
            def collect(self,*args): raise RateLimited(180)
        CONNECTORS._connectors['approved_import']=Limited()
        try:
            self.assertEqual(run_one(self.conn)['status'],'rate_limited')
            self.conn.commit()
            row=self.conn.execute('SELECT next_run_at>now()+interval \'170 seconds\' AS delayed FROM veriflow.sources WHERE id=%s',(self.source,)).fetchone()
            self.assertTrue(row['delayed'])
            self.assertEqual(self.conn.execute('SELECT status FROM veriflow.import_batches').fetchone()['status'],'pending')
        finally: CONNECTORS._connectors['approved_import']=original

    def test_all_tables_have_rls_and_no_public_privileges(self):
        rows=self.admin.execute("SELECT relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='veriflow' AND c.relkind='r'").fetchall()
        self.assertTrue(all(r['relrowsecurity'] for r in rows))
        for role in ['anon','authenticated']:
            with psycopg.connect(self.url) as c:
                c.execute('SET ROLE '+role)
                with self.assertRaises(psycopg.errors.InsufficientPrivilege): c.execute('SELECT * FROM veriflow.reviews')

    def test_cross_source_content_keeps_provenance(self):
        self.queue();run_one(self.conn);self.conn.commit()
        self.conn.execute("UPDATE veriflow.sources SET enabled=true,access_status='approved',full_text_allowed=true WHERE id='g2'")
        self.conn.execute("INSERT INTO veriflow.source_products VALUES ('g2','g2-test',%s,'Test Product')",(self.product,))
        grant=self.conn.execute('''INSERT INTO veriflow.authorizations
            (source_id,method,evidence,product_keys,full_text_allowed,approved_by,expires_at)
            VALUES ('g2','approved_import','TEST ONLY',ARRAY['g2-test'],true,'test',now()+interval '1 day') RETURNING id''').fetchone()['id']
        row=fixture();row.update(product_key='g2-test',original_url='https://g2.com/reviews/test')
        enqueue(self.conn,'g2',grant,json.dumps([row]),'json');run_one(self.conn);self.conn.commit()
        result=self.conn.execute('SELECT count(*) AS n,count(DISTINCT duplicate_group) AS groups FROM veriflow.reviews').fetchone()
        self.assertEqual(result,dict(n=2,groups=1))

    def test_dashboard_http_requires_authentication(self):
        import base64
        import socket
        import subprocess
        import sys
        import time
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError,URLError
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0))
            port=sock.getsockname()[1]
        password='private-test-password-at-least-24'
        env=dict(os.environ,DATABASE_URL=self.url,ADMIN_USERNAME='test',ADMIN_PASSWORD=password)
        process=subprocess.Popen([sys.executable,'-m','veriflow','admin','--port',str(port)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        url=f'http://127.0.0.1:{port}/sources'
        try:
            ready=False
            for _ in range(50):
                try:
                    urlopen(url,timeout=1)
                except HTTPError as exc:
                    self.assertEqual(exc.code,401)
                    ready=True
                    break
                except URLError:
                    time.sleep(.1)
            self.assertTrue(ready,'Dashboard did not start')
            token=base64.b64encode(f'test:{password}'.encode()).decode()
            with urlopen(Request(url,headers={'Authorization':'Basic '+token}),timeout=5) as response:
                self.assertEqual(response.status,200)
                self.assertEqual(response.headers['Cache-Control'],'no-store')
                self.assertIn('Capterra Reviews',response.read().decode())
        finally:
            process.terminate()
            process.wait(timeout=5)

    def test_batch_is_atomic_when_policy_validation_fails(self):
        batch=self.queue([fixture(),dict(fixture(),external_id='fixture-2',original_url='https://capterra.com/reviews/test-2')])
        records=self.conn.execute('SELECT records FROM veriflow.import_batches WHERE id=%s',(batch,)).fetchone()['records']
        records[1]['software_name']='Unmapped product'
        from psycopg.types.json import Jsonb
        self.conn.execute('UPDATE veriflow.import_batches SET records=%s WHERE id=%s',(Jsonb(records),batch))
        result=run_one(self.conn);self.conn.commit()
        self.assertEqual(result['status'],'error')
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM veriflow.reviews').fetchone()['n'],0)
        run=self.conn.execute('SELECT * FROM veriflow.collection_runs').fetchone()
        self.assertEqual(run['error_code'],'invalid_import')
