# Supabase deployment preparation and recurring free collection

Date: 2026-11-15. Work stays on the existing feature branch / Draft PR #1. No hosting purchased, second application created, paid collection enabled or production migration applied.

## Live Supabase status — not a deployment success claim

Read-only checks against **qrejfpeclncrevmepgzx only** confirm the five original migrations through 20261114133207, 42 disabled sources, zero products/reviews/Apify jobs, zero normalized product conflicts and a clean security advisor. The two earlier pending migrations remain compatible with this checked state; a new recurrence migration is separately staged. The reviewed plan in pending-migration-review.md preserves existing rows, RLS and permissions.

**The existing Supabase database is not yet receiving reviews from the application.** Codex's previously established native PostgreSQL path is blocked; no repeat socket/password attempts were made. A suitable existing runtime with verified PostgreSQL access and the current dedicated-role credentials is still required. The connected external app integration could not access the user's named app in previous work. No runtime is invented, no owner/management API insertion is presented as collector ingestion, and no credentials are requested in chat.

Source HTTP connectivity and local PostgreSQL validation are separate from this production transport requirement. The genuine checks below used a private local PostgreSQL 17 instance with the restricted application role; they are not Supabase application-authentication/TLS tests.

## Deployed-runtime acceptance command

On the **actual chosen runtime**, with native server-side secrets and all reviewed migrations installed:

```sh
python -m veriflow check-deployment --source-policy
```

This is read-only. It checks the dedicated non-owner application role, encrypted/verified client configuration, expected private tables and monitor columns, original registry IDs, RLS/public denials, disabled paid policy and optional live free-source terms. It prints safe structured results, no passwords/DSNs/keys. It neither enables sources, creates schedules nor fetches review text. `ready=true` is a configuration/readiness check, not proof of successful review ingestion; perform a selected product run and verify its saved row afterward.

Remote database connections require an explicit project reference, the application login, verify-full TLS and port 5432. For this project, the pooler hostname is pinned to the user-supplied official `aws-1-us-west-2.pooler.supabase.com`; transaction port 6543 is refused because the durable worker uses session advisory locks. No password is regenerated or TLS verification downgraded. Local-only test connections remain supported.

## Recurring collection

A new private **Recurring** screen saves a product or category selection per reviewed free provider. Intervals are 6–168 hours (24 hours by default), with at most 20 reviews per request. Schedules default disabled and require explicit activation. Both lib.reviews and the reviewed Mangrove collection are supported; Apify/Composio/other providers cannot be scheduled through this free allowlist.

The existing `application-worker` calls the scheduler before processing queued jobs. No separate paid scheduler or external queue is introduced. `python -m veriflow schedule-due` can also perform one bounded enqueue pass; it does not itself retrieve reviews.

Schedules and requests commit together, use row locking / deterministic request keys, skip overlapping queued/running jobs, respect paused sources and persisted source cooldowns, and avoid a flood of missed runs after downtime. A paused source is checked later without network retrieval; a disabled schedule queues nothing. Future runs recheck source terms, scope, license and revocation. Stopping recurrence affects future requests, not a job already in flight.

Tests simulate a newly available second review between due times: the second scheduled run inserts the new ID and counts the existing one as a duplicate without another manual START request. This does not claim a new review appeared on the live source during testing.

## Real unattended validation

In the isolated local environment, a browser saved an enabled daily Firefox schedule. The worker automatically queued and executed it without pressing START again: one real review retrieved, zero inserted, one duplicate. The next due time persisted. The validation schedule was paused afterward, and the validation worker stopped; no unattended source polling was left running.

See evidence/recurring-expansion-live-20261115.json. It also records the second real source validation. Source review text, original author identities, JWTs/issuer keys and database backups are not committed to Git.

## Practical second free source: Mangrove

The [Mangrove terms](https://mangrove.reviews/terms) explicitly welcome commercial dataset/API reuse with attribution. Native records default to **CC BY 4.0 only when no per-review license is specified**. The [documented API](https://docs.mangrove.reviews/) exposes bounded GET review queries with limit/offset pagination and original 0–100 ratings. API documentation's Apache license is not being mistaken for the dataset license.

The adapter accepts only CC-BY-4.0 records, with source terms rechecked per job. It rejects incompatible per-review licenses (including imported CC-BY-SA records) instead of relabeling them. It stores native text/date/rating/scale/subject/signature and a direct original Mangrove API review permalink. The source terms permit attribution through a review hyperlink; the app displays that source credit/link and license beside the text. JWTs, public issuer keys, aliases, images and unrelated identity fields are discarded. The source-specific attribution exception accepts only the fixed canonical api.mangrove.reviews/review/<native-signature> path; other sources' attribution rules remain strict.

Discovery is intentionally limited to actual eligible API records for audited software subjects (currently Bitwarden, GitHub, Codeberg, Keybase and Mangrove itself). It is not arbitrary website classification. Collection is capped at 20 reviews / five pages, fixed HTTPS endpoints, bounded responses, paced requests and timeout/rate-limit handling. Pagination advances over all returned records while counting unsupported licenses as skipped.

A real browser/worker run discovered **Bitwarden**, retrieved one existing review and saved it as `veriflow_app`: **75/100**, native source date **2021-01-21**, **398 characters**, CC-BY-4.0. It used real public API data, not the incompatible lib.reviews imports also present in Mangrove. Existing Firefox data was retained. Two real review rows now exist in the private local validation database, across two sources; none were inserted into live Supabase.

Original 42 registry entries remain unchanged. Optional activation adds lib.reviews and/or the separately labeled Mangrove collection; both enabled local validation sources give 44 runtime entries. Production still has 42 disabled entries.

## Packaging / preserved features

Product/category browsing, manual search, source controls, deduplication, review inspection and all five export formats remain. The existing portable Docker/Compose configuration uses the same application worker; Apify monitoring is now an explicit optional Compose profile (`--profile apify`), not a required default service. Composio remains optional/last and its SDK is excluded from the default core image.

The recurrence migration adds one private RLS-protected table; latest code expects 18 tables. No schedule or source is seeded by any migration or normal startup. A new actual deployment must apply the reviewed three pending migrations before starting this revision. Do not run the stack against the old 13-table production schema.

## Verification

**138 tests passed**, including previous UI/export/collector behavior, both free adapters, per-review licensing and native ratings, request negotiation, recurring uniqueness/overlap/pause/cooldown/new-review behavior, remote connection guards and migration preservation/rollback. Dependency checks and Compose configuration validation passed. The actual public-source/local-database evidence is separate from these fixture tests. Production database readiness remains unverified until the real runtime acceptance check and saved-row test succeed.
