# Resume scheduling repair

Prepared 2026-11-18 on `fix/resume-pending-ingestion`, based on the deployed
application revision `66dc234`. Nothing was deployed or run against production.

## Behavior and scope

Previously, the importer selected any due enabled source, even when its only
pending import belonged to a stopped job. That idle poll advanced the source's
next-run timestamp by its normal schedule, often 24 hours. Resume preserved the
checkpoint but left ingestion behind that artificial delay.

The importer now chooses sources with eligible pending imports. Paused/stopped
and terminal-parent work cannot trigger idle scheduling writes or starve other
eligible sources. Eligibility is checked again after locking the source/import,
and the existing parent control locks are still acquired before ingestion.

Already affected checkpoints can recover without manual SQL: only a source with
`last_status='idle'` whose next-run timestamp exactly matches the old idle
scheduling calculation may be ingested early, and only after its minimum source
interval has elapsed. Future success, error, rate-limit or custom schedules stay
in force. No timestamp is reset merely because an operator clicks Resume.

This changes **only `veriflow/worker.py` in production Python code**. The
frontend, dashboard handlers, authentication, Supabase connection guard and
password override, worker ownership lock, source approvals, licensing, record
deduplication, paid-provider controls and all migrations remain unchanged.
Resume does not renew a grant, completed batch, deadline or budget.

## Regression coverage and results

Complete local command (the DSN must be supplied securely for the existing local
test cluster, never the Supabase project):

```sh
python -m unittest discover -v
```

Set `VERIFLOW_LOCAL_OPS_DSN` to the disposable local PostgreSQL test cluster
before this command if the database tests are to run. The guarded bootstrap
accepts only `postgres` on `127.0.0.1:55432`, creates uniquely named empty logical
databases, and reuses already provisioned test roles without changing passwords.
It does not truncate any pre-existing installation or replay SQL on Supabase.
The older `TEST_DATABASE_URL` mode remains supported for an empty disposable DB.

Final full-suite result: **174 passed, 0 failed, 0 errored, 0 skipped**.

- Actual local authenticated HTTP Start -> Pause/Resume -> fetch checkpoint ->
  Stop -> worker poll -> Resume -> ingestion, using synthetic source transport.
- Previously saved cursor and pending import preserved across process/session
  replacement; no source timestamp reset required to resume ingestion.
- Recovery from a persisted old idle deferral; source minimum interval retained.
- Future rate-limit/error/success/custom-idle schedules preserved without writes.
- Stopped source cannot starve another eligible source.
- Revoked authorization still rejects a resumed import.
- Completed jobs cannot resume, and worker copies retain session-lock exclusion.
- All existing licensing, attribution, source approval, paid-budget,
  deduplication and CSV/XLSX/JSON/JSONL export checks pass.

The legacy authenticated HTTP test's localhost subprocess URL contradicted the
production Supabase-only connection guard. The repaired fixture runs the real
HTTP handler with a disposable test connection injected at the handler boundary.
It verifies 401 without credentials and 200 for authenticated database-backed
content. Loopback test traffic explicitly bypasses environmental HTTP proxies.
The application's connection guard was not modified or weakened.

The first test attempt after starting the local PostgreSQL container encountered
its startup-recovery window; the full suite was rerun after `pg_isready` reported
accepting connections. The fixture's proxy handling was corrected before the
final successful full run. These were local test infrastructure issues, not
production connection attempts.

## Northflank deployment steps — perform only after review/approval

Use the **existing** Northflank project and services. Do not create another app,
database, worker, scheduled job or paid resource. This branch is preparation,
not permission to start collecting.

1. Pause/scale **veriflow-worker** to zero before changing its build settings.
   Keep worker automatic deployment and autoscaling off. Confirm no other worker
   (including an older Replit worker) is running. Keep the dashboard available.
   Do not change job, grant, source or batch records as a cutover workaround.
2. In the existing **veriflow-dashboard** build settings, select repository
   `Unity20092024/Veriflow`, branch `fix/resume-pending-ingestion`, and the exact
   review commit supplied with this repair. Choose Dockerfile build, repository
   root `.` as context, and `deploy/portable/Dockerfile`. No build arguments,
   release command, database addon or migration hook.
3. Preserve Docker entrypoint `python -m veriflow`. Dashboard CMD override stays
   `admin --host 0.0.0.0 --port 8080`. Keep its existing one instance, HTTP 8080
   behind Northflank HTTPS, and TCP readiness check on 8080. Preserve all existing
   runtime secrets, authentication and certificates. Deploy this dashboard
   revision manually only after approval. There are no frontend changes.
4. From that dashboard container's Shell, an optional read-only verification is:

   ```sh
   python -B -m veriflow check-database
   ```

   It reads health/security metadata and counts; it does not process jobs or run
   migrations. Do not dump environment variables, parsed settings or passwords.
   Check the existing login, read-only review browsing and exports normally.
5. In the existing **veriflow-worker** build settings, select the same repository,
   branch, review commit, Dockerfile and context. Keep it paused while preparing
   the image. Keep the image entrypoint unchanged and set CMD override to
   **`worker`**, not `python -m veriflow worker`. Keep **no public ports**, no
   HTTP/TCP probe, no autoscaling and no automatic deployment. Use only the
   existing free Sandbox allocation and existing runtime secret bindings.
6. Both services retain `SUPABASE_PROJECT_REF=qrejfpeclncrevmepgzx`, the existing
   dedicated-role session connection on 5432 with verify-full TLS,
   `SUPABASE_SSL_ROOT_CERT=/app/certificates/supabase-ca.crt`, and the existing
   `VERIFLOW_APP_PASSWORD` override where configured. Do not rotate or retype
   credentials. Keep `APIFY_PAID_RUNS_ENABLED=false`, `APIFY_MAX_RUN_USD=0`, and
   `APIFY_ROLLING_24H_BUDGET_USD=0`. No new tokens are needed for this repair.
7. **Stop here unless worker activation has separately been approved.** Saving
   settings or deploying a paused service can have platform-specific restart
   behavior: do not select Deploy/Resume if Northflank would start it immediately.
   When activation is approved, start exactly one instance of the fixed worker
   after the old one has stopped, preserving the existing checkpoint data.
   Starting it may immediately process eligible pending work; this repair also
   wakes imports affected by the older idle deferral. Real cooldowns still wait.

No new collection scope is approved by this fix. In particular, do not reopen
the completed broader lib.reviews batch, increase the exhausted Firefox pilot
allowance, enable Mangrove, or create new grants while deploying this repair.
Live source-to-Supabase collection verification remains a separate approved task.

For rollback, stop the worker first and select the previous image. An older
worker can reproduce the idle-deferral bug; do not manually change production
timestamps, credentials, grants, review records or schema to compensate.
