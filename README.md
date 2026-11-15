# Veriflow — private collection engine

Veriflow is a private software-review collection application: mobile administration, products/categories, source permissions, persistent background jobs, duplicate inspection, source coverage and private exports. Apify and authorized direct-source/import methods are primary; Composio remains optional and last.

**Free automatic collection verified in an isolated private database.** The lib.reviews connector discovered real software online and retrieved an existing Firefox review through START COLLECTION; a category rerun was deduplicated. The current suite passes 128 tests. This is not a live Supabase deployment claim. Paid collection remains disabled; no hosting or public affiliate website is included.

- [Real automatic collection and source-to-database evidence](docs/real-automatic-collection.md)
- [Pending migration safety review](docs/pending-migration-review.md)
- [Implemented features vs live capabilities](docs/application-status.md)
- [Portable Docker/Compose deployment](docs/portable-deployment.md)
- [Apify permission, price and spending gates](docs/apify-collection.md)
- [Source capability audit](docs/source-capability-audit.md)

The user-reported Apify balance is $10; it is informational, unverified and grants no spending authorization. Paid execution stays disabled and the existing $1/20-review first-test ceiling is unchanged. The proposed lib.reviews/Firefox pilot remains unactivated.

The existing Supabase database is preserved. This branch adds two **pending, unapplied** migrations for monitoring and private administration. Do not deploy the latest code against the old schema until the additive migrations are reviewed/applied; do not recreate or reseed production.

## Included

- 42 deduplicated registry entries: all 33 unique platforms in the supplied PDF, eight additional requested review sources, and Google Trends. The extracted PDF text and provenance are retained in `docs/pdf-platforms.txt` and `data/sources.json`. No earlier source list or repository history existed to recover additional previously identified sources.
- Each source has category, aliases, collection method, access status, disabled-by-default state, full-text policy, collection interval, and minimum interval. Capterra Reviews retains that explicit label.
- Source-specific authorization records include evidence, collection method, product scope, approver, expiry, revocation, and full-text permission. Both enqueue and execution check authorization. Metadata-only collection does not require text permission.
- Reviews retain software name, permitted text, original rating scale, publication date, platform, URL, collection timestamp, approval and run references. Reviewer identity fields are discarded before queue persistence; original import files remain under operator control.
- Explicit source-to-product mappings prevent guessing product identity. Native review IDs and normalized content suppress duplicates within a source; distinct reviews may share a listing URL. Cross-source content matches are candidate groups: both records and both attributions remain intact.
- A private `veriflow` database schema, explicit server role, RLS on every table, parameterized queries, sanitized errors, and no browser database credentials.
- Transactional source locks support concurrent workers; schedules, failure counts, bounded exponential delays and Retry-After handling expose operational status. The first collector processes one queued import batch per due source per run.
- Dashboard: product search, source-filtered reviews, source status, collection counts/errors, Apify jobs/usage/cost, source capability audit, and separate Google Trends research.
- Apify v2 submission and resumable dataset ingestion with reviewed builds/mappings, source permissions, per-run and deployment budget reservations, bounded exports, counts and cost monitoring. Direct API opportunities are audited; provider-specific direct adapters still require implementation and authorization.
- Composio v3.1 connected-service/tool discovery with user scoping, pagination, version and input-schema inventory, Google Trends capability search, redacted account output, rate-limit handling, and no guessed tool slugs or automatic execution.

## Local setup

Use Python 3.12+ and PostgreSQL 17. Production uses the existing dedicated Supabase project; never run setup against unrelated projects.

```sh
python -m venv .venv
.venv/bin/pip install -r requirements-core.txt
# Optional Composio SDK dependencies: pip install -r requirements.txt
# Load real credentials through your process manager, never commit them.
export DATABASE_URL='postgresql://SERVER_LOGIN:SECRET@HOST:5432/postgres?sslmode=verify-full'
```

For a fresh database, apply all files in `supabase/migrations/` in filename order with an owner/migration connection. The existing Veriflow project is already migrated; do not reapply them. The migrations create `veriflow_runtime` (NOLOGIN) and its dedicated `veriflow_app` LOGIN. Provision the application password through secure server configuration, outside migration history. Use the login's URL for `DATABASE_URL`; **do not run the application as the schema owner/postgres**. Supabase direct connections or the session pooler work with psycopg. Configure appropriate CA roots for `sslmode=verify-full`; never disable TLS on remote connections.

The schema is intentionally outside the Data API. Do not expose it or grant `anon`/`authenticated` access. Supabase service-role or secret API keys are not needed by the browser or this direct PostgreSQL implementation. Keep all secrets server-side.

```sh
# Seed only a fresh disposable/local installation; production is already seeded.
# .venv/bin/python -m veriflow seed
export ADMIN_USERNAME='operator'
export ADMIN_PASSWORD='a-long-random-secret-of-at-least-24-characters'
.venv/bin/python -m veriflow admin
```

