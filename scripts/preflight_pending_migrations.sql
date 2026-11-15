-- Read-only. Run only against the existing dedicated Veriflow project.
BEGIN READ ONLY;
SELECT count(*) AS normalized_product_conflicts FROM (
 SELECT lower(trim(name)),lower(trim(vendor)) FROM veriflow.products
 GROUP BY 1,2 HAVING count(*)>1
) conflicts;
SELECT count(*) AS existing_apify_jobs FROM veriflow.apify_jobs;
SELECT tablename,rowsecurity FROM pg_tables WHERE schemaname='veriflow' ORDER BY tablename;
SELECT c.relname,
 has_table_privilege('anon',c.oid,'SELECT') AS anon_select,
 has_table_privilege('authenticated',c.oid,'SELECT') AS authenticated_select
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='veriflow' AND c.relkind='r' ORDER BY c.relname;
SELECT rolname,rolcanlogin,rolsuper,rolbypassrls,rolcreaterole,rolcreatedb
FROM pg_roles WHERE rolname IN ('veriflow_app','veriflow_runtime');
COMMIT;
