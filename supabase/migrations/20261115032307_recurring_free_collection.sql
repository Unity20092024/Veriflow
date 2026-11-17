-- Recurrence for explicitly enabled free-source selections. No schedule is seeded.
CREATE TABLE veriflow.recurring_schedules (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 source_id text NOT NULL REFERENCES veriflow.sources(id),
 product_id uuid REFERENCES veriflow.products(id) ON DELETE CASCADE,
 category_id uuid REFERENCES veriflow.categories(id) ON DELETE CASCADE,
 interval_seconds integer NOT NULL DEFAULT 86400 CHECK(interval_seconds BETWEEN 21600 AND 604800),
 max_reviews integer NOT NULL DEFAULT 20 CHECK(max_reviews BETWEEN 1 AND 20),
 enabled boolean NOT NULL DEFAULT false,
 next_run_at timestamptz NOT NULL DEFAULT now(),
 last_job_id uuid REFERENCES veriflow.admin_jobs(id) ON DELETE SET NULL,
 last_status text,last_error text,last_queued_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),
 CHECK((product_id IS NULL) <> (category_id IS NULL)),
 UNIQUE NULLS NOT DISTINCT(source_id,product_id,category_id)
);
CREATE INDEX recurring_due_idx ON veriflow.recurring_schedules(next_run_at,id) WHERE enabled;
CREATE INDEX recurring_product_idx ON veriflow.recurring_schedules(product_id);
CREATE INDEX recurring_category_idx ON veriflow.recurring_schedules(category_id);
CREATE INDEX recurring_job_idx ON veriflow.recurring_schedules(last_job_id);
ALTER TABLE veriflow.recurring_schedules ENABLE ROW LEVEL SECURITY;
CREATE POLICY runtime_access ON veriflow.recurring_schedules TO veriflow_runtime USING(true) WITH CHECK(true);
REVOKE ALL ON veriflow.recurring_schedules FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON veriflow.recurring_schedules TO veriflow_runtime;
