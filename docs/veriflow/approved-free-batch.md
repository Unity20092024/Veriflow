# Approved one-time free collection batch

The administrator authorized one lib.reviews-only software collection batch.
This is not a recurring schedule and never starts Apify or another paid service.

## Immutable scope

- At most 500 **new unique** reviews; duplicate records do not consume this limit.
- At most 100 source-identified software products, including software games.
- At most 1,500 HTTP attempts, including discovery, policy requests, redirects,
  retries, and review retrieval.
- At most 10 distinct listing pages per product.
- One serial requester, with at least three seconds between requests, or the
  source's longer crawl delay. Respect Retry-After cooldowns.
- Expire 48 hours after the original activation. Neither resume nor activation
  again changes the original expiry or counters.
- Stop on a changed policy, denied access, exhausted limits or exhausted tasks.
- Do not expand the source list or reinterpret ambiguous non-software subjects.

## Implementation and recovery

The normal `python -m veriflow worker` process advances the approved batch.
Use `python -m veriflow free-batch-status` to inspect it.
The explicit `free-batch-activate` command is idempotent and cannot renew it.
Do not delete checkpoints or grants to rearm a consumed batch.

Supabase retains the batch, discovered product mappings, pending listing and
review URLs, completed imports, request reservations and expiry. A PostgreSQL
session advisory lock serializes batch I/O across worker instances. Every HTTP
attempt is reserved and committed before it is sent. A crash after reservation
may conservatively consume an attempt without a response, never the reverse.
The worker revalidates source authorization before each task. One review import
is outstanding at a time; the next cannot be enqueued until the existing durable
ingestion pipeline commits its real unique/duplicate result. Reviews still use
the existing parser, attribution validation, fingerprints and Supabase storage.
The source's original Firefox pilot records and grant remain untouched.

Restart the normal worker against the same database to resume eligible pending
tasks. Do not restart the 48-hour timer. A source-policy block requires inspection,
not automatic retries. Unsupported non-product search links are excluded without
following them or hiding other valid matches. Historical task errors remain
visible after correction. HTTP 429 records the failed task and
retains the cooldown for subsequent tasks. Source outages are recorded, not
retried indefinitely.

Apply `20261115050000_bounded_free_batch.sql` once after existing local migrations.
It adds only batch checkpoint tables, RLS and explicit private runtime grants.
Do not blindly replay upstream administration migrations over this installation;
the upstream category DDL overlaps an earlier local migration.

## Rights and retention

Policy: https://lib.reviews/terms
Robots: https://lib.reviews/robots.txt
License: https://creativecommons.org/licenses/by-sa/4.0/

The source explicitly permits data mining/reuse subject to licensing, conduct
and reasonable resource usage. Preserve adjacent author credit, attribution
profile links, original review links, license links and modification notices.
ShareAlike applies to adaptations. No images or profile pages are collected.
No review retention deadline was found; the site's 90-day visitor-log statement
does not set a review retention deadline. No automatic deletion of existing
records is authorized by this batch. The batch's 48-hour deadline limits new
collection, not the CC BY-SA license term: attributed, licensed batch records
remain exportable afterward unless their grant is revoked or text permissions
are withdrawn. This does not relax expiry checks for unrelated sources.

G2/Capterra were excluded because separate automated-access permission was not
established. ODRS was excluded because sufficient review-reuse rights were not
verified. An accessible endpoint or open-source server code is not permission
to copy the hosted review data.

## Dashboard and exports

The existing authenticated private dashboard `/collection` shows discovered
products, unique insertions, duplicates, requests, failed requests, task errors,
source coverage, completion and original expiry, refreshed every 15 seconds.
`/reviews` retains CSV, JSON and Excel exports and adds JSONL. All formats retain
license and attribution metadata. Offline 500-row format fixtures are tests only,
never live data.

## Portability

The source archive contains the application, tests, migrations and dependency
manifests. It excludes credentials, private configuration, raw imported data,
review exports, uploaded documents, dependency folders and temporary maintenance
workspaces. A public CA certificate may be included under `certificates/`.

On another runtime, install `requirements-veriflow.txt`, configure the same
existing Supabase connection securely with `sslmode=verify-full` and the trusted
CA, preserve the existing secrets, and start the worker and private dashboard.
Do not provision a replacement database, rerun password resets, or replay already
applied migrations. The batch counters and expiry remain in Supabase.
