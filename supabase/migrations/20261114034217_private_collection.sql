-- Private schema: never add veriflow to Supabase exposed Data API schemas.
CREATE SCHEMA veriflow;
REVOKE ALL ON SCHEMA veriflow FROM PUBLIC;
-- Group role; create a separate LOGIN and grant it membership at deployment.
CREATE ROLE veriflow_runtime NOLOGIN;
GRANT USAGE ON SCHEMA veriflow TO veriflow_runtime;

CREATE TABLE veriflow.sources (
 id text PRIMARY KEY, name text NOT NULL UNIQUE, url text NOT NULL UNIQUE,
 category text NOT NULL CHECK (category IN ('software_review_directory','software_discovery','app_marketplace','community_discussion','review_aggregation','market_research')),
 aliases text[] NOT NULL DEFAULT '{}', provenance text NOT NULL,
 collection_method text NOT NULL CHECK (collection_method IN ('approved_import','authorized_api','permitted_crawl','composio')),
 access_status text NOT NULL CHECK (access_status IN ('pending_authorization','pending_discovery','approved','blocked')),
 enabled boolean NOT NULL DEFAULT false, full_text_allowed boolean NOT NULL DEFAULT false,
 schedule_seconds integer NOT NULL DEFAULT 86400 CHECK (schedule_seconds >= 60),
 minimum_interval_seconds integer NOT NULL DEFAULT 60 CHECK (minimum_interval_seconds >= 1),
 next_run_at timestamptz NOT NULL DEFAULT now(), failures integer NOT NULL DEFAULT 0,
 last_status text, last_run_at timestamptz, policy_notes text NOT NULL
);
CREATE TABLE veriflow.authorizations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), source_id text NOT NULL REFERENCES veriflow.sources(id),
 method text NOT NULL CHECK (method IN ('approved_import','authorized_api','permitted_crawl','composio')),
 evidence text NOT NULL CHECK (length(trim(evidence)) > 0),
 product_keys text[] NOT NULL CHECK (cardinality(product_keys) > 0),
 full_text_allowed boolean NOT NULL DEFAULT false,
 approved_by text NOT NULL, expires_at timestamptz NOT NULL,
 revoked_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON veriflow.authorizations(source_id, expires_at);
CREATE TABLE veriflow.products (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL,
 vendor text NOT NULL, UNIQUE(name,vendor), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE veriflow.source_products (
 source_id text NOT NULL REFERENCES veriflow.sources(id), external_key text NOT NULL,
 product_id uuid NOT NULL REFERENCES veriflow.products(id),
 expected_name text NOT NULL, PRIMARY KEY(source_id,external_key)
);
CREATE INDEX ON veriflow.source_products(product_id);
CREATE TABLE veriflow.import_batches (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), source_id text NOT NULL REFERENCES veriflow.sources(id),
 authorization_id uuid NOT NULL REFERENCES veriflow.authorizations(id),
 records jsonb NOT NULL CHECK (jsonb_typeof(records) = 'array'),
 status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','completed','failed')),
 created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz
);
CREATE INDEX ON veriflow.import_batches(source_id,created_at) WHERE status='pending';
CREATE TABLE veriflow.collection_runs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), source_id text NOT NULL REFERENCES veriflow.sources(id),
 batch_id uuid REFERENCES veriflow.import_batches(id),
 status text NOT NULL CHECK (status IN ('success','error','rate_limited','idle')),
 inserted integer NOT NULL DEFAULT 0, duplicates integer NOT NULL DEFAULT 0,
 error_code text, started_at timestamptz NOT NULL, finished_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON veriflow.collection_runs(source_id,started_at DESC);
CREATE TABLE veriflow.reviews (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), source_id text NOT NULL REFERENCES veriflow.sources(id),
 product_id uuid NOT NULL REFERENCES veriflow.products(id), external_id text NOT NULL,
 software_name text NOT NULL, review_text text, rating double precision, rating_scale double precision,
 published_at date NOT NULL, original_url text NOT NULL,
 collected_at timestamptz NOT NULL DEFAULT now(),
 authorization_id uuid NOT NULL REFERENCES veriflow.authorizations(id),
 run_id uuid NOT NULL REFERENCES veriflow.collection_runs(id),
 fingerprint text NOT NULL, duplicate_group text,
 CHECK ((rating IS NULL AND rating_scale IS NULL) OR (rating IS NOT NULL AND rating_scale IS NOT NULL AND rating >= 0 AND rating <= rating_scale AND rating_scale > 0 AND rating_scale <= 100)),
 UNIQUE(source_id,external_id), UNIQUE(source_id,original_url), UNIQUE(source_id,product_id,fingerprint)
);
CREATE INDEX ON veriflow.reviews(product_id,published_at DESC);
CREATE INDEX ON veriflow.reviews(source_id,published_at DESC);
CREATE INDEX ON veriflow.reviews(duplicate_group) WHERE duplicate_group IS NOT NULL;
CREATE INDEX ON veriflow.reviews(authorization_id);
CREATE INDEX ON veriflow.reviews(run_id);
CREATE TABLE veriflow.trends_research (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), source_id text NOT NULL REFERENCES veriflow.sources(id) CHECK (source_id='google-trends'),
 query text NOT NULL, geography text NOT NULL, time_range text NOT NULL,
 tool_slug text NOT NULL, tool_version text NOT NULL, original_url text NOT NULL,
 data jsonb NOT NULL, collected_at timestamptz NOT NULL DEFAULT now(),
 authorization_id uuid NOT NULL REFERENCES veriflow.authorizations(id)
);
CREATE INDEX ON veriflow.trends_research(collected_at DESC);
CREATE INDEX ON veriflow.trends_research(authorization_id);
CREATE INDEX ON veriflow.sources(next_run_at) WHERE enabled;
-- No grants to anon/authenticated. An explicit runtime role is required even for
-- direct SQL connections. RLS is defense in depth inside this unexposed schema.
DO $$ DECLARE t text; BEGIN
 FOR t IN SELECT tablename FROM pg_tables WHERE schemaname='veriflow' LOOP
  EXECUTE format('ALTER TABLE veriflow.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY runtime_access ON veriflow.%I TO veriflow_runtime USING (true) WITH CHECK (true)',t);
 END LOOP;
END $$;
GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA veriflow TO veriflow_runtime;
-- PUBLIC has no access; new tables get no runtime privileges until reviewed.
REVOKE ALL ON ALL TABLES IN SCHEMA veriflow FROM PUBLIC;
