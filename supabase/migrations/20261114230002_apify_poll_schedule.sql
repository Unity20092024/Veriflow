-- Scheduling metadata only; does not enable sources or authorize paid starts.
ALTER TABLE veriflow.apify_jobs
 ADD COLUMN next_poll_at timestamptz NOT NULL DEFAULT now(),
 ADD COLUMN poll_failures integer NOT NULL DEFAULT 0 CHECK (poll_failures >= 0);
CREATE INDEX apify_jobs_poll_due_idx ON veriflow.apify_jobs(next_poll_at,created_at)
 WHERE state='running' AND actor_run_id IS NOT NULL;
