# Selective integration into the existing Replit application

Checked 2026-11-15 against **qrejfpeclncrevmepgzx only**. This branch starts at the exact fetched Codex commit `ff62e181766253a1e98fdd2d3885b3709b8d4a84` in an isolated checkout. It does not modify Codex's feature branch, Draft PR #1, the live schema, credentials, sources or records. No new collection has run during this integration review.

## Verified live state

The initial direct read-only management check at 14:07 UTC found **43 sources, one enabled source, one product and one review**. The saved review is for Mozilla Firefox, with the existing lib.reviews mapping `https://lib.reviews/mozilla-firefox`. It retains CC-BY-SA-4.0 license metadata and required credit. There were two completed collection jobs and two completed collection job items. Do not treat the earlier zero-review snapshot as current.

The initial **17** private tables had RLS enabled and denied SELECT to `anon` and `authenticated`. Neither application/runtime role is a superuser or bypasses RLS. Security advisor returned no findings. No passwords were reset and no owner-based collector insertion was used. Management reads corroborate the saved record; the user's successful Replit collector remains the live application evidence, not a new authentication test from Codex.

**Concurrent activity:** by 14:12 UTC the same read-only preflight found **10 products** and **20 private tables**, with new `free_batches`, `free_batch_tasks` and `free_batch_products` tables. Counts remained 43 sources / one enabled source / one review. All 20 tables still had RLS and denied public reads, including schema USAGE. This work created none of those products/tables. Another session appears to be modifying the live app/database. The free-batch tables already contain request/record/product/page limits and expiry fields; inspect and reuse the actual current implementation instead of adding a competing batch engine. Do not assume these observations are a stable deployment checkpoint. Refresh preflight and coordinate with that session before any migration or worker change.

The final saved preflight at **14:14:49 UTC** found **43 sources, one enabled source, 10 products and 10 reviews**. Its 20 private tables still had RLS and denied public reads/schema usage, with no normalized product conflicts. Reviews therefore also increased in the other session during this review. No collection request or database mutation was issued by this work. The snapshot is timestamped evidence, not a guarantee that a concurrently changing database will retain these counts.

## Access blocker

The connected Replit integration cannot see Review Capture Hub. Its accessible app list belongs to another account and contains neither that title nor Veriflow. Do not create a replacement app, guess an app ID or modify unrelated apps. The existing application needs to be shared with / connected to this integration under the correct account (`service362`), or its actual current source must first be backed up from Replit into a separate branch of Unity20092024/Veriflow. An app URL helps identify it but does not itself grant access.

Only the Codex branch and review package are backed up here. **The Replit application's current source has not been obtained or backed up by this work.** No integration into its running code, deployed worker or exports can be claimed until that source/access is available. Never paste secrets into chat or commit its environment files.

## Schema differences: no blind migration replay

| Area | Current live Replit database | Codex ff62e18 | Safe integration decision |
| --- | --- | --- | --- |
| Categories | categories/product_categories already exist, including normalized category index | Administration migration creates both | Preserve them; do not replay CREATE TABLE or reseed categories |
| Products | name/vendor uniqueness; no website column or normalized identity index | Product helper depends on both additions | Reuse the working Replit product helper; port only after checking its actual source. Do not copy Codex discovery helper blindly |
| Durable jobs | collection_jobs and collection_job_items, with leases/cursors/counters | admin_jobs/admin_settings | Keep Replit's working queue and reporting. Do not rename/drop/replace queues or start Codex's competing worker |
| Controlled batches | free_batches/free_batch_tasks/free_batch_products appeared during review | No matching engine in ff62e18 | Obtain the latest Replit checkpoint and reuse its current batch controls; do not introduce another engine or assume its larger defaults are approved |
| Batch linkage | import_batches.collection_job_item_id exists | Codex worker does not complete that lifecycle | Port normalized records through the existing enqueue/ingest completion path; preserve counters/leases/receipts |
| Recurrence | No recurrence table observed | recurring_schedules.last_job_id references admin_jobs | The Codex recurrence SQL is incompatible as-is. Adapt scheduling to enqueue the existing collection_jobs once the actual app code is available |
| Apify monitoring | next_poll_at/poll_failures absent | Optional monitor migration adds them | Not needed for this $0 free-source integration; leave paid monitor disabled |
| Licenses | review_licenses already permits CC-BY-SA-4.0 and CC-BY-4.0 | Same license set | No license-constraint replacement needed. Keep text, credit and original native scales |

Migration history still lists five original versions; newer live Replit additions are not recorded there. History alone must not determine what SQL to apply. `scripts/preflight_replit_integration.sql` inspects the actual schema and counts without reading review text or modifying anything. The sanitized read-only snapshot is in `docs/evidence/replit-live-preflight-20261115.json`.

No migration file is added for this review package: required worker/job relationships cannot safely be finalized without the actual Replit application source. After obtaining it, prepare one additive reconciliation migration only for missing scheduling storage/constraints/indexes. Keep existing records, IDs, grants and policies. Check recoverable backup and preflight immediately before application, use a short transaction lock timeout, roll back on conflict, then verify row counts and privacy again. Do not mark unapplied Codex migrations as applied or drop existing tables to make migration history match.

## Reuse the connectors without rebuilding the application

