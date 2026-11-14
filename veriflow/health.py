"""Read-only deployment verification, with no credentials in the result."""
EXPECTED = {'sources','authorizations','products','source_products','import_batches',
            'collection_runs','reviews','trends_research','integration_status','integration_bindings','apify_bindings','apify_jobs'}


def database_health(conn):
    tables=conn.execute('''SELECT c.relname,c.relrowsecurity,
        has_table_privilege('anon',c.oid,'SELECT') AS anon_select,
        has_table_privilege('authenticated',c.oid,'SELECT') AS authenticated_select
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='veriflow' AND c.relkind='r' ''').fetchall()
    roles=conn.execute('''SELECT rolname,rolsuper,rolbypassrls,
        pg_has_role(current_user,'veriflow_runtime','MEMBER') AS runtime_member
        FROM pg_roles WHERE rolname=current_user''').fetchone()
    counts=conn.execute('''SELECT count(*) AS sources,count(*) FILTER (WHERE enabled) AS enabled_sources
        FROM veriflow.sources''').fetchone()
    namespaces=conn.execute("SELECT has_schema_privilege('anon','veriflow','USAGE') AS anon_access,has_schema_privilege('authenticated','veriflow','USAGE') AS authenticated_access").fetchone()
    # Verify the application's TLS connection, including a pooler transport.
    ssl = conn.pgconn.ssl_in_use
    owner=conn.execute("SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='veriflow' AND pg_get_userbyid(c.relowner)=current_user) AS owns_tables").fetchone()['owns_tables']
    present={t['relname'] for t in tables}
    private=not any(t['anon_select'] or t['authenticated_select'] for t in tables) and not any(namespaces.values())
    rls=all(t['relrowsecurity'] for t in tables)
    app_role=roles['rolname']=='veriflow_app' and roles['runtime_member'] and not roles['rolsuper'] and not roles['rolbypassrls'] and not owner
    result=dict(tables=sorted(present),missing_tables=sorted(EXPECTED-present),rls_enabled=rls,
                public_access_denied=private,application_role=bool(app_role),tls=bool(ssl),**counts)
    result['healthy']=not result['missing_tables'] and rls and private and app_role and result['tls'] and counts['sources']==42
    return result
