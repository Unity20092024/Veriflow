-- Additive checkpoints for the explicitly approved, one-time lib.reviews batch.
CREATE TABLE veriflow.free_batches (
 id text PRIMARY KEY,
 authorization_id uuid REFERENCES veriflow.authorizations(id),
 state text NOT NULL DEFAULT 'running' CHECK(state IN ('running','completed','limited','expired','blocked')),
 started_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL DEFAULT now()+interval '48 hours',
 max_unique integer NOT NULL DEFAULT 500 CHECK(max_unique=500),
 max_products integer NOT NULL DEFAULT 100 CHECK(max_products=100),
 max_requests integer NOT NULL DEFAULT 1500 CHECK(max_requests=1500),
 max_pages integer NOT NULL DEFAULT 10 CHECK(max_pages=10),
 requests integer NOT NULL DEFAULT 0 CHECK(requests BETWEEN 0 AND 1500),
 failed_requests integer NOT NULL DEFAULT 0,
 next_http_at timestamptz NOT NULL DEFAULT now(),
 policy_hash text,
 error_code text,
 updated_at timestamptz NOT NULL DEFAULT now(),
 CHECK(expires_at<=started_at+interval '48 hours')
);
CREATE TABLE veriflow.free_batch_products (
 batch_id text NOT NULL REFERENCES veriflow.free_batches(id),
 product_id uuid NOT NULL REFERENCES veriflow.products(id),
 url text NOT NULL,
 name text NOT NULL,
 category text NOT NULL,
 PRIMARY KEY(batch_id,url)
);
CREATE TABLE veriflow.free_batch_tasks (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 batch_id text NOT NULL REFERENCES veriflow.free_batches(id),
 kind text NOT NULL CHECK(kind IN ('discover','listing','review')),
 url text NOT NULL,
 data jsonb NOT NULL,
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','importing','done','failed')),
 batch_import_id uuid REFERENCES veriflow.import_batches(id),
 error_code text,
 UNIQUE(batch_id,kind,url)
);
CREATE INDEX free_batch_tasks_pending ON veriflow.free_batch_tasks(batch_id,state,id);
ALTER TABLE veriflow.free_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE veriflow.free_batch_products ENABLE ROW LEVEL SECURITY;
ALTER TABLE veriflow.free_batch_tasks ENABLE ROW LEVEL SECURITY;
CREATE POLICY runtime_access ON veriflow.free_batches TO veriflow_runtime USING(true) WITH CHECK(true);
CREATE POLICY runtime_access ON veriflow.free_batch_products TO veriflow_runtime USING(true) WITH CHECK(true);
CREATE POLICY runtime_access ON veriflow.free_batch_tasks TO veriflow_runtime USING(true) WITH CHECK(true);
REVOKE ALL ON veriflow.free_batches,veriflow.free_batch_products,veriflow.free_batch_tasks FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON veriflow.free_batches,veriflow.free_batch_products,veriflow.free_batch_tasks TO veriflow_runtime;
GRANT USAGE,SELECT ON SEQUENCE veriflow.free_batch_tasks_id_seq TO veriflow_runtime;
