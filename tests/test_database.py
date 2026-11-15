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
        env=dict(os.environ,DATABASE_URL=self.url,ADMIN_USERNAME='test',ADMIN_PASSWORD=password,PORT=str(port))
        process=subprocess.Popen([sys.executable,'-m','veriflow','admin','--host','0.0.0.0'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
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
            from urllib.parse import urlencode
            payload=urlencode({'name':'HTTP fixture product','vendor':'Fixture vendor','csrf':'wrong'}).encode()
            with self.assertRaises(HTTPError) as rejected:
                urlopen(Request(f'http://127.0.0.1:{port}/actions/product',data=payload,headers={'Authorization':'Basic '+token}),timeout=5)
            self.assertEqual(rejected.exception.code,403)
            import re
            with urlopen(Request(f'http://127.0.0.1:{port}/products',headers={'Authorization':'Basic '+token}),timeout=5) as response:
                csrf=re.search(r'name="csrf" value="([^"]+)"',response.read().decode()).group(1)
            payload=urlencode({'name':'HTTP fixture product','vendor':'Fixture vendor','csrf':csrf}).encode()
            with urlopen(Request(f'http://127.0.0.1:{port}/actions/product',data=payload,headers={'Authorization':'Basic '+token}),timeout=5) as response:
                self.assertEqual(response.status,200)
                self.assertIn('HTTP fixture product',response.read().decode())
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

    def apify_setup(self):
        from psycopg.types.json import Jsonb
        from types import SimpleNamespace
        from unittest.mock import Mock
        from veriflow.apify_pipeline import pricing_snapshot
        from unittest.mock import patch
        paid=patch.dict(os.environ,{'APIFY_PAID_RUNS_ENABLED':'true'});paid.start();self.addCleanup(paid.stop)
        from veriflow.pilot import policy
        mock_policy=dict(policy(),paid_execution_authorized=True)
        approval=patch('veriflow.pilot.policy',return_value=mock_policy);approval.start();self.addCleanup(approval.stop)
        self.conn.execute("UPDATE veriflow.sources SET collection_method='apify' WHERE id=%s",(self.source,))
        self.conn.execute("UPDATE veriflow.authorizations SET method='apify' WHERE id=%s",(self.grant,))
        schema={'type':'object','properties':{'url':{'type':'string'},'maxResults':{'type':'integer','minimum':1}},'required':['url','maxResults']}
        price={'pricingModel':'PAY_PER_EVENT','isPPEPlatformUsagePaidByUser':False,'pricingPerEvent':{'actorChargeEvents':{'result':{'eventPriceUsd':.01}}}}
        actor=dict(pricingInfos=[dict(price,startedAt='2026-01-01T00:00:00Z')])
        mapping={'fields':{'external_id':['id'],'software_name':['product'],'review_text':['text'],'rating':['stars'],'published_at':['date'],'original_url':['url']},'rating_scale_constant':5}
        binding=self.conn.execute('''INSERT INTO veriflow.apify_bindings
            (source_id,product_key,actor_id,build_number,build_id,approved_input,input_schema,target_url,target_input_path,
            limit_input_key,field_mapping,pricing_snapshot,max_records,max_charge_usd,timeout_seconds,approved_by,approval_evidence,enabled,pricing_review)
            VALUES (%s,'test-product','test-actor','1.0.0','test-build',%s,%s,'https://capterra.com/products/test',ARRAY['url'],
            'maxResults',%s,%s,10,.5,60,'test','TEST ONLY; no real provider rights',true,%s) RETURNING id''',
            (self.source,Jsonb({'url':'https://capterra.com/products/test','maxResults':10}),Jsonb(schema),Jsonb(mapping),Jsonb(pricing_snapshot(actor)),Jsonb({'full_pricing_confirmed':True,'total_cost_control_confirmed':True,'evidence':'MOCK ONLY — no live pricing authorization','max_incremental_cost_usd':.5}))).fetchone()['id']
        client=SimpleNamespace(token='TEST-TOKEN',actor=Mock(return_value=actor),
            build=Mock(return_value={'actId':'test-actor','buildNumber':'1.0.0','status':'SUCCEEDED','inputSchema':json.dumps(schema)}),
            start=Mock(return_value={'id':'test-run','actId':'test-actor','buildId':'test-build'}),
            run=Mock(return_value={'id':'test-run','actId':'test-actor','buildId':'test-build','status':'SUCCEEDED','defaultDatasetId':'test-dataset','usageTotalUsd':.03}),
            items=Mock(return_value=[dict(id='fixture-1',product='Test Product',text='TEST FIXTURE — not a real review',stars=4,date='2026-01-01',url='https://capterra.com/reviews/test-1',reviewer_email='discard@example.invalid')]))
        self.conn.commit()
        return binding,client

    def test_mocked_apify_to_database_idempotent_ingestion_and_provenance(self):
        from unittest.mock import patch
        from veriflow.apify_pipeline import submit_job,refresh_job
        binding,client=self.apify_setup()
        with patch.dict(os.environ,{'APIFY_MAX_RUN_USD':'1','APIFY_ROLLING_24H_BUDGET_USD':'2'}):
            job=submit_job(self.conn,binding,self.grant,client)
        result=refresh_job(self.conn,job['job_id'],client);self.conn.commit()
        self.assertEqual(result['state'],'queued')
        self.assertEqual(refresh_job(self.conn,job['job_id'],client)['state'],'queued')
        self.conn.commit()
        self.assertEqual(client.items.call_count,1)
        self.assertEqual(run_one(self.conn)['inserted'],1);self.conn.commit()
        self.assertEqual(refresh_job(self.conn,job['job_id'],client)['state'],'ingested')
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM veriflow.reviews').fetchone()['n'],1)
        provenance=self.conn.execute('''SELECT j.actor_run_id,j.dataset_id,j.inserted,j.reported_usage_usd,j.confirmed_billed_usd
            FROM veriflow.reviews r JOIN veriflow.collection_runs c ON c.id=r.run_id
            JOIN veriflow.apify_jobs j ON j.id=c.provider_job_id''').fetchone()
        self.assertEqual(provenance['actor_run_id'],'test-run')
        self.assertEqual(provenance['dataset_id'],'test-dataset')
        self.assertEqual(provenance['inserted'],1)
        self.assertIsNone(provenance['confirmed_billed_usd'])
        self.assertIn('test-run',page(self.conn,'/collection',{}))
        self.assertIn('Capterra Reviews',page(self.conn,'/capabilities',{}))

    def test_apify_budget_zero_and_daily_cap_prevent_paid_post(self):
        from unittest.mock import patch
        from veriflow.apify_pipeline import submit_job,BudgetDenied
        binding,client=self.apify_setup()
        for limits in [{'APIFY_MAX_RUN_USD':'0','APIFY_ROLLING_24H_BUDGET_USD':'5'},
                       {'APIFY_MAX_RUN_USD':'1','APIFY_ROLLING_24H_BUDGET_USD':'.4'}]:
            with patch.dict(os.environ,limits):
                with self.assertRaises(BudgetDenied):submit_job(self.conn,binding,self.grant,client)
            self.conn.rollback()
        client.start.assert_not_called()

    def test_apify_permission_required_before_paid_start(self):
        from unittest.mock import patch
        from veriflow.apify_pipeline import submit_job
        binding,client=self.apify_setup()
        self.conn.execute('UPDATE veriflow.authorizations SET revoked_at=now() WHERE id=%s',(self.grant,));self.conn.commit()
        with patch.dict(os.environ,{'APIFY_MAX_RUN_USD':'1','APIFY_ROLLING_24H_BUDGET_USD':'5'}):
            with self.assertRaises(AccessDenied):submit_job(self.conn,binding,self.grant,client)
        client.start.assert_not_called()

    def test_apify_uncertain_start_retains_reservation_and_is_not_retried(self):
        from unittest.mock import patch
        from veriflow.apify import StartUnknown
        from veriflow.apify_pipeline import submit_job,refresh_job,JobPending
        binding,client=self.apify_setup();client.start.side_effect=StartUnknown()
        with patch.dict(os.environ,{'APIFY_MAX_RUN_USD':'1','APIFY_ROLLING_24H_BUDGET_USD':'.5'}):
            job=submit_job(self.conn,binding,self.grant,client)
            self.assertEqual(job['state'],'start_unknown')
            with self.assertRaises(JobPending):submit_job(self.conn,binding,self.grant,client)
            self.conn.rollback()
        self.assertEqual(refresh_job(self.conn,job['job_id'],client)['state'],'start_unknown')
        self.assertEqual(client.start.call_count,1)
        self.assertEqual(client.run.call_count,0)

    def test_apify_expired_permission_prevents_export(self):
        from unittest.mock import patch
        from veriflow.apify_pipeline import submit_job,refresh_job
        binding,client=self.apify_setup()
        with patch.dict(os.environ,{'APIFY_MAX_RUN_USD':'1','APIFY_ROLLING_24H_BUDGET_USD':'2'}):job=submit_job(self.conn,binding,self.grant,client)
        self.conn.execute("UPDATE veriflow.authorizations SET expires_at=now()-interval '1 second' WHERE id=%s",(self.grant,));self.conn.commit()
        self.assertEqual(refresh_job(self.conn,job['job_id'],client)['error_code'],'access_denied')
        client.items.assert_not_called()

    def test_apify_wrong_product_rejects_complete_batch(self):
        from unittest.mock import patch
        from veriflow.apify_pipeline import submit_job,refresh_job
        binding,client=self.apify_setup();client.items.return_value[0]['product']='Different Product'
        with patch.dict(os.environ,{'APIFY_MAX_RUN_USD':'1','APIFY_ROLLING_24H_BUDGET_USD':'2'}):job=submit_job(self.conn,binding,self.grant,client)
        self.assertIn('error_code',refresh_job(self.conn,job['job_id'],client));self.conn.commit()
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM veriflow.import_batches').fetchone()['n'],0)

    def test_apify_changed_pricing_or_extra_platform_charges_blocks_start(self):
        from unittest.mock import patch
        from veriflow.apify_pipeline import submit_job,BudgetDenied
        binding,client=self.apify_setup()
        client.actor.return_value['pricingInfos'][0]['isPPEPlatformUsagePaidByUser']=True
        with patch.dict(os.environ,{'APIFY_MAX_RUN_USD':'1','APIFY_ROLLING_24H_BUDGET_USD':'2'}):
            with self.assertRaises(BudgetDenied):submit_job(self.conn,binding,self.grant,client)
        client.start.assert_not_called()

    def test_distinct_metadata_reviews_can_share_listing_url(self):
        a=fixture();a['review_text']=None
        b=dict(a,external_id='different-native-review',rating=3)
        self.queue([a,b]);self.assertEqual(run_one(self.conn)['inserted'],2)
        self.conn.commit()
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM veriflow.reviews').fetchone()['n'],2)

    def test_apify_repeated_completed_runs_deduplicate_reviews(self):
        from unittest.mock import patch
        from veriflow.apify_pipeline import submit_job,refresh_job
        binding,client=self.apify_setup()
        for n in range(2):
            client.start.return_value['id']='test-run-'+str(n)
            client.run.return_value['id']='test-run-'+str(n)
            with patch.dict(os.environ,{'APIFY_MAX_RUN_USD':'1','APIFY_ROLLING_24H_BUDGET_USD':'2'}):job=submit_job(self.conn,binding,self.grant,client)
            refresh_job(self.conn,job['job_id'],client);self.conn.commit()
            self.conn.execute('UPDATE veriflow.sources SET next_run_at=now() WHERE id=%s',(self.source,))
            result=run_one(self.conn);self.conn.commit()
            self.assertEqual(result['inserted'],1 if n==0 else 0)
            self.assertEqual(result['duplicates'],0 if n==0 else 1)
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM veriflow.reviews').fetchone()['n'],1)
        self.assertEqual(client.start.call_count,2)

    def test_apify_binding_mutation_after_start_cannot_change_product_provenance(self):
        from unittest.mock import patch
        from veriflow.apify_pipeline import submit_job,refresh_job
        binding,client=self.apify_setup()
        with patch.dict(os.environ,{'APIFY_MAX_RUN_USD':'1','APIFY_ROLLING_24H_BUDGET_USD':'2'}):job=submit_job(self.conn,binding,self.grant,client)
        self.conn.execute('UPDATE veriflow.apify_bindings SET max_records=21 WHERE id=%s',(binding,));self.conn.commit()
        self.assertEqual(refresh_job(self.conn,job['job_id'],client)['error_code'],'access_denied')
        client.items.assert_not_called()

    def test_apify_missing_fulltext_permission_blocks_paid_start(self):
        from unittest.mock import patch
        from veriflow.apify_pipeline import submit_job
        binding,client=self.apify_setup()
        self.conn.execute('UPDATE veriflow.authorizations SET full_text_allowed=false WHERE id=%s',(self.grant,));self.conn.commit()
        with patch.dict(os.environ,{'APIFY_MAX_RUN_USD':'1','APIFY_ROLLING_24H_BUDGET_USD':'2'}):
            with self.assertRaises(AccessDenied):submit_job(self.conn,binding,self.grant,client)
        client.start.assert_not_called()

    def test_apify_failed_provider_run_records_error_without_export(self):
        from unittest.mock import patch
        from veriflow.apify_pipeline import submit_job,refresh_job
        binding,client=self.apify_setup();client.run.return_value['status']='FAILED'
        with patch.dict(os.environ,{'APIFY_MAX_RUN_USD':'1','APIFY_ROLLING_24H_BUDGET_USD':'2'}):job=submit_job(self.conn,binding,self.grant,client)
        self.assertEqual(refresh_job(self.conn,job['job_id'],client)['state'],'failed');self.conn.commit()
        row=self.conn.execute('SELECT error_code,confirmed_billed_usd FROM veriflow.apify_jobs').fetchone()
        self.assertEqual(row['error_code'],'apify_run_failed')
        self.assertIsNone(row['confirmed_billed_usd'])
        client.items.assert_not_called()

    def test_apify_transient_export_error_resumes_without_second_paid_start(self):
        from unittest.mock import patch
        from veriflow.apify_pipeline import submit_job,refresh_job
        from veriflow.apify import ApifyError
        binding,client=self.apify_setup();rows=client.items.return_value;client.items.side_effect=RateLimited(180)
        with patch.dict(os.environ,{'APIFY_MAX_RUN_USD':'1','APIFY_ROLLING_24H_BUDGET_USD':'2'}):job=submit_job(self.conn,binding,self.grant,client)
        result=refresh_job(self.conn,job['job_id'],client);self.conn.commit()
        self.assertEqual(result['state'],'running')
        self.assertEqual(result['retry_after_seconds'],180)
        client.items.side_effect=None;client.items.return_value=rows
        self.assertEqual(refresh_job(self.conn,job['job_id'],client)['state'],'queued');self.conn.commit()
        self.assertEqual(client.start.call_count,1)

    def test_apify_reviewer_identity_mapping_rejected_before_paid_start(self):
        from unittest.mock import patch
        from psycopg.types.json import Jsonb
        from veriflow.apify_pipeline import submit_job
        binding,client=self.apify_setup()
        mapping=self.conn.execute('SELECT field_mapping FROM veriflow.apify_bindings WHERE id=%s',(binding,)).fetchone()['field_mapping']
        mapping['fields']['review_text']=['reviewer','email']
        self.conn.execute('UPDATE veriflow.apify_bindings SET field_mapping=%s WHERE id=%s',(Jsonb(mapping),binding));self.conn.commit()
        with patch.dict(os.environ,{'APIFY_MAX_RUN_USD':'1','APIFY_ROLLING_24H_BUDGET_USD':'2'}):
            with self.assertRaises(AccessDenied):submit_job(self.conn,binding,self.grant,client)
        client.start.assert_not_called()

    def test_revoked_apify_approval_requests_stop_of_owned_active_run(self):
        from unittest.mock import patch,Mock
        from veriflow.apify_pipeline import submit_job,refresh_job
        binding,client=self.apify_setup()
        client.run.return_value['status']='RUNNING';client.abort=Mock(return_value={'status':'ABORTED'})
        with patch.dict(os.environ,{'APIFY_MAX_RUN_USD':'1','APIFY_ROLLING_24H_BUDGET_USD':'2'}):job=submit_job(self.conn,binding,self.grant,client)
        self.conn.execute('UPDATE veriflow.authorizations SET revoked_at=now() WHERE id=%s',(self.grant,));self.conn.commit()
        self.assertEqual(refresh_job(self.conn,job['job_id'],client)['state'],'aborted')
        client.abort.assert_called_once_with('test-run')
        client.items.assert_not_called()

    def licensed_fixture_setup(self):
        from veriflow.libreviews import extract_review
        from pathlib import Path
        self.conn.execute('UPDATE veriflow.sources SET enabled=false')
        self.source='lib-reviews-fixture'
        self.conn.execute('''INSERT INTO veriflow.sources
            (id,name,url,category,provenance,collection_method,access_status,enabled,full_text_allowed,
             policy_notes,required_license_id,attribution_required)
            VALUES (%s,'lib.reviews FIXTURE','https://lib.reviews','software_review_directory','OFFLINE TEST ONLY',
            'approved_import','approved',true,true,'FIXTURE ONLY','CC-BY-SA-4.0',true)''',(self.source,))
        self.product=self.conn.execute("INSERT INTO veriflow.products(name,vendor) VALUES ('Mozilla Firefox','Fixture vendor') RETURNING id").fetchone()['id']
        self.conn.execute("INSERT INTO veriflow.source_products VALUES (%s,'fixture-firefox',%s,'Mozilla Firefox')",(self.source,self.product))
        self.grant=self.conn.execute('''INSERT INTO veriflow.authorizations
            (source_id,method,evidence,product_keys,full_text_allowed,approved_by,expires_at,license_id,terms_url)
            VALUES (%s,'approved_import','OFFLINE FIXTURE ONLY',ARRAY['fixture-firefox'],true,'test',now()+interval '1 day','CC-BY-SA-4.0','https://lib.reviews/terms') RETURNING id''',(self.source,)).fetchone()['id']
        self.conn.commit()
        return extract_review(Path('tests/fixtures/libreviews-firefox.html').read_text(),'fixture-firefox','https://lib.reviews/mozilla-firefox')

    def test_licensed_fixture_ingestion_keeps_credit_and_license_on_dashboard(self):
        row=self.licensed_fixture_setup()
        self.queue([row]);self.assertEqual(run_one(self.conn)['inserted'],1);self.conn.commit()
        saved=self.conn.execute('SELECT * FROM veriflow.review_licenses').fetchone()
        self.assertEqual(saved['public_credit'],'Fixture author')
        self.assertEqual(saved['license_id'],'CC-BY-SA-4.0')
        self.assertTrue(saved['text_modified'])
        self.assertIn('Fixture author',page(self.conn,'/reviews',{}))
        self.assertIn('https://creativecommons.org/licenses/by-sa/4.0/',page(self.conn,'/reviews',{}))
        self.queue([row]);self.conn.execute('UPDATE veriflow.sources SET next_run_at=now() WHERE id=%s',(self.source,))
        self.assertEqual(run_one(self.conn)['duplicates'],1);self.conn.commit()
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM veriflow.review_licenses').fetchone()['n'],1)

    def test_required_licensing_cannot_be_silently_discarded(self):
        row=self.licensed_fixture_setup();del row['license_metadata']
        with self.assertRaises(AccessDenied):self.queue([row])
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM veriflow.import_batches').fetchone()['n'],0)

    def test_different_author_credits_are_not_collapsed_as_same_licensed_review(self):
        import copy
        row=self.licensed_fixture_setup();other=copy.deepcopy(row)
        other['external_id']='00000000-0000-4000-8000-000000000002'
        other['original_url']='https://lib.reviews/review/'+other['external_id']
        other['license_metadata'].update(public_credit='Another fixture author',attribution_url='https://lib.reviews/user/another-fixture')
        self.queue([row,other]);self.assertEqual(run_one(self.conn)['inserted'],2);self.conn.commit()
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM veriflow.review_licenses').fetchone()['n'],2)

    def test_environment_cannot_raise_first_pilot_dollar_or_record_ceiling(self):
        from unittest.mock import patch
        from psycopg.types.json import Jsonb
        from veriflow.apify_pipeline import submit_job,BudgetDenied
        binding,client=self.apify_setup()
        self.conn.execute('UPDATE veriflow.apify_bindings SET pricing_review=%s,max_charge_usd=1.1 WHERE id=%s',
            (Jsonb({'full_pricing_confirmed':True,'total_cost_control_confirmed':True,'evidence':'MOCK ONLY','max_incremental_cost_usd':1.1}),binding))
        with patch.dict(os.environ,{'APIFY_MAX_RUN_USD':'100','APIFY_ROLLING_24H_BUDGET_USD':'100','APIFY_MAX_RECORDS':'1000'}):
            with self.assertRaises(BudgetDenied):submit_job(self.conn,binding,self.grant,client)
        self.conn.rollback()
        self.conn.execute('UPDATE veriflow.apify_bindings SET max_records=21,approved_input=%s WHERE id=%s',
            (Jsonb({'url':'https://capterra.com/products/test','maxResults':21}),binding))
        with patch.dict(os.environ,{'APIFY_MAX_RECORDS':'1000'}):
            with self.assertRaises(BudgetDenied):submit_job(self.conn,binding,self.grant,client)
        client.start.assert_not_called()

    def test_first_test_budget_does_not_reset_after_twenty_four_hours(self):
        from unittest.mock import patch
        from psycopg.types.json import Jsonb
        from veriflow.apify_pipeline import submit_job,BudgetDenied
        binding,client=self.apify_setup()
        with patch.dict(os.environ,{'APIFY_MAX_RUN_USD':'1','APIFY_ROLLING_24H_BUDGET_USD':'100'}):
            job=submit_job(self.conn,binding,self.grant,client)
            self.conn.execute("UPDATE veriflow.apify_jobs SET state='ingested',confirmed_billed_usd=.5,created_at=now()-interval '2 days' WHERE id=%s",(job['job_id'],))
            self.conn.execute('UPDATE veriflow.apify_bindings SET pricing_review=%s WHERE id=%s',
                (Jsonb({'full_pricing_confirmed':True,'total_cost_control_confirmed':True,'evidence':'MOCK ONLY','max_incremental_cost_usd':.75}),binding))
            self.conn.commit()
            with self.assertRaises(BudgetDenied):submit_job(self.conn,binding,self.grant,client)
        self.assertEqual(client.start.call_count,1)

    def test_unconfirmed_complete_pricing_blocks_paid_post(self):
        from unittest.mock import patch
        from veriflow.apify_pipeline import submit_job,BudgetDenied
        binding,client=self.apify_setup()
        self.conn.execute("UPDATE veriflow.apify_bindings SET pricing_review='{}' WHERE id=%s",(binding,));self.conn.commit()
        with patch.dict(os.environ,{'APIFY_MAX_RUN_USD':'1','APIFY_ROLLING_24H_BUDGET_USD':'1'}):
            with self.assertRaises(BudgetDenied):submit_job(self.conn,binding,self.grant,client)
        client.start.assert_not_called()

    def test_paid_switch_off_blocks_even_mock_authorized_binding(self):
        from unittest.mock import patch
        from veriflow.apify_pipeline import submit_job
        from veriflow.pilot import PaidRunsDisabled
        binding,client=self.apify_setup()
        with patch.dict(os.environ,{'APIFY_PAID_RUNS_ENABLED':'false'}):
            with self.assertRaises(PaidRunsDisabled):submit_job(self.conn,binding,self.grant,client)
        client.actor.assert_not_called();client.start.assert_not_called()

    def test_untracked_apify_import_cannot_bypass_reserved_record_allowance(self):
        binding,client=self.apify_setup()
        with self.assertRaises(AccessDenied):self.queue([fixture()])
        client.start.assert_not_called()
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM veriflow.import_batches').fetchone()['n'],0)

    def test_password_reset_changes_only_application_password(self):
        from scripts.reset_app_password import reset_role_password
        from psycopg.conninfo import conninfo_to_dict
        before=self.admin.execute("SELECT * FROM pg_roles WHERE rolname IN ('veriflow_app','postgres') ORDER BY rolname").fetchall()
        owner_hash=self.admin.execute("SELECT rolpassword FROM pg_authid WHERE rolname='postgres'").fetchone()['rolpassword']
        policies=self.admin.execute("SELECT * FROM pg_policies WHERE schemaname='veriflow' ORDER BY tablename,policyname").fetchall()
        password='OnlyDisposableFixturePassword1234567890'
        reset_role_password(self.admin,password)
        self.assertEqual(before,self.admin.execute("SELECT * FROM pg_roles WHERE rolname IN ('veriflow_app','postgres') ORDER BY rolname").fetchall())
        self.assertTrue(self.admin.execute("SELECT rolpassword=%s AS same FROM pg_authid WHERE rolname='postgres'",(owner_hash,)).fetchone()['same'])
        self.assertEqual(policies,self.admin.execute("SELECT * FROM pg_policies WHERE schemaname='veriflow' ORDER BY tablename,policyname").fetchall())
        settings=conninfo_to_dict(self.url);settings.update(user='veriflow_app',password=password)
        with psycopg.connect(**settings,row_factory=dict_row) as app:
            self.assertEqual(app.execute('SELECT current_user AS role').fetchone()['role'],'veriflow_app')
            self.assertEqual(app.execute('SELECT count(*) AS n FROM veriflow.sources').fetchone()['n'],42)

    def test_monitor_queues_once_with_paid_execution_disabled(self):
        from unittest.mock import patch
        from veriflow.apify_pipeline import submit_job
        from veriflow.apify_monitor import poll_one
        binding,client=self.apify_setup()
        with patch.dict(os.environ,{'APIFY_MAX_RUN_USD':'1','APIFY_ROLLING_24H_BUDGET_USD':'2'}):
            submit_job(self.conn,binding,self.grant,client)
        with patch.dict(os.environ,{'APIFY_PAID_RUNS_ENABLED':'false'}):
            result=poll_one(self.conn,client);self.conn.commit()
            self.assertEqual(result['state'],'queued')
            self.assertIsNone(poll_one(self.conn,client));self.conn.commit()
        self.assertEqual(client.start.call_count,1)
        self.assertEqual(client.items.call_count,1)
        self.assertEqual(run_one(self.conn)['inserted'],1);self.conn.commit()
        self.assertIn('poll failures',page(self.conn,'/collection',{}))

    def test_monitor_rate_limit_is_durable_and_honors_retry_after(self):
        from unittest.mock import patch
        from veriflow.apify_pipeline import submit_job
        from veriflow.apify_monitor import poll_one
        binding,client=self.apify_setup();client.run.side_effect=RateLimited(900)
        with patch.dict(os.environ,{'APIFY_MAX_RUN_USD':'1','APIFY_ROLLING_24H_BUDGET_USD':'2'}):
            job=submit_job(self.conn,binding,self.grant,client)
        result=poll_one(self.conn,client);self.conn.commit()
        self.assertEqual(result['next_poll_seconds'],900)
        self.assertEqual(result['poll_failures'],1)
        with psycopg.connect(self.url,row_factory=dict_row) as restarted:
            self.assertIsNone(poll_one(restarted,client))
        self.assertEqual(client.run.call_count,1)
        client.run.side_effect=None
        self.conn.execute("UPDATE veriflow.apify_jobs SET next_poll_at=now() WHERE id=%s",(job['job_id'],));self.conn.commit()
        result=poll_one(self.conn,client);self.conn.commit()
        self.assertEqual(result['state'],'queued')
        self.assertEqual(result['poll_failures'],0)
        self.assertIsNone(self.conn.execute('SELECT error_code FROM veriflow.apify_jobs WHERE id=%s',(job['job_id'],)).fetchone()['error_code'])

    def test_monitor_preserves_uncertain_starts_without_retrying(self):
        from unittest.mock import patch
        from veriflow.apify import StartUnknown
        from veriflow.apify_pipeline import submit_job
        from veriflow.apify_monitor import poll_one
        binding,client=self.apify_setup();client.start.side_effect=StartUnknown()
        with patch.dict(os.environ,{'APIFY_MAX_RUN_USD':'1','APIFY_ROLLING_24H_BUDGET_USD':'2'}):
            submit_job(self.conn,binding,self.grant,client)
        self.assertIsNone(poll_one(self.conn,client))
        self.assertEqual(client.start.call_count,1)
        client.run.assert_not_called()

    def test_monitor_without_credentials_backs_off_without_provider_call(self):
        from unittest.mock import patch
        from veriflow.apify_pipeline import submit_job
        from veriflow.apify_monitor import poll_one
        binding,client=self.apify_setup()
        with patch.dict(os.environ,{'APIFY_MAX_RUN_USD':'1','APIFY_ROLLING_24H_BUDGET_USD':'2'}):
            submit_job(self.conn,binding,self.grant,client)
        client.token=None
        result=poll_one(self.conn,client);self.conn.commit()
        self.assertEqual(result['error_code'],'apify_credentials_missing')
        self.assertGreaterEqual(result['next_poll_seconds'],300)
        client.run.assert_not_called()
        self.assertEqual(self.conn.execute("SELECT status FROM veriflow.integration_status WHERE provider='apify'").fetchone()['status'],'pending_credentials')

    def test_monitor_parallel_process_does_not_duplicate_request(self):
        from veriflow.apify_monitor import poll_one
        with psycopg.connect(self.url,row_factory=dict_row) as other:
            other.execute("SELECT pg_advisory_xact_lock(hashtext('veriflow_apify_monitor'))")
            self.assertEqual(poll_one(self.conn),{'state':'busy'})

    def test_health_detects_pending_monitor_migration(self):
        from veriflow.health import database_health
        with self.admin.transaction():
            self.admin.execute('ALTER TABLE veriflow.apify_jobs RENAME COLUMN next_poll_at TO pending_test_column')
            health=database_health(self.admin)
            self.assertEqual(health['missing_columns'],['next_poll_at'])
            self.assertFalse(health['healthy'])
            self.admin.execute('ALTER TABLE veriflow.apify_jobs RENAME COLUMN pending_test_column TO next_poll_at')

    def test_monitor_retains_terminal_error_and_cost_reservation(self):
        from unittest.mock import patch
        from veriflow.apify_pipeline import submit_job
        from veriflow.apify_monitor import poll_one
        binding,client=self.apify_setup();client.run.return_value['status']='FAILED'
        with patch.dict(os.environ,{'APIFY_MAX_RUN_USD':'1','APIFY_ROLLING_24H_BUDGET_USD':'2'}):
            job=submit_job(self.conn,binding,self.grant,client)
        result=poll_one(self.conn,client);self.conn.commit()
        self.assertEqual(result['error_code'],'apify_run_failed')
        row=self.conn.execute('SELECT state,error_code,reserved_usd,confirmed_billed_usd FROM veriflow.apify_jobs WHERE id=%s',(job['job_id'],)).fetchone()
        self.assertEqual(row['state'],'failed')
        self.assertEqual(row['error_code'],'apify_run_failed')
        self.assertGreater(row['reserved_usd'],0)
        self.assertIsNone(row['confirmed_billed_usd'])
        client.items.assert_not_called()

    def test_monitor_running_job_is_throttled_and_recovers_provider_status(self):
        from unittest.mock import patch
        from veriflow.apify_pipeline import submit_job
        from veriflow.apify_monitor import poll_one
        binding,client=self.apify_setup();client.run.return_value['status']='RUNNING'
        with patch.dict(os.environ,{'APIFY_MAX_RUN_USD':'1','APIFY_ROLLING_24H_BUDGET_USD':'2'}):
            submit_job(self.conn,binding,self.grant,client)
        client.token=None
        poll_one(self.conn,client);self.conn.commit()
        client.token='TEST-TOKEN'
        self.conn.execute('UPDATE veriflow.apify_jobs SET next_poll_at=now()');self.conn.commit()
        self.assertEqual(poll_one(self.conn,client)['state'],'running');self.conn.commit()
        self.assertIsNone(poll_one(self.conn,client))
        self.assertEqual(client.run.call_count,1)
        self.assertEqual(self.conn.execute("SELECT status,error_code FROM veriflow.integration_status WHERE provider='apify'").fetchone(),{'status':'discovered','error_code':None})

    def test_manual_product_category_and_search_are_persistent(self):
        from veriflow.admin_ops import product
        pid=product(self.conn,'New Fixture App','Fixture Vendor','https://example.invalid',['Productivity','Utilities'])
        self.assertEqual(pid,product(self.conn,'new fixture app','fixture vendor',categories=['productivity']))
        self.conn.commit()
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM veriflow.product_categories WHERE product_id=%s',(pid,)).fetchone()['n'],2)
        self.assertIn('New Fixture App',page(self.conn,'/products',{'q':['New Fixture']}))
        self.assertIn('Productivity',page(self.conn,'/categories',{}))

    def test_catalog_discovery_creates_mappings_and_categories_atomically(self):
        from veriflow.admin_ops import discover_catalog
        data=[dict(external_key='test-product',name='Test Product',vendor='Test Vendor',categories=['Automation'])]
        self.assertEqual(discover_catalog(self.conn,self.source,self.grant,data)['products_processed'],1)
        self.assertIn('Automation',page(self.conn,'/categories',{}))
        with self.assertRaises(AccessDenied):discover_catalog(self.conn,self.source,self.grant,[dict(data[0],name='Wrong software')])

    def test_bulk_sources_cannot_bypass_grants_and_settings_are_saved(self):
        from veriflow.admin_ops import source_settings
        with self.assertRaises(AccessDenied):source_settings(self.conn,['g2'],'resume',3600)
        self.conn.rollback()
        source_settings(self.conn,[self.source],'schedule',3600);self.conn.commit()
        self.assertEqual(self.conn.execute("SELECT value FROM veriflow.admin_settings WHERE key='source_preferences'").fetchone()['value']['schedule_seconds'],3600)
        source_settings(self.conn,[self.source],'pause',3600);self.conn.commit()
        self.assertFalse(self.conn.execute('SELECT enabled FROM veriflow.sources WHERE id=%s',(self.source,)).fetchone()['enabled'])

    def test_start_control_queues_idempotent_durable_import_job(self):
        from uuid import uuid4
        from veriflow.admin_ops import request_job
        from veriflow.application_jobs import run_job
        self.queue([fixture()]);self.conn.commit()
        key=str(uuid4());job=request_job(self.conn,'collection',{},key,self.source,self.grant)
        self.assertEqual(job,request_job(self.conn,'collection',{},key,self.source,self.grant));self.conn.commit()
        result=run_job(self.conn);self.conn.commit()
        self.assertEqual(result['state'],'succeeded')
        self.assertEqual(result['inserted'],1)
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM veriflow.reviews').fetchone()['n'],1)
        self.assertIsNone(run_job(self.conn))

    def test_start_control_blocks_paid_actor_even_with_approved_source(self):
        from uuid import uuid4
        from unittest.mock import patch
        from veriflow.admin_ops import request_job
        from veriflow.application_jobs import run_job
        self.apify_setup()
        request_job(self.conn,'collection',{},str(uuid4()),self.source,self.grant);self.conn.commit()
        with patch.dict(os.environ,{'APIFY_PAID_RUNS_ENABLED':'false'}):result=run_job(self.conn)
        self.conn.commit()
        self.assertEqual(result['state'],'blocked')
        self.assertEqual(result['error_code'],'apify_paid_runs_disabled')
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM veriflow.apify_jobs').fetchone()['n'],0)

    def test_background_exports_all_formats_and_private_storage(self):
        import tempfile
        import zipfile
        import xml.etree.ElementTree as ET
        from pathlib import Path
        from uuid import uuid4
        from unittest.mock import patch
        from veriflow.admin_ops import request_job
        from veriflow.application_jobs import run_job
        self.queue([fixture()]);run_one(self.conn);self.conn.commit()
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,{'VERIFLOW_ARTIFACT_DIR':root}):
            for fmt in ('csv','xlsx','json','jsonl','zip'):
                jid=request_job(self.conn,'export',{'format':fmt,'limit':1000},str(uuid4()));self.conn.commit()
                result=run_job(self.conn);self.conn.commit()
                self.assertEqual(result['state'],'succeeded',fmt)
                self.assertEqual(result['records'],1)
                path=Path(root)/result['artifact_name'];self.assertEqual(path.stat().st_mode&0o777,0o600)
                if fmt=='json':self.assertEqual(len(json.loads(path.read_text())),1)
                if fmt=='jsonl':self.assertIn('original_url',json.loads(path.read_text()))
                if fmt=='zip':
                    with zipfile.ZipFile(path) as z:self.assertEqual(json.loads(z.read('manifest.json'))['records'],1)
                if fmt=='xlsx':
                    with zipfile.ZipFile(path) as z:ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
                self.assertIn('Download',page(self.conn,'/exports',{}))

    def test_export_omits_unapproved_text_and_retains_source_reference(self):
        from veriflow.exports import rows
        self.queue([fixture()]);run_one(self.conn);self.conn.commit()
        self.conn.execute('UPDATE veriflow.authorizations SET revoked_at=now() WHERE id=%s',(self.grant,));self.conn.commit()
        records=list(rows(self.conn,{'format':'json'}))
        self.assertIsNone(records[0]['review_text'])
        self.assertTrue(records[0]['original_url'].startswith('https://'))

    def test_admin_job_and_category_tables_are_private(self):
        for name in ('admin_jobs','categories','product_categories','admin_settings'):
            row=self.conn.execute("SELECT c.relrowsecurity,has_table_privilege('anon',c.oid,'SELECT') AS public_read FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='veriflow' AND c.relname=%s",(name,)).fetchone()
            self.assertTrue(row['relrowsecurity']);self.assertFalse(row['public_read'])
        for path in ('/collect','/jobs','/settings','/coverage','/exports'):
            self.assertIn('Veriflow',page(self.conn,path,{},'fixture-token'))

    def test_review_inspection_includes_duplicate_links_and_escapes_text(self):
        row=fixture();row['review_text']='<script>fixture attack</script>'
        self.queue([row]);run_one(self.conn);self.conn.commit()
        rid=str(self.conn.execute('SELECT id FROM veriflow.reviews').fetchone()['id'])
        text=page(self.conn,'/reviews/'+rid,{})
        self.assertIn('&lt;script&gt;',text);self.assertNotIn('<script>fixture',text)
        self.assertIn('Potential duplicate',text)

    def test_authorized_thousand_review_batch_and_bounded_export(self):
        from veriflow.exports import rows
        records=[dict(fixture(),external_id='bulk-fixture-'+str(n),review_text='TEST FIXTURE ONLY review '+str(n),original_url='https://capterra.com/reviews/bulk-fixture-'+str(n)) for n in range(1000)]
        self.queue(records);result=run_one(self.conn);self.conn.commit()
        self.assertEqual(result['inserted'],1000)
        self.assertEqual(sum(1 for _ in rows(self.conn,{'format':'jsonl','limit':750})),750)
        self.conn.commit()
        self.conn.execute('UPDATE veriflow.sources SET next_run_at=now() WHERE id=%s',(self.source,));self.conn.commit()
        self.queue(records);result=run_one(self.conn);self.conn.commit()
        self.assertEqual(result['inserted'],0);self.assertEqual(result['duplicates'],1000)

    def test_catalog_job_creates_products_without_generating_reviews(self):
        from uuid import uuid4
        from veriflow.admin_ops import request_job
        from veriflow.application_jobs import run_job
        payload={'records':[dict(external_key='test-product',name='Test Product',vendor='Test Vendor',categories=['Catalog fixture'])]}
        request_job(self.conn,'catalog',payload,str(uuid4()),self.source,self.grant);self.conn.commit()
        result=run_job(self.conn);self.conn.commit()
        self.assertEqual(result['state'],'succeeded')
        self.assertEqual(result['products_processed'],1)
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM veriflow.reviews').fetchone()['n'],0)

    def test_source_permission_requires_explicit_review_and_keeps_paused(self):
        from veriflow.admin_ops import record_permission
        expiry='2027-01-01T00:00:00+00:00'
        evidence='TEST FIXTURE ONLY — scoped permission evidence'
        with self.assertRaises(AccessDenied):record_permission(self.conn,'g2','approved_import',evidence,['fixture-key'],expiry,True,False,True)
        with self.assertRaises(AccessDenied):record_permission(self.conn,'g2','approved_import',evidence,['fixture-key'],expiry,True,True,False)
        record_permission(self.conn,'g2','approved_import',evidence,['fixture-key'],expiry,False,True,False);self.conn.commit()
        row=self.conn.execute("SELECT enabled,access_status FROM veriflow.sources WHERE id='g2'").fetchone()
        self.assertFalse(row['enabled']);self.assertEqual(row['access_status'],'approved')

    def test_bulk_jsonl_streams_into_multiple_durable_batches(self):
        from veriflow.bulk_import import import_file
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'approved-fixtures.jsonl'
            path.write_text('\n'.join(json.dumps(dict(fixture(),external_id='stream-'+str(n),review_text='TEST FIXTURE ONLY '+str(n),original_url='https://capterra.com/reviews/stream-'+str(n))) for n in range(1001)))
            result=import_file(self.conn,path,self.source,self.grant)
        self.assertEqual(result,dict(records_queued=1001,batches=2))
        self.assertEqual(self.conn.execute("SELECT count(*) AS n FROM veriflow.import_batches WHERE status='pending'").fetchone()['n'],2)

    def test_interrupted_application_job_is_recovered_without_duplicate_write(self):
        from uuid import uuid4
        from veriflow.admin_ops import request_job
        from veriflow.application_jobs import run_job
        self.queue([fixture()]);self.conn.commit()
        jid=request_job(self.conn,'collection',{},str(uuid4()),self.source,self.grant);self.conn.commit()
        self.conn.execute("UPDATE veriflow.admin_jobs SET state='running',started_at=now(),attempts=1 WHERE id=%s",(jid,));self.conn.commit()
        self.assertEqual(run_job(self.conn)['state'],'succeeded')
        self.assertEqual(self.conn.execute('SELECT attempts FROM veriflow.admin_jobs WHERE id=%s',(jid,)).fetchone()['attempts'],2)
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM veriflow.reviews').fetchone()['n'],1)

    def test_import_backlog_drains_at_minimum_interval_not_daily_schedule(self):
        self.queue([fixture()]);self.queue([dict(fixture(),external_id='backlog-2')]);self.conn.commit()
        run_one(self.conn);self.conn.commit()
        row=self.conn.execute('SELECT extract(epoch FROM next_run_at-last_run_at) AS delay,minimum_interval_seconds FROM veriflow.sources WHERE id=%s',(self.source,)).fetchone()
        self.assertEqual(int(row['delay']),row['minimum_interval_seconds'])

    def test_start_after_scheduled_ingestion_reports_no_pending_imports(self):
        from uuid import uuid4
        from veriflow.admin_ops import request_job
        from veriflow.application_jobs import run_job
        request_job(self.conn,'collection',{},str(uuid4()),self.source,self.grant);self.conn.commit()
        result=run_job(self.conn)
        self.assertEqual(result['state'],'succeeded')
        self.assertEqual(result['status'],'no_pending_imports')
        self.assertEqual(result['inserted'],0)
