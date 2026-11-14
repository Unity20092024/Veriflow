-- No source approvals, paid jobs or registry activation in this migration.
ALTER TABLE veriflow.sources ADD COLUMN required_license_id text;
ALTER TABLE veriflow.sources ADD COLUMN attribution_required boolean NOT NULL DEFAULT false;
ALTER TABLE veriflow.authorizations ADD COLUMN license_id text;
ALTER TABLE veriflow.authorizations ADD COLUMN terms_url text;
ALTER TABLE veriflow.apify_bindings ADD COLUMN pricing_review jsonb NOT NULL DEFAULT '{}';
ALTER TABLE veriflow.apify_jobs ADD COLUMN pilot_id text NOT NULL DEFAULT 'first-apify-test';
-- Conservative reservation for any preexisting job with unknown row allowance.
ALTER TABLE veriflow.apify_jobs ADD COLUMN reserved_records integer NOT NULL DEFAULT 1000
 CHECK (reserved_records BETWEEN 1 AND 1000);
CREATE INDEX apify_jobs_pilot_idx ON veriflow.apify_jobs(pilot_id);
CREATE TABLE veriflow.review_licenses (
 review_id uuid PRIMARY KEY REFERENCES veriflow.reviews(id) ON DELETE CASCADE,
 license_id text NOT NULL CHECK (license_id IN ('CC-BY-SA-4.0','CC-BY-4.0')),
 license_url text NOT NULL, source_terms_url text NOT NULL,
 public_credit text NOT NULL, attribution_url text NOT NULL,
 text_modified boolean NOT NULL, change_note text,
 CHECK (NOT text_modified OR coalesce(length(trim(change_note)),0)>0)
);
ALTER TABLE veriflow.review_licenses ENABLE ROW LEVEL SECURITY;
CREATE POLICY runtime_access ON veriflow.review_licenses TO veriflow_runtime USING (true) WITH CHECK (true);
REVOKE ALL ON veriflow.review_licenses FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON veriflow.review_licenses TO veriflow_runtime;
