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
        sql=sorted(Path('supabase/migrations').glob('*.sql'))[0].read_text()
        cls.admin.execute(sql)
        cls.admin.execute('CREATE ROLE veriflow_test_login LOGIN')
        cls.admin.execute('GRANT veriflow_runtime TO veriflow_test_login')
        cls.admin.execute('CREATE ROLE anon NOLOGIN')
        cls.admin.execute('CREATE ROLE authenticated NOLOGIN')
        for migration in sorted(Path('supabase/migrations').glob('*.sql'))[1:]:
            cls.admin.execute(migration.read_text())

    @classmethod
    def tearDownClass(cls):
        cls.admin.close()

    def setUp(self):
        self.admin.execute('TRUNCATE veriflow.sources,veriflow.products,veriflow.integration_status CASCADE')
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
        for route in ['/','/sources','/errors','/trends','/integrations']:
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

    def trends_setup(self):
        # Mock tool contract only. It does not assert a real Google Trends tool.
        import hashlib
        from types import SimpleNamespace
        from psycopg.types.json import Jsonb
        from veriflow.composio import ComposioClient
        schema={'type':'object','properties':{k:{'type':'string'} for k in ['q','geo','range']},'required':['q','geo','range'],'additionalProperties':False}
        mapping={'rows_path':['series'],'date_key':'day','value_key':'interest',
                 'argument_keys':{'query':'q','geography':'geo','time_range':'range'}}
        tool={'slug':'TEST_TRENDS_READ','version':'test-v1','toolkit':{'slug':'test-provider'},'input_parameters':schema}
        calls=[]
        def execute(slug,**kwargs):
            calls.append((slug,kwargs))
            return {'successful':True,'data':{'series':[{'day':'2026-01-01','interest':72,'private_identity':'discard'}]}}
        sdk=SimpleNamespace(client=SimpleNamespace(
            connected_accounts=SimpleNamespace(list=lambda **kw:{'items':[{'id':'test-account','status':'ACTIVE','toolkit':{'slug':'test-provider'}}]}),
            tools=SimpleNamespace(list=lambda **kw:{'items':[tool]})),tools=SimpleNamespace(execute=execute))
        client=ComposioClient('test-key','test-user',sdk=sdk)
        self.conn.execute("UPDATE veriflow.sources SET enabled=true,access_status='approved' WHERE id='google-trends'")
        grant=self.conn.execute('''INSERT INTO veriflow.authorizations(source_id,method,evidence,product_keys,approved_by,expires_at)
            VALUES ('google-trends','composio','TEST ONLY',ARRAY['test query'],'test',now()+interval '1 day') RETURNING id''').fetchone()['id']
        binding=self.conn.execute('''INSERT INTO veriflow.integration_bindings
            (source_id,provider,tool_slug,tool_version,connected_account_id,user_scope_hash,read_only_approved,approval_evidence,input_schema,output_mapping,enabled)
            VALUES ('google-trends','test-provider','TEST_TRENDS_READ','test-v1','test-account',%s,true,'TEST ONLY',%s,%s,true) RETURNING id''',
            (hashlib.sha256(b'test-user').hexdigest(),Jsonb(schema),Jsonb(mapping))).fetchone()['id']
        return dict(client=client,binding=binding,grant=grant,calls=calls,schema=schema)

    def run_trends(self,setup):
        from veriflow.integrations import collect_trends
        return collect_trends(self.conn,setup['binding'],setup['grant'],
            {'q':'test query','geo':'US','range':'today 12-m'},'test query','US','today 12-m',
            'https://trends.google.com/trends/explore',client=setup['client'])

    def test_mocked_composio_to_postgres_transfer(self):
        from veriflow.integrations import discover
        setup=self.trends_setup()
        inventory=discover(self.conn,setup['client'])
        self.assertEqual(inventory['status'],'discovered')
        result=self.run_trends(setup);self.conn.commit()
        self.assertEqual(result['status'],'success')
        self.assertEqual(result['points'],1)
        row=self.conn.execute('SELECT * FROM veriflow.trends_research').fetchone()
        self.assertEqual(row['data'],{'series':[{'date':'2026-01-01','value':72}]})
        self.assertEqual(row['tool_version'],'test-v1')
        self.assertEqual(setup['calls'][0][1]['connected_account_id'],'test-account')
        self.assertEqual(setup['calls'][0][1]['user_id'],'test-user')
        status=self.conn.execute("SELECT * FROM veriflow.integration_status WHERE provider='test-provider'").fetchone()
        self.assertEqual(status['status'],'ready')
        self.assertIsNotNone(status['last_success_at'])
        dashboard=page(self.conn,'/integrations',{})
        self.assertIn('test-provider',dashboard)
        self.assertNotIn('test-account',dashboard)
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM veriflow.reviews').fetchone()['n'],0)

    def test_catalog_match_without_connected_account_cannot_execute(self):
        setup=self.trends_setup()
        setup['client'].sdk.client.connected_accounts.list=lambda **kw:{'items':[]}
        result=self.run_trends(setup);self.conn.commit()
        self.assertEqual(result['error_code'],'access_denied')
        self.assertEqual(setup['calls'],[])
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM veriflow.trends_research').fetchone()['n'],0)

    def test_unapproved_binding_never_executes(self):
        setup=self.trends_setup()
        self.conn.execute('UPDATE veriflow.integration_bindings SET read_only_approved=false')
        self.assertEqual(self.run_trends(setup)['error_code'],'access_denied')
        self.assertEqual(setup['calls'],[])

    def test_missing_composio_credentials_persist_status(self):
        from veriflow.integrations import discover
        from veriflow.composio import ComposioClient
        client=ComposioClient();client.api_key=None;client.user_id=None
        result=discover(self.conn,client);self.conn.commit()
        self.assertEqual(result['error_code'],'credentials_missing')
        row=self.conn.execute("SELECT status,error_code FROM veriflow.integration_status WHERE provider='composio'").fetchone()
        self.assertEqual(row,dict(status='pending_credentials',error_code='credentials_missing'))

    def test_source_disabled_or_expired_blocks_trends(self):
        setup=self.trends_setup()
        self.conn.execute("UPDATE veriflow.authorizations SET expires_at=now()-interval '1 day' WHERE id=%s",(setup['grant'],))
        self.assertEqual(self.run_trends(setup)['error_code'],'access_denied')
        self.assertEqual(setup['calls'],[])

    def test_changed_input_schema_or_user_blocks_execution(self):
        setup=self.trends_setup()
        setup['client'].user_id='different-user'
        self.assertEqual(self.run_trends(setup)['error_code'],'access_denied')
        self.assertEqual(setup['calls'],[])

    def test_application_login_is_not_owner_or_privileged(self):
        with psycopg.connect(self.url,row_factory=dict_row) as c:
            c.execute('SET ROLE veriflow_app')
            self.assertEqual(c.execute('SELECT current_user AS name').fetchone()['name'],'veriflow_app')
            self.assertEqual(c.execute('SELECT count(*) AS n FROM veriflow.sources').fetchone()['n'],42)
            role=c.execute("SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user").fetchone()
            self.assertFalse(any(role.values()))
            from veriflow.health import database_health
            health=database_health(c)
            self.assertTrue(health['application_role'])
            self.assertTrue(health['public_access_denied'])
            self.assertTrue(health['rls_enabled'])
            self.assertEqual(health['missing_tables'],[])
            self.assertFalse(health['tls'])  # Disposable local PostgreSQL intentionally has no TLS.
            self.assertFalse(health['healthy'])
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                c.execute('ALTER TABLE veriflow.reviews DISABLE ROW LEVEL SECURITY')
