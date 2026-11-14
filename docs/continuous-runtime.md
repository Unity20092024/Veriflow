# Continuous engine development in Codex

The engine continues to be developed and tested here. External app access is not a dependency for fixture development, schema validation or local end-to-end tests. Live secrets, provider permission and hosting connectivity are separate deployment prerequisites.

## Monitor known Apify runs

`python -m veriflow apify-monitor` continuously checks due jobs that already have a known Actor run ID. `--once` checks at most one due job; `--interval 60` controls successful-run polling (allowed range 30-3600 seconds). `deploy/veriflow-apify-monitor.service` supplies an optional process-manager unit; it is not enabled by this change.

The monitor never submits a new run and never retries uncertain starts. It skips starting/start_unknown, queued, completed, failed and aborted jobs. The ingestion worker remains separate: `python -m veriflow worker`. Completed datasets pass through the existing approval/product/field-validation and deduplication flow before review insertion. Revoked source approval uses the existing refresh logic to request cancellation of an owned active run; no collection permission is inferred by monitoring.

A transaction advisory lock serializes monitor processes. The refresh layer uses the same source-before-job lock ordering as ingestion, so manual and automatic refresh cannot duplicate queue insertion. Successful jobs are polled at the configured interval; transient failures back off exponentially; missing/invalid credentials wait at least five minutes. Retry-After is respected up to the existing one-day client bound. `next_poll_at` and consecutive `poll_failures` persist in PostgreSQL across process restarts. A restart never reconstructs or retries a paid start.

Monitoring is not a promise of zero provider charges: existing runs and dataset operations may already incur reviewed usage charges. It retains existing spending reservations and source-specific approval checks; it does not release uncertain costs. Paid-start gates remain false, all live sources remain disabled and no monitor was launched against production.

## Additive migration — not applied to live Supabase

`supabase/migrations/20261114230002_apify_poll_schedule.sql` adds the poll deadline, failure counter and a due-running-job index. It changes no grants, RLS, passwords or source authorization. It was generated with the Supabase CLI and tested on disposable PostgreSQL only. No remote migration or schema change was performed.

Deploy this code only with its reviewed migration installed by the authorized migration process. `check-database` now reports missing monitor columns and fails readiness if that migration is absent. The dashboard Collection page shows poll failures, next poll and last update; it also requires the new migration. Do not rerun historical migrations, reseed the production registry or run migrations at ordinary application startup.

## Private dashboard hosting settings

The default remains `127.0.0.1:8080`. The dashboard accepts a `PORT` server environment value or explicit `--port`; an explicit port wins. Managed hosting can explicitly use:

```sh
python -m veriflow admin --host 0.0.0.0
```

`0.0.0.0` is opt-in, never selected merely because PORT is present. Only loopback and the explicit all-interfaces binding are accepted. ADMIN_USERNAME and a 24+ character ADMIN_PASSWORD remain required for either binding; no anonymous data route, authentication bypass or browser database credential is introduced. All existing cache/security headers remain. Use external binding only behind the hosting platform's HTTPS termination and intended access controls; the built-in HTTP server does not itself implement TLS.

The processes are distinct: dashboard, ingestion worker, optional known-run monitor. Starting them does not enable sources, grant authorization or schedule Actor submissions. An automatic paid-start scheduler is still out of scope until source rights, actual pricing and effective total spending controls are confirmed.

## Validation

All **97 tests passed** with mocked provider responses and a fresh disposable PostgreSQL instance. They cover monitoring through queue/ingestion without additional Actor starts, durable Retry-After cooldown across a new connection, uncertain-start preservation, missing credentials, concurrent monitor exclusion, retained failure/cost information, successful recovery, dashboard bind/auth boundaries and pending-migration detection. No live PostgreSQL connection attempts or provider collection were made for this development increment.
