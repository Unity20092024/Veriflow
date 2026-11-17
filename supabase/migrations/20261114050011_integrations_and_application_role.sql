-- Dedicated application login. Password is provisioned separately and never
-- included in migrations, repository history or application logs.
CREATE ROLE veriflow_app LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT veriflow_runtime TO veriflow_app;

CREATE TABLE veriflow.integration_status (
 provider text PRIMARY KEY,
 status text NOT NULL CHECK (status IN ('pending_credentials','discovered','ready','error','unsupported')),
 capabilities jsonb NOT NULL DEFAULT '[]',
 last_discovered_at timestamptz, last_success_at timestamptz,
 error_code text, updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE veriflow.integration_bindings (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 source_id text NOT NULL REFERENCES veriflow.sources(id),
 provider text NOT NULL, tool_slug text NOT NULL, tool_version text NOT NULL,
 connected_account_id text NOT NULL, user_scope_hash text NOT NULL,
 read_only_approved boolean NOT NULL DEFAULT false,
 approval_evidence text NOT NULL CHECK (length(trim(approval_evidence)) > 0),
 input_schema jsonb NOT NULL, output_mapping jsonb NOT NULL,
 enabled boolean NOT NULL DEFAULT false,
 UNIQUE(source_id,connected_account_id,tool_slug,tool_version)
);
CREATE INDEX ON veriflow.integration_bindings(source_id);
ALTER TABLE veriflow.integration_status ENABLE ROW LEVEL SECURITY;
ALTER TABLE veriflow.integration_bindings ENABLE ROW LEVEL SECURITY;
CREATE POLICY runtime_access ON veriflow.integration_status TO veriflow_runtime USING (true) WITH CHECK (true);
CREATE POLICY runtime_access ON veriflow.integration_bindings TO veriflow_runtime USING (true) WITH CHECK (true);
REVOKE ALL ON veriflow.integration_status,veriflow.integration_bindings FROM PUBLIC,anon,authenticated;
REVOKE ALL ON SCHEMA veriflow FROM anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON veriflow.integration_status,veriflow.integration_bindings TO veriflow_runtime;
INSERT INTO veriflow.integration_status(provider,status,error_code)
VALUES ('composio','pending_credentials','credentials_missing');
