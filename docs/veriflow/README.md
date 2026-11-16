# Veriflow — private automated review collection

Veriflow automatically collects existing software reviews from individually
approved sources through a persistent Python worker and the existing Supabase
project. It is a private, single-administrator tool, not a manual review-entry
app or a public content website.

Breadth First is the default collection strategy. The live database currently
contains **11 authentic reviews across 11 distinct products**; the approved
lib.reviews batch is complete and no collection job is active. Product coverage
and category metrics are read from Supabase.

The native Mangrove API connector is integrated with persistent pagination,
license validation, attribution and deduplication. Mangrove is currently
disabled and pending authorization, with no product mappings, grants or jobs.
Its source must not collect until an exact scope is separately approved.
Collection uses only free services; paid Apify execution remains disabled.
Composio is optional and is not required by the core test suite.

See [Breadth First product coverage](product-coverage-strategy.md),
[Mangrove worker integration](docs/veriflow/mangrove-worker.md), and the
[portable source restore guide](docs/veriflow/source-backup-restore.md).

## Included

- 42 deduplicated baseline registry entries: all 33 unique platforms in the supplied PDF, eight additional requested review sources, and Google Trends. The extracted source catalog is included in `data/sources.json`. Runtime may contain additional provider rows.
- Each source has category, aliases, collection method, access status, disabled-by-default state, full-text policy, collection interval, and minimum interval. Capterra Reviews retains that explicit label.
- Source-specific authorization records include evidence, collection method, product scope, approver, expiry, revocation, and full-text permission. Both enqueue and execution check authorization. Metadata-only collection does not require text permission.
- Reviews retain software name, permitted text, original rating scale, publication date, platform, URL, collection timestamp, approval and run references. Reviewer identity fields are discarded before queue persistence; original import files remain under operator control.
- Explicit source-to-product mappings prevent guessing product identity. Native review IDs and normalized content suppress duplicates within a source; distinct reviews may share a listing URL. Cross-source content matches are candidate groups: both records and both attributions remain intact.
- A private `veriflow` database schema, explicit server role, RLS on every table, parameterized queries, sanitized errors, and no browser database credentials.
- Persistent collection jobs save pagination cursors, item progress, review counts, duplicate counts, and failures. Source access and product mappings are revalidated before each page and ingestion.
- Dashboard: product search, source-filtered reviews, source status, collection counts/errors, Apify jobs/usage/cost, source capability audit, and separate Google Trends research.
- The Apify pipeline is present for future reviewed use, but paid execution remains disabled. Direct API adapters still require source-specific permission, explicit mappings, and active grants.
- Composio v3.1 connected-service/tool discovery with user scoping, pagination, version and input-schema inventory, Google Trends capability search, redacted account output, rate-limit handling, and no guessed tool slugs or automatic execution.

## Local setup

Use Python 3.12+ and the existing Veriflow Supabase project. Do not create a
replacement database or reset working credentials. Keep secrets in the
runtime's secure Secrets facility.

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
# Configure the existing database and administrator credentials through Secrets.
# Keep sslmode=verify-full and the existing trusted CA certificate.
```

The existing project is already migrated; do not replay applied migrations. Use
the dedicated `veriflow_app` connection and the trusted CA certificate with
`sslmode=verify-full`. Do not run the application as the schema owner or change
the existing password. See the restore guide for Android-friendly steps.

The schema is intentionally outside the Data API. Do not expose it or grant `anon`/`authenticated` access. Supabase service-role or secret API keys are not needed by the browser or this direct PostgreSQL implementation. Keep all secrets server-side.

```sh
.venv/bin/python -m veriflow admin
.venv/bin/python -m veriflow worker
```

The private dashboard requires HTTP Basic authentication on every page.
Credentials and review text are excluded from access logs; responses disable
caching. Do not expose it publicly without an authenticated HTTPS boundary.

## Start permitted collection

Use the authenticated dashboard's Collection controls to choose an eligible
category, product, or source set. A job requires a permitted source, an active
source-specific authorization, and an explicit source-product mapping. Breadth
First is the default; its per-product target guides priority and is not a storage
cap. CSV/JSON import is supplementary, not the primary collection method.
Export only records the source license and attribution allow.

## Composio and Google Trends

```sh
export COMPOSIO_API_KEY='server-side-project-key'
export COMPOSIO_USER_ID='your-veriflow-operator-user-id'
.venv/bin/python -m veriflow discover-composio
```

Discovery now persists sanitized provider/capability health for `/integrations`; database connectivity is required. Missing credentials are recorded explicitly. The CLI prints a summary without account IDs or provider payloads.

Discovery happens before selecting an integration: it inventories active connected accounts for that user, lists their available tools, and separately searches the tool catalog for Google Trends. A catalog match is not proof of a connected provider or collection authorization. Treat the output as private configuration: account IDs are retained; provider tokens/personal account details are not.

Composio and Google Trends are optional research features and are not needed for
review collection or the core test suite. Do not install the optional SDK unless
a specific approved feature requires it. A catalog match does not establish
provider permission or authorization.

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

The current Python suite runs without installing optional Composio
(`python -m unittest discover -s tests -q`). It covers the worker, provider
parsers, authorization checks, deduplication, exports, product coverage and
dashboard. The private dashboard has been verified against the normal Supabase
connection; the signed-in interface cannot be captured by an unauthenticated
preview browser.

## Delivery boundaries

The downloadable source archive excludes secrets, private keys, runtime review
exports, generated datasets, dependencies and caches. It includes deployment
instructions that reuse the existing Supabase account and Secrets.
