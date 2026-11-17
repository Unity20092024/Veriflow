"""Upgrade tests use only disposable PostgreSQL, never a Supabase endpoint."""
import os
import re
import unittest
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'Disposable PostgreSQL required')
class MigrationUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.settings=conninfo_to_dict(os.environ['TEST_DATABASE_URL'])
        if self.settings.get('host') not in ('localhost','127.0.0.1'):self.skipTest('Upgrade harness is local-only')
        self.admin=psycopg.connect(**self.settings,autocommit=True,row_factory=dict_row)
        self.name='veriflow_upgrade_'+uuid4().hex
        self.admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(self.name)))
        self.conn=psycopg.connect(**dict(self.settings,dbname=self.name),row_factory=dict_row)
        migrations=sorted(Path('supabase/migrations').glob('*.sql'))
        self.pending=[m for m in migrations if m.name.startswith(('20261114230002_','20261115003835_'))]
        self.additions=[m for m in migrations if m.name.startswith('20261115032307_')]
        for migration in migrations:
            if migration in self.pending+self.additions:continue
            text=migration.read_text()
            # Roles are cluster-wide and already exist in the disposable test
            # cluster; schema changes are exercised verbatim in this new DB.
            text=re.sub(r'^CREATE ROLE (?:veriflow_runtime|veriflow_app) .*?;\s*','',text,flags=re.M)
            self.conn.execute(text)
        self.conn.execute("INSERT INTO veriflow.products(name,vendor) VALUES ('Preserved Fixture','Vendor')")
        self.conn.commit()
    def tearDown(self):
        self.conn.close()
        self.admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(self.name)));self.admin.close()
    def snapshot(self):
        return self.conn.execute("SELECT tablename,policyname,roles,qual,with_check FROM pg_policies WHERE schemaname='veriflow' ORDER BY tablename,policyname").fetchall()
    def test_pending_migrations_preserve_existing_data_and_security(self):
        old=self.snapshot()
        for migration in self.pending:
            self.conn.execute("SET LOCAL lock_timeout='5s'");self.conn.execute(migration.read_text())
        for migration in self.additions:self.conn.execute(migration.read_text())
        self.conn.commit()
        self.assertEqual(self.conn.execute('SELECT name FROM veriflow.products').fetchone()['name'],'Preserved Fixture')
        after=self.snapshot()
        for policy in old:self.assertIn(policy,after)
        private=self.conn.execute("SELECT bool_and(c.relrowsecurity) AS rls,bool_and(NOT has_table_privilege('anon',c.oid,'SELECT') AND NOT has_table_privilege('authenticated',c.oid,'SELECT')) AS denied FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='veriflow' AND c.relkind='r'").fetchone()
        self.assertTrue(private['rls']);self.assertTrue(private['denied'])
    def test_conflicting_normalized_product_index_rolls_back_safely(self):
        self.conn.execute("INSERT INTO veriflow.products(name,vendor) VALUES ('preserved fixture','vendor')");self.conn.commit()
        with self.assertRaises(psycopg.errors.UniqueViolation):
            with self.conn.transaction():self.conn.execute(self.pending[-1].read_text())
        self.assertIsNone(self.conn.execute("SELECT to_regclass('veriflow.categories') AS table").fetchone()['table'])
        self.assertEqual(self.conn.execute('SELECT count(*) AS n FROM veriflow.products').fetchone()['n'],2)
