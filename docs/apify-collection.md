# Primary collection: Apify and authorized direct APIs

Current first-test ceiling: **$1 total / 20 review records**, not automatic permission to spend. Paid execution remains disabled in both the versioned policy and runtime configuration. The engine now reserves records and total cost across the pilot lifetime, requires a complete pricing review, and preserves approved license/credit metadata. See [current-workspace token instructions](apify-token-current-workspace.md).

Apify and authorized source APIs are the primary integration paths. Composio discovery, Google Trends and SerpApi support are preserved as optional integrations. Missing Composio credentials never block Apify, approved imports, the worker, or the private review dashboard.

The [42-source capability audit](source-capability-audit.md) and [machine-readable audit](../data/source-capabilities.json) record candidate Actor IDs/builds, advertised fields, exact observed pricing, estimated event costs, native API opportunities, and limitations. Thirty-four Actor candidates were identified, but none was enabled or represented as licensed. Eight sources have verified documented API paths with scope/access restrictions. The generic review pipeline does not reinterpret discovery metadata, community posts, aggregates, AI-generated summaries or Trends series as customer reviews.

## Current live status

Only Supabase project **qrejfpeclncrevmepgzx** was changed. The original migrations and the Apify job migration are installed. The database has twelve private tables, 42 disabled sources, and no collection authorizations or paid Actor jobs. Live checks confirm RLS throughout, denied anon/authenticated access, and expected `veriflow_app` privileges. The security advisor returned no findings. Performance advisors report only informational unused indexes in the new database ([guidance](https://supabase.com/docs/guides/database/database-linter?lint=0005_unused_index)).

The database management connection works. The application connection through the workspace's existing owner-only runtime file still fails: its direct endpoint is IPv6-only and was unreachable in the earlier checks; project-specific pooler routing remains unresolved. No owner database URL is used as a substitute for normal jobs. Application-password/TLS/dashboard connectivity to live Supabase remains unverified.

No APIFY_TOKEN binding is exposed in this execution environment or its server configuration. No permission for a particular product's review collection/storage, no Actor binding, and no nonzero paid-run budget were provided. Therefore the real-review acceptance criterion remains **blocked**, not completed. No paid run or actual review was fabricated. Tests use marked fixtures against disposable PostgreSQL, not production.

## Server configuration

Attach existing credentials through the environment's secret binding or an owner-readable server file outside Git. Supported server-only settings:

| Setting | Default | Purpose |
|---|---:|---|
| `APIFY_TOKEN` | absent | Authenticate the existing Apify account |
| `APIFY_MAX_RUN_USD` | 0 | Maximum approved charge allowance per paid run |
| `APIFY_ROLLING_24H_BUDGET_USD` | 0 | Deployment-wide rolling 24-hour spending/reservation allowance |
| `APIFY_MAX_RECORDS` | 100 | Local maximum rows per binding/run; absolute implementation limit 1,000 |

Both dollar limits must be explicitly set above zero before a paid start. A new binding is disabled by default. Its `pricing_review` must record complete pricing confirmation, verified total-cost control, evidence and a full `max_incremental_cost_usd` allowance including export/storage. This is additional to the live event-price snapshot; it is not inferred from Actor availability. The token is sent only in the Authorization header to `api.apify.com`; it is never put in a URL, Actor input, logs, browser code or repository. Redirects are rejected. Use a token with the required Actor/run/dataset permissions; runs request limited Actor permissions and disable automatic restart. Run memory is explicitly 512 MB and timeout is bounded by the reviewed binding (30–3,600 seconds).

```sh
VERIFLOW_ENV_FILE=/secure/veriflow/runtime.env python -m veriflow apify-check
VERIFLOW_ENV_FILE=/secure/veriflow/runtime.env python -m veriflow check-database
```

`apify-check` confirms authentication without printing account details. It requires no Composio ID or credentials. `check-database` requires the dedicated application login and verified TLS. Do not commit private environment files, raw exports, Actor inputs containing private data or source-approval documents.

## Configure one authorized source

An operator must first confirm source access and export/storage rights for a specific product, including whether original full text may be retained. Capterra Reviews remains explicitly labeled and has no inferred permission. Actor availability, public accessibility or a paid Apify subscription alone are not evidence of source rights.

Use the existing product and `source_products` mapping workflow in [operations](operations.md). Create a source-specific `authorizations` record with `method='apify'`, evidence, approver, allowed product key, expiry and explicit full-text permission. Enable only that reviewed source and set its `collection_method='apify'`.

Create an `apify_bindings` row using inspected provider contracts, with:

- That source/product key, one exact source product URL, operator/evidence and explicit enabled state.
- A real Actor ID, immutable observed build ID and numeric build version. Never use `latest` for execution.
- Its complete reviewed input schema and approved input object. The source product URL must be present at `target_input_path`; `limit_input_key` must equal the binding's `max_records`. Review all input options for source scope: do not select additional platforms, unapproved URLs, automatic cross-platform discovery or unbounded crawl targets.
- A field mapping from native output paths to `external_id`, `software_name`, `published_at`, `original_url`, optional permitted `review_text`, `rating` and `rating_scale`. Paths are lists of object keys. Original text can combine explicitly mapped `text_parts` (e.g. title/pros/cons) with section labels; no text is generated. The software name must match the existing source-product mapping.
- If applicable, a `source_path` and exact `source_value` to reject mixed-platform output. Declared actor product identity and original review/listing URL must be verified, not guessed. Nested arrays or non-ISO dates require a separate reviewed normalizer; unsupported outputs are rejected.
- `pricing_snapshot` produced by `veriflow.apify_pipeline.pricing_snapshot()` from the current official Actor metadata, positive `max_charge_usd`, a row cap and a bounded timeout.

The Actor build/schema and pricing are checked again before each paid POST. Price changes, configuration edits during a run, mismatched products/source labels, revoked/expired approvals and missing text permission block ingestion. Reviewer names, accounts, email addresses, avatars and profiles are excluded from selected fields and persistence. The pipeline validates the entire projected batch before writing reviews.

## Paid-run spending semantics

The first implementation permits **pay-per-event** pricing only, with unchanged reviewed event prices and no separately billed platform usage. Other pricing models, including free Actors that still accrue platform usage, are listed in the audit but fail closed for paid starts until their cost controls are reviewed and implemented. `maxTotalChargeUsd` is the platform PPE event-charge limit; it is not a universal cost limit for every Actor pricing model. `maxItems` has different semantics for pay-per-result Actors and is not treated as a total-price guarantee. See [Apify's documented run options](https://docs.apify.com/api/client/js/reference/interface/TaskCallOptions).

Before starting an Actor, the service acquires a deployment-wide PostgreSQL advisory lock, checks the global budget, persists a reservation and commits it. This protects against parallel callers and process failure during an external paid POST. The approved binding's complete Actor event-charge allowance is reserved; a new start is blocked while that binding has an unresolved or pending job.

Timeouts, 5xx responses or ambiguous starts are recorded as `start_unknown` and **never automatically retried**. A process crash may leave `starting`; that also remains reserved and blocks another start. Inspect the existing run in Apify Console and reconcile its identity/billing before any new start. Do not clear the reservation to work around an uncertain response. This milestone does not automatically adopt arbitrary existing runs or import unrelated datasets.

Provider `usageTotalUsd` is displayed as **reported usage**, separately from **invoice-confirmed billed cost**. It is not assumed to include every charge. Until invoice cost is confirmed by an operator, the full reservation continues counting against the budget, even after 24 hours if unresolved. Reviewed `confirmed_billed_usd` values can be recorded through a private operator workflow after checking the invoice; never set them to zero simply to free capacity. The dashboard deliberately distinguishes these amounts.

Post-run dataset reads and retained storage can incur separate platform charges even when the Actor's event price includes its execution usage. The local request/row/byte limits bound retrieval volume, but the event-run and reservation settings do **not** guarantee an upper bound on the complete Apify invoice or future retained-storage charges. Before production scheduling, review the account's platform charges and configure storage retention and any available account-level spending controls. Raw Actor datasets remain in Apify under its retention settings; this milestone neither makes them public nor deletes provider datasets automatically. [Apify pricing-model and post-run storage guidance](https://docs.apify.com/actors/running/actors-in-store).

## Run and resume

```sh
python -m veriflow apify-start --binding BINDING_UUID --authorization APPROVAL_UUID
# A start returns a durable internal job UUID; it does not wait for the Actor.
python -m veriflow apify-refresh --job JOB_UUID
# Repeat only reads of this known run until it reaches a terminal state.
python -m veriflow worker --once
```

`apify-refresh` polls only the known Actor run. It checks Actor/build provenance, permissions and a fingerprint of the reviewed binding. Successful datasets are downloaded with bounded pagination and an explicit field projection using the supported JSON export endpoint; the client also exposes bounded CSV export. No public dataset sharing URLs are created. Invalid batches remain unimported, and no raw Actor payload is stored in Veriflow.

A successful dataset produces a private import batch that the existing scheduled worker validates again and ingests. Jobs retain source, grant, Actor/build, run/dataset identifiers, row counts, duplicates, sanitized failures, reservations and usage. Reviews retain their original source URLs, native IDs, dates, original rating scale, permitted text, software/product association and collection time through the run log. Duplicate native review IDs and normalized content are suppressed; distinct metadata reviews may share a source listing URL. Repeating refresh or ingesting repeated completed exports does not duplicate reviews.

Actor failures and transient export failures are visible without automatically starting another Actor. HTTP 429 is sanitized as `rate_limited`; respect the provider's Retry-After before refreshing again. Refresh returns `retry_after_seconds` so callers can honor the delay; there is no internal immediate retry loop. When refresh detects revoked permissions on an active known run, it requests abort and avoids downloading its dataset. Keep a poller running if you need prompt revocation handling; the submitted remote run does not depend on the local process remaining alive.

No new paid-run schedule is enabled by this milestone. The existing worker schedule consumes approved queued imports. Scheduling Actor submissions or a polling loop requires explicit source approval, configured budgets and an execution environment with verified PostgreSQL connectivity; a poller must honor rate limits and resume existing jobs rather than restart them.

## Dashboard and verification

Private admin pages:

- `/collection`: per-source review counts, failed/uncertain jobs, retrieved/inserted/duplicate counts, run and dataset references, reserved budget, reported usage and invoice-confirmed cost.
- `/capabilities`: all 42 sources' Actor/API candidate and cost-audit status.
- Existing `/reviews`, `/sources`, `/errors`, `/integrations` and separate `/trends` remain available.

The initial Apify suite passed **62 tests** against disposable PostgreSQL. It covers all migrations, privacy/RLS, HTTP authentication, provider contracts and secret placement, bounded exports, budgets, uncertain starts, repeated-run deduplication, source/product/text permission checks, build/config/pricing changes, revocation abort, failed jobs, retryable exports and optional Composio behavior. A mocked Actor-to-Veriflow-to-PostgreSQL transfer is proven. No live Apify-to-Supabase transfer is claimed.
