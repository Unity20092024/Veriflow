# Verified free Firefox collection in live Supabase

## Scope and upstream reuse

The administrator approved two requested Firefox runs, at most one review per
run, no recurring collection, and no paid execution. lib.reviews is an optional
43rd source; the original 42 catalog rows remain unchanged.

The native parser and HTTP client were taken unchanged from
[upstream revision a31ed34](https://github.com/Unity20092024/Veriflow/tree/a31ed34d638c793fe4d4c11ef0a419e32bb7ece5):

- `veriflow/libreviews.py`
- `veriflow/libreviews_live.py`

The upstream source activation/authorization logic was adapted in
`veriflow/free_collection.py` to the existing Replit `collection_jobs` and
`collection_job_items` queue, not the upstream administration queue.
The existing authenticated dashboard, exports, app connection and TLS
configuration were retained. No password reset or credential update occurred.

## Live result — 2026-11-15 UTC

Target: existing Supabase project `qrejfpeclncrevmepgzx`, private `veriflow` schema.
Both jobs were submitted through the authenticated dashboard's START COLLECTION
endpoint and executed by the separately running persistent collection worker.
No review upload or fixture populated this database.

| Check | Observed result |
| --- | --- |
| Product | Mozilla Firefox |
| Category | Web browsers |
| Native review | https://lib.reviews/review/48ea3813-0f63-4739-b659-0a361e9c99bf |
| Publication date | 2026-11-10 |
| Rating | 3 / 5 |
| Stored review text | 273 characters |
| First job | retrieved 1, inserted 1, duplicates 0, completed |
| Repeat job | retrieved 1, inserted 0, duplicates 1, completed |
| Persisted reviews after both jobs | 1 |
| Source count | 43; SHA-256 comparison confirmed all original 42 rows unchanged |
| Remaining queued/running collection jobs | 0 |
| Apify jobs | 0; paid execution disabled |
| Dashboard and CSV/Excel/JSON exports | authenticated 200, unauthenticated 401 |
| New category table protection | RLS enabled; anonymous/authenticated public reads denied |

Dashboard response checks verified the actual saved contribution, adjacent
public credit/profile link, native URL, category and modification notice.
CSV, JSON and XLSX responses were parsed and checked against the saved
attribution. Review wording and author identity are deliberately not copied
into this repository.

## Permission, attribution and retention

[Source terms](https://lib.reviews/terms) expressly permit mining/reuse subject to
the license, conduct conditions and non-excessive resource usage.
[robots.txt](https://lib.reviews/robots.txt) excludes `/api/`; this collector
fetches permitted public HTML only.

Review text is CC BY-SA 4.0. Store/display/export minimal public author credit,
profile link, native URL, license, terms URL and an HTML-to-plaintext/title-label
change notice with the contribution. The dashboard and exports retain these.
No images, avatars, profile pages or private identities are fetched. Future
redistribution must respect attribution, applicable ShareAlike requirements
and third-party content rights.

No review-retention deadline was found in the reviewed terms. The 90-day
period refers to lib.reviews' own visitor logs, not copies of licensed reviews.
The local collection authorization expires after seven days and is not
automatically renewed; this is an access limit, not a claim that a CC license
expires after seven days. No automatic deletion policy was introduced.

## Operational limits

Each lib.reviews item uses the native client with `max_reviews=1,max_pages=1`,
rechecks terms/robots, and stops with no follow-up cursor. The source-specific
admission check serializes requests and refuses jobs after the two approved
items exist. It never adds recurring jobs. Source/network failures do not
silently resubmit this pilot; a 429 persists the cooldown and fails the item.
Lost worker leases can recover the same durable request; ingestion is
transactional and database uniqueness prevents duplicate review rows.

Both permitted test jobs are now consumed. Additional live collection requires
new administrator approval and a reviewed scope-limit change. Do not rerun
activation or broaden the product authorization to bypass this limit.

## Migration portability

`20261115040000_free_source_categories.sql` applies only the category tables
and their private policies from upstream's larger
`20261115003835_private_administration_jobs.sql`. It does not add a duplicate
administration queue, modify existing tables, or change existing table policies.
The unrelated Apify polling migration was not needed and was not applied.

Before merging the full upstream branch, reconcile the overlapping category
DDL rather than replaying the full administration migration. Preserve the
existing Replit queue, source limits, connection configuration and exports.
