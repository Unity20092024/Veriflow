-- Read-only: inspect the existing project before selectively porting ff62e18.
-- No credentials, review bodies, author identities, DDL, writes or source calls.
SELECT jsonb_build_object(
 'checked_at',now(),
 'counts',jsonb_build_object(
   'sources',(SELECT count(*) FROM veriflow.sources),
   'enabled_sources',(SELECT count(*) FROM veriflow.sources WHERE enabled),
   'products',(SELECT count(*) FROM veriflow.products),
   'reviews',(SELECT count(*) FROM veriflow.reviews)),
 'tables',(SELECT jsonb_agg(jsonb_build_object(
   'name',c.relname,'rls',c.relrowsecurity,
   'anon_select',has_table_privilege('anon',c.oid,'SELECT'),
   'authenticated_select',has_table_privilege('authenticated',c.oid,'SELECT')) ORDER BY c.relname)
   FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE n.nspname='veriflow' AND c.relkind='r'),
 'compatibility',jsonb_build_object(
   'categories_exist',to_regclass('veriflow.categories') IS NOT NULL,
   'product_categories_exist',to_regclass('veriflow.product_categories') IS NOT NULL,
   'replit_jobs_exist',to_regclass('veriflow.collection_jobs') IS NOT NULL,
   'replit_job_items_exist',to_regclass('veriflow.collection_job_items') IS NOT NULL,
   'replit_free_batches_exist',to_regclass('veriflow.free_batches') IS NOT NULL,
   'replit_free_batch_tasks_exist',to_regclass('veriflow.free_batch_tasks') IS NOT NULL,
   'replit_free_batch_products_exist',to_regclass('veriflow.free_batch_products') IS NOT NULL,
   'codex_admin_jobs_exist',to_regclass('veriflow.admin_jobs') IS NOT NULL,
   'codex_admin_settings_exist',to_regclass('veriflow.admin_settings') IS NOT NULL,
   'codex_recurring_exist',to_regclass('veriflow.recurring_schedules') IS NOT NULL,
   'product_website_exists',EXISTS(SELECT 1 FROM information_schema.columns
     WHERE table_schema='veriflow' AND table_name='products' AND column_name='website'),
   'apify_poll_column_count',(SELECT count(*) FROM information_schema.columns
     WHERE table_schema='veriflow' AND table_name='apify_jobs' AND column_name IN ('next_poll_at','poll_failures'))),
 'normalized_product_conflicts',(SELECT count(*) FROM (
   SELECT lower(trim(name)),lower(trim(vendor)) FROM veriflow.products GROUP BY 1,2 HAVING count(*)>1) x),
 'normal_schema_usage',jsonb_build_object(
   'anon',has_schema_privilege('anon','veriflow','USAGE'),
   'authenticated',has_schema_privilege('authenticated','veriflow','USAGE')),
 'collection_started_by_this_preflight',false
) AS replit_integration_preflight;
