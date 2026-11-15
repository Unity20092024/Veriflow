# Private application build — 2026-11-15

Development continues independently in Codex on `feature/step-1-private-collection`, Draft PR #1. No hosting purchase, live password change, Supabase migration application or paid collection occurred in this increment.

## Implemented and exercised locally

| Requirement | Application behavior | Evidence / practical limit |
|---|---|---|
| High-volume authorized reviews | Streaming CSV/JSONL bulk import into durable 1,000-record / bounded-byte batches; existing worker continuously ingests approved sources | 1,000 synthetic records inserted, repeated import produced zero additional reviews and 1,000 duplicates; 1,001-row file created two durable batches. Not a live scrape or throughput benchmark. |
| Automatic discovery/categories | Background approved-catalog discovery creates canonical products, source mappings and categories; conflicting mappings fail closed | Catalog fixture processed without generating reviews. Live provider search/discovery adapters still need source-specific implementation and permission. |
| Manual products/search | Add software, vendor, HTTPS website and categories; case-insensitive product identity, name/vendor search and category filter | Browser-tested product addition; database-tested persistence and identity/category matching. |
| START COLLECTION | Prominent control queues an idempotent persistent request for approved imports | Browser-tested through background ingestion. Paid Apify requests produce a visible blocked job. No automatic paid submission. |
| Persistent jobs | Durable queued/running/terminal state, attempt counts, crash recovery and cancellation of queued requests; separate worker process | Tests cover request idempotency and recovery. Direct PostgreSQL or **session** pooling is required; session advisory locks are intentionally used. |
| Bulk sources/settings | Multi-source pause/resume/schedule, saved selection/preferences, explicit permission record/revoke, source-product association | Resume refuses unapproved sources. Recording permission keeps a source paused. Actor availability never supplies rights. |
| Duplicate/review inspection | Existing native-ID/content deduplication plus detail pages, provenance, source URLs, mandatory attribution and potential cross-source duplicate links | Synthetic duplicate rerun and HTML escaping tested; no automatic cross-source deletion. |
| Source coverage | All registry sources with review/product counts, approval/health indicators, last run/failures; product coverage summary | Database-backed views. Zero coverage remains visible; no fictional collection counts. |
| CSV / Excel / JSON / JSONL / ZIP | Background export generation, bounded server-side cursor, filtered datasets, private expiring downloads | All five formats tested; Excel independently opened with openpyxl and downloaded through authenticated browser. ZIP contains JSONL, manifest and licensing instructions. |
| Mobile private admin | Responsive product cards, touch-size forms, native file picker, horizontal scrolling confined to wide data tables, required authentication and CSRF protection | Browser workflow at 390 px plus desktop screenshots; no page-level horizontal overflow on checked product/coverage screens. |

## What is not live-tested

No real source collection has run through Apify. No source was activated in the production registry. The proposed lib.reviews/Firefox source still needs a reviewed real output contract and supported, enforceable usage-cost policy. Current paid-start guard remains PPE-only; Cheerio is pay per usage and stays blocked. Direct APIs and online product discovery need specific approved adapters; catalog import discovery is implemented, not an unrestricted web crawler.

The existing Supabase production application connection was not retried from Codex. Earlier management verification is separate from this local validation. Latest code requires the pending migrations below before deploying against that database.

The user reports **$10 available Apify balance**. It is recorded as unverified informational data only. It does not raise the existing **$1 / 20-review first-test ceiling**, authorize spending, or enable paid starts. Composio is optional and last, with discovery retained and its SDK omitted from the default container.

## Operator workflow

1. Add/search software and categories. Source-product keys must explicitly map to the correct product; conflicting mappings are rejected.
2. In Sources & settings → Configure source permissions, record actual evidence, method, product scope, expiry and full-text storage permission where applicable. Mandatory license/terms rules still apply. This records an operator approval; the software cannot establish that an external permission exists. Saving leaves the source paused.
3. Resume only reviewed sources through the bulk settings screen. Revoking a grant pauses its source. Full-text export is omitted when current source/grant permission is unavailable at export generation.
4. Upload a permitted JSON/JSONL/CSV review export through the native file picker (5 MB HTTP request / 1,000 records per web batch), or queue a scoped JSON product catalog. Nothing is generated as a customer review.
5. START COLLECTION processes an already queued approved import through the background application worker. The normal ingestion worker can also consume eligible source queues on schedule. Cancelling an administration request does not remove already queued import batches or abort a provider run; pause the source to stop pending ingestion.
6. Inspect persistent jobs, reviews and coverage; create filtered private exports. Never interpret a blocked request as successful collection.

For a larger approved local export, the portable CLI streams rather than loading the entire file:

```sh
python -m veriflow bulk-import --source SOURCE_ID --authorization GRANT_UUID --file approved-export.jsonl --max-records 100000
```

CSV and JSONL are supported for streaming, default file ceiling 100,000 and explicit maximum 1,000,000 records. Each batch revalidates permission and commits independently. A later invalid row/record ceiling can reject the remaining file after earlier batches were queued; rerunning preserves review deduplication. This is not atomic across an entire large file, and unprocessed records must not be reported as imported. Bulk import is restricted to approved-import sources and cannot bypass the Apify job budget. When further captured batches are pending, ingestion drains the backlog at the configured minimum interval instead of waiting the full discovery schedule. START after an already processed queue reports no_pending_imports, not a fabricated review count.

Exports are capped at 100,000 rows per request, fetched in 500-row chunks. Spreadsheet cells are protected against formula execution; JSON/JSONL preserve original text. Excel's 32,767-character cell limit is enforced by rejecting oversized cells with no silent truncation; use JSONL for such records. Artifacts have owner-only permissions and seven-day retention; expired downloads are refused immediately and the worker removes expired files. Persistent export storage must be shared between the dashboard and application worker.

## Verification

**117 tests passed** against a fresh disposable PostgreSQL 17 instance, plus dependency/diff checks. The actual Chromium phone workflow used only marked fixtures and the restricted application role: product creation → permission/mapping → native file upload → START → separate background worker ingestion → review inspection → private XLSX download. Anonymous access was denied. The Excel file was opened with a separate reader.

Local artifacts are outside Git at `/workspace/veriflow-preview/`: mobile-products.png, mobile-coverage.png, desktop-products.png and a marked fixture export. These screenshots are development evidence, not production data or proof of source permission.

Docker image build and Compose configuration validation passed. The default image ran as UID 10001, verified private artifact permissions and passed pip dependency checks; paid execution remained false. These checks did not connect the container to live Supabase.

## Additive migration review

Existing migrations were preserved. New pending migration `20261115003835_private_administration_jobs.sql` adds categories, product-category links, a product website/normalized identity index, private settings and durable administration jobs. All new tables have RLS and explicit runtime grants, with public/anon/authenticated access revoked. No data/API schema is exposed.

Both this migration and the previous `20261114230002_apify_poll_schedule.sql` remain **unapplied to live Supabase**. Review and apply only pending migrations through the authorized migration process before deploying this revision. Do not recreate the database, replay old migrations or seed production at startup. Fresh local validation contains 17 private tables; the last live report remains 13 installed tables.

The normalized product identity index deliberately fails if existing case/whitespace variants conflict. Preflight existing products before applying it and reconcile conflicts explicitly; the migration never silently merges or deletes products. Readiness checks reject missing expected tables/monitor columns.