Open `http://127.0.0.1:8080`. The server binds loopback and requires HTTP Basic authentication on every page. For remote use, place it behind an HTTPS reverse proxy and private VPN/access gateway. Do not forward an unencrypted public port. Credentials, review text and query strings are excluded from access logs; responses disable caching.

## Approve and run the first import

1. Obtain an authorized source export. Record approval evidence, scope, permitted fields, expiry, and whether full text is permitted. Refer to `docs/operations.md` for parameterized setup examples. Registry membership is not collection authorization.
2. Create the canonical product and an explicit `source_products` mapping using the source's stable product key and expected exported software name. Ambiguous products must be resolved by an operator before import.
3. Insert the source-specific authorization and enable only the reviewed source. Do not enable the whole registry.
4. Import JSON (array of objects) or CSV (header row). Each batch is limited to 1,000 records / 5 MB. Required fields: `external_id`, `product_key`, `software_name`, `published_at` (`YYYY-MM-DD`), `original_url` (HTTPS on source domain). Optional: `review_text`, `rating`, `rating_scale`. Ratings require their original scale. Do not include author names, email addresses, avatars, profile URLs, or other unnecessary identifying fields.

```sh
.venv/bin/python -m veriflow import --source capterra-reviews --authorization APPROVAL_UUID --file /secure/export.json
.venv/bin/python -m veriflow worker --once
# Or run continuously under the supplied systemd unit:
.venv/bin/python -m veriflow worker
```

Imported full text is rejected without both source and authorization permission. Unimplemented direct API/crawl adapters fail closed. The separately approved Apify pipeline is described in the collection guide; it does not require Composio. No scraping is implemented or implied. Review HTML is escaped in the dashboard. Completed and permanently failed queue payloads are cleared; source references and run history remain. Keep original exports only under an appropriate private retention policy.

## Composio and Google Trends

```sh
export COMPOSIO_API_KEY='server-side-project-key'
export COMPOSIO_USER_ID='your-veriflow-operator-user-id'
.venv/bin/python -m veriflow discover-composio
```

Discovery now persists sanitized provider/capability health for `/integrations`; database connectivity is required. Missing credentials are recorded explicitly. The CLI prints a summary without account IDs or provider payloads.

Discovery happens before selecting an integration: it inventories active connected accounts for that user, lists their available tools, and separately searches the tool catalog for Google Trends. A catalog match is not proof of a connected provider or collection authorization. Treat the output as private configuration: account IDs are retained; provider tokens/personal account details are not.

Current session discovery found no exposed Composio tools or environment credentials. Accordingly **live Google Trends execution is deferred**. The separate `trends_research` table/dashboard and a configurable SDK execution adapter are implemented. Select an actually connected, versioned tool, review its input/output contract and read-only behavior, and create an explicitly approved private binding before execution. Additional integrations follow the same process. See `docs/architecture.md`.

## Verification

Unit tests (database integration tests skip unless configured):

```sh
.venv/bin/python -m unittest discover -v
```

Full suite requires a **fresh disposable PostgreSQL instance**. It creates the schema and test roles, and deliberately refuses an existing installation. Never point `TEST_DATABASE_URL` at production.

```sh
docker run --name veriflow-test -e POSTGRES_PASSWORD=veriflow-local-test -p 127.0.0.1:55432:5432 -d postgres:17.6
export TEST_DATABASE_URL='postgresql://postgres:veriflow-local-test@127.0.0.1:55432/postgres'
.venv/bin/python -m unittest discover -v
docker rm -f veriflow-test
```

CI runs the full suite with an ephemeral PostgreSQL service. Tests cover the Capterra import roundtrip, privacy projection, duplicates, product identity, authorization changes, RLS and denied public access, concurrency locks, rate-limit rescheduling, dashboard rendering, and mocked Composio discovery. Live Supabase, actual provider exports and live Composio execution have not been validated.

## Delivery boundaries

This repository was empty and had no `main` ref at inspection. Work belongs on `feature/step-1-private-collection`. An empty review baseline may be used as the draft PR target so `main` remains untouched. The dedicated Veriflow Supabase project was installed in the subsequent database milestone; unrelated projects remain untouched. Runtime PostgreSQL networking, live Composio credentials, and authorized provider inputs remain prerequisites for real collection. See the integration milestone report for current verified status.

For Android without an interactive terminal, see [secure mobile Apify configuration](docs/apify-token-mobile.md). It uses the existing repository's encrypted Actions secret; it does not inject the key into the current Cloud machine, and runner verification remains subject to the existing GitHub billing lock.

For the existing Review Capture Hub Replit app, see [Android application-role password setup](docs/replit-role-password.md). The user retains the chosen password in a password manager; the one-time helper changes only `veriflow_app` and is never normal startup.

The [continuous runtime increment](docs/continuous-runtime.md) adds a known-run Apify monitor with durable retry scheduling and explicit dashboard host/PORT configuration. Its additive scheduling migration is tested locally and **not applied to live Supabase**.
