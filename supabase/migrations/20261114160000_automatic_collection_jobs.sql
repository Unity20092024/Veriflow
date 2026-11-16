CREATE TABLE veriflow.collection_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scope text NOT NULL CHECK (scope IN ('category','product','all_eligible')),
  category text CHECK (category IN (
    'software_review_directory','software_discovery','app_marketplace',
    'community_discussion','review_aggregation','market_research'
  )),
  product_id uuid REFERENCES veriflow.products(id),
  state text NOT NULL DEFAULT 'queued'
    CHECK (state IN ('queued','running','completed','partial','failed','cancelled')),
  requested_sources integer NOT NULL DEFAULT 0 CHECK (requested_sources >= 0),
  completed_sources integer NOT NULL DEFAULT 0 CHECK (completed_sources >= 0),
  pages_fetched integer NOT NULL DEFAULT 0 CHECK (pages_fetched >= 0),
  reviews_retrieved integer NOT NULL DEFAULT 0 CHECK (reviews_retrieved >= 0),
  inserted integer NOT NULL DEFAULT 0 CHECK (inserted >= 0),
  duplicates integer NOT NULL DEFAULT 0 CHECK (duplicates >= 0),
  error_code text,
  created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  CHECK (
    (scope = 'category' AND category IS NOT NULL AND product_id IS NULL) OR
    (scope = 'product' AND category IS NULL AND product_id IS NOT NULL) OR
    (scope = 'all_eligible' AND category IS NULL AND product_id IS NULL)
  )
);

CREATE INDEX collection_jobs_state_created_idx
  ON veriflow.collection_jobs(state,created_at);

CREATE TABLE veriflow.collection_job_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid NOT NULL REFERENCES veriflow.collection_jobs(id) ON DELETE CASCADE,
  source_id text NOT NULL REFERENCES veriflow.sources(id),
  product_id uuid NOT NULL REFERENCES veriflow.products(id),
  product_key text NOT NULL,
  authorization_id uuid NOT NULL REFERENCES veriflow.authorizations(id),
  state text NOT NULL DEFAULT 'queued'
    CHECK (state IN ('queued','fetching','awaiting_ingest','completed','failed','cancelled')),
  cursor_url text,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  lease_until timestamptz,
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  pages_fetched integer NOT NULL DEFAULT 0 CHECK (pages_fetched >= 0),
  reviews_retrieved integer NOT NULL DEFAULT 0 CHECK (reviews_retrieved >= 0),
  inserted integer NOT NULL DEFAULT 0 CHECK (inserted >= 0),
  duplicates integer NOT NULL DEFAULT 0 CHECK (duplicates >= 0),
  error_code text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  UNIQUE(job_id,source_id,product_key)
);

CREATE INDEX collection_job_items_claim_idx
  ON veriflow.collection_job_items(state,next_attempt_at,created_at);
CREATE INDEX collection_job_items_job_idx
  ON veriflow.collection_job_items(job_id,state);

ALTER TABLE veriflow.import_batches
  ADD COLUMN collection_job_item_id uuid
  REFERENCES veriflow.collection_job_items(id) ON DELETE SET NULL;
CREATE INDEX import_batches_collection_job_item_idx
  ON veriflow.import_batches(collection_job_item_id)
  WHERE collection_job_item_id IS NOT NULL;

ALTER TABLE veriflow.collection_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE veriflow.collection_job_items ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON veriflow.collection_jobs,veriflow.collection_job_items FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON veriflow.collection_jobs,veriflow.collection_job_items TO veriflow_runtime;
CREATE POLICY runtime_access ON veriflow.collection_jobs
  TO veriflow_runtime USING (true) WITH CHECK (true);
CREATE POLICY runtime_access ON veriflow.collection_job_items
  TO veriflow_runtime USING (true) WITH CHECK (true);
