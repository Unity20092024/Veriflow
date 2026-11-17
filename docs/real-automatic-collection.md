# Real free automatic collection — 2026-11-15

**A real lib.reviews → persistent worker → restricted private PostgreSQL ingestion succeeded.** This was performed in an isolated local PostgreSQL 17 environment in Codex, not the production Supabase project. The source HTTP calls were real; no review upload, mocked response, generated review or paid Actor was used for this acceptance run.

## Result

The authenticated phone-width browser enabled the reviewed free source and submitted an online Firefox search. The separate application worker discovered **Mozilla Firefox** and **Wikibase for Web** from lib.reviews' actual software-subject metadata, creating source mappings and deterministic categories. It labels an unstated vendor as “Not stated by source” rather than inventing one.

Selecting Mozilla Firefox and pressing **START COLLECTION** retrieved and stored one existing review. Selecting the **Web browsers** category and pressing START again retrieved that same review, inserted zero new rows and counted one duplicate. Database role was `veriflow_app`, without owner/superuser/BYPASSRLS privileges. The real record remains in the private local database, with an owner-only backup outside Git.

| Saved evidence | Observed value |
|---|---|
| Product | Mozilla Firefox |
| Native review URL | https://lib.reviews/review/48ea3813-0f63-4739-b659-0a361e9c99bf |
| Source publication date | 2026-11-10 |
| Rating | 3 / 5 |
| Stored review text | 273 characters including labeled native title and plaintext conversion |
| Required license | CC BY-SA 4.0 |
| Required public credit/profile link | Preserved in private review_licenses and displayed beside the contribution |
| First run | Retrieved 1, inserted 1, duplicates 0 |
| Category rerun | Retrieved 1, inserted 0, duplicates 1 |
| Total persisted native review rows | 1 |
| Apify starts / financial spend | None |

The [sanitized receipt](evidence/libreviews-live-20261115.json) records timestamps/counts/source metadata. Full review text, public author identity, credentials and database backups are not committed to Git. Phone screenshots/private evidence are under `/workspace/veriflow-real-proof/`. Their banner explicitly identifies isolated local validation. The database transport was development loopback; this is not a claim of successful live Supabase application/TLS connectivity.

## Why retrieval and storage are eligible

[Source terms](https://lib.reviews/terms) explicitly welcome data download/mining/reuse, subject to resource/conduct rules and license compliance. Review/post text is [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); credit by public username beside the contribution is required, with a source-profile link recommended. The source's own permission establishes the access/reuse path, not an Actor listing or software code license.

The connector preserves review wording in plaintext, native ID/URL, publication date, rating/scale, product association, collection time, license links, source terms and minimal required public credit. It records HTML-to-plaintext/title-label changes. It excludes images, emails, avatars, private identities and unrelated profile data. Any future redistribution must respect applicable attribution/ShareAlike and third-party-content conditions; no public publication is enabled here.

[robots.txt](https://lib.reviews/robots.txt) disallows `/api/`. This connector excludes that path entirely. It uses permitted public search, product pages, native review permalinks and product pagination. The upstream [product route](https://github.com/permacommons/lib.reviews/blob/main/routes/things.ts) and [pagination template](https://github.com/permacommons/lib.reviews/blob/main/views/partials/feed.hbs) confirm the product-specific `/before/<timestamp>` contract.

## Operator workflow — no uploaded review file

1. Open START COLLECTION and review the source terms. The explicit **Enable free lib.reviews connector** action registers/enables only this reviewed source and its license policy. It does not enable any of the original 42 sources, another crawler or a paid Actor.
2. Enter a software keyword (for example Firefox), then **Discover software**. The persistent job fetches online subject metadata. It accepts only descriptions with explicit software classifications and does not convert review excerpts, arbitrary search hits or other review subjects into software products. Existing source mappings are never silently reassigned.
3. Choose a discovered product **or** category, set the record limit and press **START COLLECTION**. The worker retrieves reviews directly and sends them through the shared normalization, product-scope, authorization, licensing and deduplication pipeline.
4. Inspect the job's retrieved/inserted/duplicate/page counts and then the review's text, attribution and original URL. Import-based workflows remain available separately.

Original registry `data/sources.json` remains 42 unchanged entries. `data/free-sources.json` is an audited optional source extension. Explicit activation adds lib.reviews as a 43rd runtime registry entry; readiness verifies the original IDs are still present rather than assuming extras are invalid. No production registration/activation was performed.

The source-specific public-license grant is scoped to an exact discovered product URL, records the verified terms hash and expires in seven days. Every network job rechecks terms and robots; an explicitly revoked or narrower product grant is never automatically overridden. Other sources still require their own source-specific rights and implementations.

## Bounds and failure handling

- Free collection: at most 20 reviews, five product pages per product, five mapped products per category request and 50 total HTTP requests per job. This is a careful first connector, not a claim of representative or high-volume market coverage.
- HTTPS only, fixed source host, validated public paths, same-origin redirects only, bounded 1 MB responses, English source rendering and 20-second request timeout. No login, API token or proxy rotation. No arbitrary URL fetch / general crawler / SSRF endpoint.
- Serial requests wait at least two seconds and honor source crawl delay. Robots refusals, policy changes, product-name mismatches, cross-product pagination and missing attribution fail closed. No assets or profile pages are fetched.
- Pagination follows only that product's published older-review link, detects cycles, deduplicates repeated review permalinks across pages and stops at the configured cap. Two-page behavior is covered by fixtures; the actual Firefox acceptance record occupied one page. Cap/truncation fields do not promise that additional real reviews exist.
- HTTP 429 stops the job, records Retry-After and persists the cooldown in source state. New requests cannot bypass it after restart. No hidden automatic repeated HTTP retry occurs. Source/network failures appear as sanitized job errors; the operator may retry after the cooldown, with database deduplication protecting saved records.
- Composio and Apify are not imported by this source client. Paid execution remains disabled and the $1/20 paid first-test policy remains unchanged, regardless of the reported $10 balance.

## Verification and remaining deployment work

The full suite passed **128 tests**, including real connector contracts, pagination, software discovery filtering, source/robot/license safeguards, persisted cooldown, worker/category ingestion, deduplication, prior dashboard/export features and pending-migration upgrade/rollback checks. The genuine browser/source/database run above is separate evidence from those fixture tests.

The two pending Supabase migrations were reviewed and exercised against an existing-schema local upgrade. Live read-only checks found zero product-name conflicts, zero products/reviews/provider jobs, 42 disabled sources, RLS enabled and no security-advisor findings. They are still **not applied**. See [migration review](pending-migration-review.md).

Free automatic collection is verified in the isolated environment. Production Supabase deployment is not declared operational: it still requires reviewed pending migrations and a functioning application connection on the intended runtime. No hosting was purchased, no main/Supabase password changed, no unrelated project modified and Draft PR #1 stays unmerged.
