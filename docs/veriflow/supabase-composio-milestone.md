# Earlier Supabase and Composio integration milestone

The subsequent collection strategy makes Apify/direct APIs primary and Composio optional. Current tables, tests and acceptance blockers are in [the Apify collection guide](apify-collection.md).

Verified 2026-11-14, on `feature/step-1-private-collection`, Draft PR #1. No merge, public website, new Supabase project, new Composio account, or unrelated project changes.

## Live Supabase results

Target: **Veriflow**, reference `qrejfpeclncrevmepgzx`, ACTIVE_HEALTHY, PostgreSQL 17.11, region us-west-2.

The authenticated Supabase management connection succeeded. The existing migration `20261114034217_private_collection.sql` was inspected and applied verbatim. Additional reviewed migrations install the dedicated application login, private integration configuration/status tables, and missing foreign-key indexes identified by the performance advisor. Management-tool migration timestamps were reconciled to the checked-in filenames so future CLI runs do not reapply the same SQL.

Installed private tables:

- `veriflow.sources`
- `veriflow.products`
- `veriflow.source_products`
- `veriflow.authorizations`
- `veriflow.import_batches`
- `veriflow.collection_runs`
- `veriflow.reviews`
- `veriflow.trends_research`
- `veriflow.integration_status`
- `veriflow.integration_bindings`

All **42** source IDs were seeded from `data/sources.json`; **zero** sources enabled. No production reviews, artificial customer testimonials, Trends results, source authorizations, or integration bindings were inserted.

Every table has RLS enabled. Live privilege checks show `anon` and `authenticated` cannot read any table or use the private schema. The application login inherits `veriflow_runtime` and can access the tables, but is not their owner, superuser, role creator, database creator, or RLS bypass role. No public Data API grants or exposed schema configuration were added. Supabase's security advisor returned no findings. Three missing foreign-key indexes were addressed; unused-index information is expected in a new database and does not justify removing the indexes. Advisor documentation: https://supabase.com/docs/guides/database/database-linter?lint=0005_unused_index

## Runtime connection and credentials

`veriflow_app` is the dedicated LOGIN; `veriflow_runtime` remains the NOLOGIN privilege group. A random password was generated locally, and only its SCRAM verifier was sent to PostgreSQL through the authenticated management connection. No password is present in migrations or Git history. An owner-only (0600) runtime configuration was created outside the repository, under a 0700 directory. Its values are not included in this report.

Load it using `VERIFLOW_ENV_FILE` through the deployment's secure process environment. The optional loader rejects group/world-readable files and supports only the documented server-side keys. When `SUPABASE_PROJECT_REF` is set, the database client requires the dedicated application login, the matching direct/project-scoped pooler identity, and `sslmode=verify-full`.

**The live dashboard-to-database connection remains blocked.** The direct project endpoint resolves to IPv6, which this execution environment cannot route. Regional pooler candidates closed connections before PostgreSQL authentication; they were not verified as this project's supported endpoint. An approved outer-executor check had the same result. No TLS validation was disabled, owner credentials substituted, or alternate data access channel added to the dashboard. The management connection also cannot impersonate `veriflow_app` with `SET ROLE`; its grants were not widened to bypass that restriction. Runtime privileges were verified through PostgreSQL privilege inspection, but the actual password login still needs validation. Obtain the exact session-pooler hostname/port from this project's Supabase Connect panel and verify access from the intended deployment network. Keep the original host for certificate verification.

The configured runtime URL currently references the direct endpoint. Move the owner-only credentials into the intended deployment secret manager; workspace-local files are not a production secret deployment. Once networking is available, run:

```sh
VERIFLOW_ENV_FILE=/secure/veriflow/runtime.env .venv/bin/python -m veriflow check-database
VERIFLOW_ENV_FILE=/secure/veriflow/runtime.env .venv/bin/python -m veriflow admin
```

