ALTER TABLE veriflow.sources DROP CONSTRAINT sources_collection_method_check;
ALTER TABLE veriflow.sources ADD CONSTRAINT sources_collection_method_check
 CHECK (collection_method IN ('approved_import','authorized_api','permitted_crawl','composio','apify'));
ALTER TABLE veriflow.authorizations DROP CONSTRAINT authorizations_method_check;
ALTER TABLE veriflow.authorizations ADD CONSTRAINT authorizations_method_check
 CHECK (method IN ('approved_import','authorized_api','permitted_crawl','composio','apify'));

CREATE TABLE veriflow.apify_bindings (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 source_id text NOT NULL REFERENCES veriflow.sources(id),
 product_key text NOT NULL,
 actor_id text NOT NULL, build_number text NOT NULL, build_id text NOT NULL,
 approved_input jsonb NOT NULL, input_schema jsonb NOT NULL,
 target_url text NOT NULL, target_input_path text[] NOT NULL,
 limit_input_key text NOT NULL, field_mapping jsonb NOT NULL,
 pricing_snapshot jsonb NOT NULL,
 max_records integer NOT NULL CHECK (max_records BETWEEN 1 AND 1000),
 max_charge_usd numeric(12,6) NOT NULL CHECK (max_charge_usd > 0),
 timeout_seconds integer NOT NULL CHECK (timeout_seconds BETWEEN 30 AND 3600),
 approved_by text NOT NULL, approval_evidence text NOT NULL CHECK (length(trim(approval_evidence))>0),
 enabled boolean NOT NULL DEFAULT false,
 FOREIGN KEY(source_id,product_key) REFERENCES veriflow.source_products(source_id,external_key)
);
CREATE TABLE veriflow.apify_jobs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 binding_id uuid NOT NULL REFERENCES veriflow.apify_bindings(id),
 source_id text NOT NULL REFERENCES veriflow.sources(id),
 authorization_id uuid NOT NULL REFERENCES veriflow.authorizations(id),
 state text NOT NULL CHECK (state IN ('starting','start_unknown','running','queued','ingested','failed','aborted')),
 actor_id text NOT NULL, build_id text NOT NULL, binding_fingerprint text NOT NULL,
 actor_run_id text UNIQUE, dataset_id text,
 reserved_usd numeric(12,6) NOT NULL CHECK (reserved_usd>0),
 reported_usage_usd numeric(12,6) CHECK (reported_usage_usd>=0),
 confirmed_billed_usd numeric(12,6) CHECK (confirmed_billed_usd>=0),
 retrieved integer NOT NULL DEFAULT 0, inserted integer NOT NULL DEFAULT 0, duplicates integer NOT NULL DEFAULT 0,
 error_code text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON veriflow.apify_bindings(source_id,product_key);
CREATE INDEX ON veriflow.apify_jobs(binding_id);
CREATE INDEX ON veriflow.apify_jobs(source_id,created_at DESC);
CREATE INDEX ON veriflow.apify_jobs(authorization_id);
CREATE INDEX ON veriflow.apify_jobs(created_at);
ALTER TABLE veriflow.import_batches ADD COLUMN provider_job_id uuid UNIQUE REFERENCES veriflow.apify_jobs(id);
ALTER TABLE veriflow.collection_runs ADD COLUMN provider_job_id uuid REFERENCES veriflow.apify_jobs(id);
CREATE INDEX ON veriflow.collection_runs(provider_job_id);
ALTER TABLE veriflow.apify_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE veriflow.apify_jobs ENABLE ROW LEVEL SECURITY;
CREATE POLICY runtime_access ON veriflow.apify_bindings TO veriflow_runtime USING (true) WITH CHECK (true);
CREATE POLICY runtime_access ON veriflow.apify_jobs TO veriflow_runtime USING (true) WITH CHECK (true);
REVOKE ALL ON veriflow.apify_bindings,veriflow.apify_jobs FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON veriflow.apify_bindings,veriflow.apify_jobs TO veriflow_runtime;
INSERT INTO veriflow.integration_status(provider,status,error_code)
 VALUES ('apify','pending_credentials','credentials_missing') ON CONFLICT(provider) DO NOTHING;

-- Some official review exports expose a shared listing URL rather than a
-- per-review permalink. Native review IDs and content fingerprints deduplicate
-- records without dropping distinct reviews on that shared page.
ALTER TABLE veriflow.reviews DROP CONSTRAINT reviews_source_id_original_url_key;
CREATE INDEX reviews_source_url_idx ON veriflow.reviews(source_id,original_url);