- Preserve the existing lib.reviews connector, routes, dashboard and worker. Treat Codex's upstream tests as reference behavior, not proof that Replit is integrated.
- Reuse the standalone Mangrove HTTPS client/normalizer in `veriflow/mangrove_live.py`. The higher-level mangrove_collection module depends on Codex's product helpers/queue and must be adapted, not wholesale copied into Replit.
- Port the narrow Mangrove original-API attribution URL validation from `veriflow/licensing.py` and source-bound connector validation from `veriflow/connectors.py`. Keep equivalent existing validation for every other source. Mangrove ratings remain 0–100; Firefox retains its original 0–5 scale.
- Mangrove pagination uses API offsets; Replit's cursor_url cannot be assumed to understand them. Preserve persistent progress using its existing worker conventions after inspecting them. Recheck authorization, individual review license and product mapping before enqueue and ingest; do not overwrite revoked grants.
- Maintain existing deduplication keys and preserve both sources' provenance/credit. Keep actual fetched text and private backups out of this public repository.
- Verify the existing export implementation includes all required license, credit and change-notice fields beside each exported record in every format. This has not been inspected in Replit yet. A counts-only database query cannot prove its exports are compliant.

## Controlled batch awaiting approval

The exact proposal is `data/proposed-free-batch.json`. It is deliberately **non-executable**, creates no authorization and enables no source or schedule.

| Source / product | Text and retention conditions | Batch limits |
| --- | --- | --- |
| lib.reviews / Mozilla Firefox, existing exact live mapping | CC BY-SA 4.0; public author credit beside the contribution plus original profile/source links, license and change notices; ShareAlike where applicable on redistribution | At most 10 reviews, five listing pages and 50 total HTTP attempts, including policy reads and redirect hops |
| Mangrove / Bitwarden, exact subject https://bitwarden.com | Accept CC-BY-4.0 only, including the documented default when no individual license is specified. Original native review hyperlink/source credit, license/change notice. Reject incompatible imported CC-BY-SA contributions rather than relabeling them | At most 10 reviews, five API pages and 30 total HTTP attempts, including policy/discovery reads |

**Combined ceiling: 20 eligible reviews retained/ingested, 80 HTTP requests, one source request at a time, $0 paid-service budget.** Mangrove's native pagination returns 20 candidate rows per page (up to 100 over five pages); incompatible candidates are discarded, not stored or relabeled. The cap is ten eligible Mangrove reviews, not a claim that only ten raw API rows are received. Native clients enforce total request bounds; partial results must be reported honestly if a bound prevents completion. Requests are at least two seconds apart (longer robots delay wins), timeout after 20 seconds and read at most 1 MB each. No automatic batch retries; stop on rate-limit/permission/policy errors. Do not call Apify, Composio or paid APIs. No hosting purchase or plan upgrade. Existing hosting/database usage stays within the operator's current resources; no claim that ordinary infrastructure usage has no cost.

Store permitted text/metadata privately until manually deleted; no automatic purge, publication or replacement of existing rows. Collect no unnecessary reviewer identity. Private exports must retain each source's license/attribution/change notices. Existing duplicates count as duplicates; no guaranteed number of new reviews. Native Bitwarden API data was verified in the earlier isolated test; this review has not fetched new review records.

Both sources' policy pages were rechecked without review retrieval. The lib.reviews permission digest is unchanged. Mangrove's digest changed since the earlier test; a visible-text comparison found a wording change to the list of things users may review. The commercial dataset reuse, per-review license/default and hyperlink-attribution conditions remain. The newly reviewed digest is recorded in the proposal. Recheck before execution and stop for renewed review if relevant terms change.

## Recurrence acceptance after source access and integration

Schedules should default paused. Support product/category selection, 6–168 hours (24-hour default), bounded per-run records and a clear pause control. A running server-side worker is required; no browser tab or independent paid scheduler should trigger collection. Persist schedule state and enqueue atomically, prevent overlapping selections/jobs and avoid catch-up floods after downtime. Respect source pauses, cooldowns, scope revocation and permission expiry. Pausing prevents future requests, not an already running request. Stop/start the same worker in a fixture test to verify persistence.

The approval requested here is for **one batch only**, not ongoing recurrence. Do not enable recurring live retrieval until the user approves its separate duration, interval and per-run limits. Finish one approved live run, inspect preserved Firefox plus any new Bitwarden row, rerun only if separately authorized to check duplicates, and verify one private export before expanding the scope.

## Handoff order

1. Restore access to the existing Replit app or securely back up its actual source to a separate GitHub branch. Preserve its current working commit first.
2. Adapt the reusable client to its current worker and prepare additive scheduling reconciliation; no frontend rebuild.
3. Validate with fixtures and the existing export path; apply only the reconciled changes after review, then recheck live counts/security.
4. Obtain explicit approval of the exact batch proposal; only then activate the necessary scope and execute once through the dedicated application role.
5. Record safe retrieved/inserted/duplicate/error counts and an export receipt. Keep Draft PR #1 and main untouched. Do not represent this preparation as a completed Replit deployment.

## Checks performed on this review branch

The preflight query was executed directly on the existing project and its safe result saved. The proposal JSON was checked for non-executable/pending approval state, disabled paid providers/recurrence and consistent aggregate limits. Fifteen existing lib.reviews/Mangrove extraction and license fixture tests passed in the isolated checkout without source retrieval. No application code changed; the upstream 138-test result remains historical and was not rerun or presented as a Replit integration test. Replit worker, UI and export acceptance remain blocked by access to the actual application.
