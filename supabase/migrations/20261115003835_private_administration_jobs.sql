-- Additive private administration. No sources, grants or paid execution enabled.
CREATE TABLE veriflow.categories (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),name text NOT NULL,
 CHECK(length(trim(name)) BETWEEN 1 AND 120)
);
CREATE UNIQUE INDEX categories_name_normalized ON veriflow.categories(lower(trim(name)));
CREATE TABLE veriflow.product_categories (
 product_id uuid NOT NULL REFERENCES veriflow.products(id) ON DELETE CASCADE,
 category_id uuid NOT NULL REFERENCES veriflow.categories(id) ON DELETE CASCADE,
 PRIMARY KEY(product_id,category_id)
);
CREATE INDEX product_categories_category_idx ON veriflow.product_categories(category_id,product_id);
ALTER TABLE veriflow.products ADD COLUMN website text;
CREATE UNIQUE INDEX products_identity_normalized ON veriflow.products(lower(trim(name)),lower(trim(vendor)));
CREATE TABLE veriflow.admin_settings (
 key text PRIMARY KEY,value jsonb NOT NULL,updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE veriflow.admin_jobs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 kind text NOT NULL CHECK(kind IN ('collection','catalog','export')),
 source_id text REFERENCES veriflow.sources(id),authorization_id uuid REFERENCES veriflow.authorizations(id),
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0),
 state text NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','running','succeeded','blocked','failed','cancelled')),
 payload jsonb NOT NULL DEFAULT '{}',result jsonb NOT NULL DEFAULT '{}',error_code text,
 provider_job_id uuid REFERENCES veriflow.apify_jobs(id),
 request_key uuid NOT NULL UNIQUE,
 created_at timestamptz NOT NULL DEFAULT now(),started_at timestamptz,finished_at timestamptz,
 artifact_name text,artifact_expires_at timestamptz
);
CREATE INDEX admin_jobs_due_idx ON veriflow.admin_jobs(created_at,id) WHERE state='queued';
CREATE INDEX admin_jobs_source_idx ON veriflow.admin_jobs(source_id,created_at DESC);
CREATE INDEX admin_jobs_authorization_idx ON veriflow.admin_jobs(authorization_id);
CREATE INDEX admin_jobs_provider_idx ON veriflow.admin_jobs(provider_job_id);
CREATE INDEX admin_jobs_history_idx ON veriflow.admin_jobs(created_at DESC);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['categories','product_categories','admin_settings','admin_jobs'] LOOP
  EXECUTE format('ALTER TABLE veriflow.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY runtime_access ON veriflow.%I TO veriflow_runtime USING(true) WITH CHECK(true)',t);
  EXECUTE format('REVOKE ALL ON veriflow.%I FROM PUBLIC,anon,authenticated',t);
  EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON veriflow.%I TO veriflow_runtime',t);
 END LOOP;
END $$;