The health command verifies the actual application login, TLS, expected tables, source count, RLS, and denied public privileges without printing connection strings or secrets.

## Live Composio results

There are no Composio tools, `COMPOSIO_API_KEY`, `COMPOSIO_USER_ID`, or configured environment secret bindings available in this execution environment. Therefore authentication, connected services, usable review actions, and Google Trends execution **cannot yet be determined**. No service is represented as connected based on catalog membership, and no real Composio-to-Supabase transfer occurred.

The private status table records `composio / pending_credentials / credentials_missing`. Configure the API key from the user's **existing Composio project** and the user ID owning the existing connections in the secure runtime environment. Do not create an account, auth config, connection, or integration as a workaround. Then run `discover-composio`; it only lists existing services and tools.

The existing `veriflow/composio.py` was extended with the supported Python SDK (`composio==0.32.0`, fully pinned dependencies). It uses the documented v3.1 API, user-scoped ACTIVE-account queries, bounded pagination, exact account IDs, pinned tool versions, reviewed input contracts, sanitized failures, and rate-limit handling. SDK tracking and implicit file transfers are disabled; SDK logs are discarded instead of propagating private request details. Discovery output to process logs contains only provider names, counts and status; it excludes account identifiers, private account details and tool responses. The dashboard shows candidate capability categories and `requires_contract_review` labels.

## Connector activation after discovery

A catalog result is not an executable connection. For each candidate action:

1. Verify an ACTIVE account for the configured user; inspect the actual tool contract and provider terms. Confirm read-only behavior, permissions and the requested use. Catalog wording alone does not approve an action.
2. Create a private `integration_bindings` row with the real provider, connected-account ID, exact tool/version, SHA-256 of `COMPOSIO_USER_ID`, reviewed input schema, output mapping, evidence, and explicit read-only approval. The adapter never creates these automatically. Do not commit binding values or private inventory to GitHub.
3. For Trends, add a source authorization scoped to the exact research query (`authorizations.product_keys`), set an appropriate expiry, and explicitly enable only `google-trends` after approval. Keep every review source disabled.
4. Map the provider's actual query/geography/time-range argument names and returned series path/date/value fields. The adapter retains only ISO dates and finite numeric interest values in [0,100], discarding all other provider output. Tools with another output format need a separately reviewed normalizer.
5. Execute the reviewed binding and verify a real saved result. Connection status becomes `ready` only after the approved action succeeds and its normalized result is stored. Discovery alone yields `discovered`.

`collect-trends` takes a private JSON request file containing `arguments`, `query`, `geography`, `time_range`, and a Google Trends `original_url`, plus explicit `--binding` and `--authorization` IDs. It validates research labels against the real provider arguments. A command skeleton is:

```sh
python -m veriflow collect-trends --binding BINDING_UUID --authorization APPROVAL_UUID --request-file /secure/trends-request.json
```

No example tool slug or provider account is presented as a real integration. Review/rating tools, product discovery, search/research and community tools are inventoried as candidates after authentication. Each requires separate contract review, field projection, source-specific permission and an appropriate connector/normalizer before activation. Existing approved CSV/JSON imports remain available.

## Validation

The full local suite passes **38 tests** against disposable PostgreSQL, including all migrations, the dedicated non-owner login, denied anonymous access, secure config/project guards, dashboard HTTP authentication and integration view, current SDK request contracts, missing/failed authentication, connected-account validation, read-only approval gates, authorization expiry, and a mocked Composio → normalized Trends → PostgreSQL transfer. The mocked transfer is deliberately not described as a live provider transfer.

Live checks separately verified the installed schema, permissions, role membership, migration history, source seed, and security advisors through Supabase management tools. Remaining checks are actual application-password login/TLS/dashboard connectivity, live Composio authentication/discovery, and an approved real action-to-Supabase transfer. Hosted CI was previously blocked by GitHub account billing; its current run status is reported in the PR.
