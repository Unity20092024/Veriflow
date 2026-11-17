# Collection operations: Northflank cutover

Reviewed 2026-11-17 against the recovered Replit source, snapshot `06f8a4d`,
and Northflank preparation `b95da6e`. Application fixes are isolated on
`fix/northflank-collection-operations`. Draft PR #1 is unchanged.

**GO for deployment preparation using this patched branch. NO-GO for starting
the worker from the earlier preparation branch. Production activation still
requires approval and the checks below.** No Northflank deployment, live source
request, production database write, credential change or migration was performed.
The working dashboard/database connection is user-reported, not independently
retested here. The actual running Northflank revision has not been inspected.

| Requirement | Finding and minimum fix |
| --- | --- |
| Start | Existing authenticated `POST /collection/start`; eligibility, source approval and Breadth First default retained. |
| Pause / Stop / Resume | Missing in the recovered application. Added authenticated, same-origin, CSRF-protected `POST /collection/pause`, `/collection/stop`, `/collection/resume` and small controls on the existing Collection page. |
| Saved progress | Controls operate on the existing job/batch ID. Cursors, pending imports, counters, deadlines, targets, product scope and authorizations are retained. |
| Restart recovery | Existing expired fetch leases and transactional imports retained. Local checks recovered the exact saved cursor and rolled back/retried an import without duplicate reviews. |
| Completed stays completed | Resume accepts only explicitly operator-paused/stopped, unexpired work. Completed, partial, failed, policy-blocked, expired and limited work cannot be restarted using Resume. Delayed callbacks cannot reopen a stopped parent. |
| Exports | Existing authenticated `GET /exports/reviews.csv`, `.xlsx`, `.json`, `.jsonl` retained with filters and attribution. This archive has **no ZIP export endpoint**, despite earlier reports. No export redesign was added. |
| Worker ownership | New PostgreSQL session advisory lock covers the entire existing ingest/fetch/bounded cycle on one connection. Concurrent updated worker copies skip work. A lost connection releases ownership. |
| Docker | Existing Python 3.12 Dockerfile supports both processes separately; no Node build or migration hook is required. No Dockerfile change was needed. |

## Control semantics

Pause and Stop both halt further work and retain a resumable checkpoint. They
are not deletion or permanent cancellation. An HTTP request already in flight
may finish and save its cursor/import; an ingest transaction already holding its
control lock may finish before the Stop response. Subsequent pending imports
are held until Resume. Resume does not renew approval, the original deadline,
request allowance or spending budget. The worker still rechecks current source
permissions, product mappings and licensing before ingestion or requests.

No SQL migration or permission change is needed: paused/stopped generic jobs
use the existing `cancelled` state plus `operator_paused`/`operator_stopped` error
markers; the one-time free batch uses `blocked` plus the same markers. Other
cancelled/blocked work is not resumable. Child checkpoints remain unchanged.
The dashboard displays the operator state separately from these storage states.

## Controlled deployment settings

Use the existing repository **Unity20092024/Veriflow**, branch
**fix/northflank-collection-operations**, for both services. Keep the currently
working dashboard's configuration and credentials; change only its code revision
after approval. The new controls require updating the dashboard as well as the
worker to this revision.

| Setting | Dashboard | Worker |
| --- | --- | --- |
| Dockerfile / build context | `deploy/portable/Dockerfile` / repository root `.` | Same |
| Image entrypoint | Keep `python -m veriflow` | Same |
| CMD override | `admin --host 0.0.0.0 --port 8080` | `worker` |
| Public port | Existing HTTP 8080 behind Northflank HTTPS | None; remove inherited 8080 |
| Replicas | Existing one | Zero/paused until approved; exactly one after cutover |
| Health check | Existing TCP 8080; anonymous HTTP returns 401 | No HTTP/TCP probe; no listener |
| Automatic CD / autoscaling | Preserve deliberate deployment control | Off / off |
| Database / migration hooks | Existing Supabase only / none | Same |

Retain the existing app-role session connection, verify-full TLS and packaged CA.
Reuse the existing runtime secrets; never put them in build arguments. Keep
`APIFY_PAID_RUNS_ENABLED=false`, `APIFY_MAX_RUN_USD=0` and
`APIFY_ROLLING_24H_BUDGET_USD=0`. Select only the already included $0 Sandbox
resources; do not add services beyond its free allocation or buy addons.

Before starting an approved worker:

1. Confirm the deployed branch/revision and existing schema match this recovered
   application. Read-only verification only; do not replay migrations.
2. Stop any older Replit, Northflank or other worker. Older code does not honor
   the new global lock and does not safely hold paused imports.
3. Deploy the patched dashboard first, keeping the worker paused. Check existing
   login, read-only review browsing, exports and the Collection page.
4. Inspect existing job/batch states, original deadlines, grants and product
   scope. Starting a worker can immediately process previously queued work;
   startup does not create or approve a new scope. Do not start it until the
   operator has approved processing the outstanding work.
5. After approval, start exactly one persistent worker. Observe checkpoint and
   request counters, logs without secrets, authentic review attribution and
   duplicate counts. Verify Stop/Resume using that approved scope. These live
   Northflank checks are pending, not claimed complete.

If rolling back, stop the worker first. Do not run the older worker against
operator-paused imports; it lacks the new protection. Do not clear or rewrite
production state as a rollback workaround.

## Validation evidence

- 115 offline tests passed, including 13 new control/HTTP authorization/CSRF and
  worker-ownership checks.
- Nine new integration tests passed against uniquely named disposable databases
  on a local PostgreSQL instance, including dashboard rendering, saved cursors,
  stop during a fetch, restart/deduplication, original free-batch limits and real
  session lock ownership. Transport was mocked; no real reviews were requested.
- 41 existing database regression tests passed in a separate disposable local
  database, including RLS, denied anonymous access, source approvals, licensed
  attribution, native deduplication and mocked provider spending guards.
- Total: **165 distinct tests passed**. One older HTTP subprocess test was not
  run because it supplies a localhost application URL that the recovered exact
  Supabase-host connection guard correctly refuses. Handler auth/CSRF and actual
  local database rendering were checked separately without weakening that guard.
- The ordinary full discovery with the opt-in local tests enabled reported 166
  tests, 124 passed / 42 original database tests skipped. The 41 database tests
  above were then exercised separately with a database-local bootstrap that
  reused existing local test roles without resetting passwords.
- `git diff --check` and CLI import/help passed. No Supabase migration files,
  database security settings, credentials, strategy defaults or paid collector
  configuration changed. A new image build and live Northflank worker verification
  remain deployment-time checks; local image build was avoided due to less than
  1 GB available disk space. The existing Docker recipe was inspected, not rebuilt.
