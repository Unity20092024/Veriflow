# Selective integration into the existing Replit application

**Current instruction: the two-product batch is declined and must remain unexecuted. Replit is authoritative for the live worker and dashboard. The user reports 11 genuine reviews across 11 products; the older snapshots below do not supersede that report. This task performs no live source/database requests, migrations, credential operations or competing job creation.**

The reusable connector is now isolated under `integration_patches/mangrove/`: standard-library Python, disabled by default, one worker-selected software product/page per call. It does not depend on Codex jobs, schema, product helpers or scheduler. [Patch contract and fixture tests](../integration_patches/mangrove/README.md). No existing application module was replaced.

Checked 2026-11-15 against **qrejfpeclncrevmepgzx only**. This branch starts at the exact fetched Codex commit `ff62e181766253a1e98fdd2d3885b3709b8d4a84` in an isolated checkout. It does not modify Codex's feature branch, Draft PR #1, the live schema, credentials, sources or records. No new collection has run during this integration review.

## Historical read-only observations — not current dashboard totals

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

No migration is added, applied or proposed for execution under the current task. The connector patch requires no SQL. Existing schema differences are documented for the Replit maintainer; neither migration-history differences nor Codex helper dependencies justify altering the working database. Preserve all live records, RLS, grants, worker tables and credentials.

## Reuse the connectors without rebuilding the application

- Preserve the existing lib.reviews connector, routes, dashboard and worker. Treat Codex's upstream tests as reference behavior, not proof that Replit is integrated.
- Selectively port the isolated `integration_patches/mangrove/connector.py`, not the Codex application adapter. The earlier `veriflow/mangrove_live.py` remains an upstream reference; `mangrove_collection.py` depends on Codex product helpers/queues and is excluded from this patch.
- Port the narrow Mangrove original-API attribution URL validation from `veriflow/licensing.py` and source-bound connector validation from `veriflow/connectors.py`. Keep equivalent existing validation for every other source. Mangrove ratings remain 0–100; Firefox retains its original 0–5 scale.
- Mangrove pagination uses API offsets; Replit's cursor_url cannot be assumed to understand them. Preserve persistent progress using its existing worker conventions after inspecting them. Recheck authorization, individual review license and product mapping before enqueue and ingest; do not overwrite revoked grants.
- Maintain existing deduplication keys and preserve both sources' provenance/credit. Keep actual fetched text and private backups out of this public repository.
- Verify the existing export implementation includes all required license, credit and change-notice fields beside each exported record in every format. This has not been inspected in Replit yet. A counts-only database query cannot prove its exports are compliant.

## Declined batch — do not execute

`data/proposed-free-batch.json` is an archived, non-executable proposal marked **declined_by_user**. It creates no authorization or schedule. Do not revive it, ask to approve it again or use its products/limits as a future default. No live review retrieval was started by Codex under that proposal.

Future proposals must prioritize **distinct software products, category diversity and authentic source evidence**, using Replit's existing Breadth First selection. Do not prioritize repeated depth on Firefox, Bitwarden or any other small product set. Do not imply a hardcoded software list or fixture demonstrates actual review availability for additional products.

## Worker and recurrence authority

The existing Replit worker owns scheduling, breadth selection, persistent cursors, budgets, source cooldowns, deduplication, database writes and job completion. The isolated patch returns at most one page and does not create or run collection jobs. No Codex scheduler, recurring table or advisory-lock job runner is ported. Server-side recurrence, if already present in Replit, remains unchanged and operates only through that worker. This task does not enable or extend its schedule.

## Handoff without overwriting working functionality

1. Review/selectively port only the isolated Mangrove module once the actual existing worker's connector boundary is available. No frontend, queue or scheduler replacement.
2. Supply Replit's existing verified software mapping, approved permissions, quotas and persistence callbacks. Adapt at its current boundary without changing schema or credentials.
3. Run fixtures first; preserve its lib.reviews behavior, breadth ordering, job completion, source labels, license attribution and exports. Offline tests are not deployed-worker acceptance evidence.
4. Leave the connector disabled for live use until there is a **new approved scope**. No live retrieval, source activation, new collection job or schema mutation is authorized by this patch.
5. Keep this work on `integration/replit-free-connectors`; preserve Draft PR #1, its source branch and main.

## Checks performed on this review branch

The preflight query was executed directly on the existing project and its safe result saved. The archived proposal is now explicitly declined, non-executable and not authorization for any future batch. Paid providers and proposed recurrence remain disabled. Fifteen existing lib.reviews/Mangrove extraction and license fixture tests passed in the isolated checkout without source retrieval. No application code changed; the upstream 138-test result remains historical and was not rerun or presented as a Replit integration test. Replit worker, UI and export acceptance remain blocked by access to the actual application.

Current patch validation: **9 isolated standard-library connector tests and 15 existing connector/license tests passed (24 total)**, with synthetic transports only. No live source request, database read/write or deployed-worker test was performed for this patch.
