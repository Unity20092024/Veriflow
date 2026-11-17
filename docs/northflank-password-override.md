# Northflank application password override

Verified against application commit
`66dc234cc117eab74cabe7edbd564a0df25dd18a` on 2026-11-17.
**No production-code fix or database migration is required.** This verification
branch adds only tests and these instructions. No deployment, credential change,
live connection attempt or collection was performed by Codex.

`veriflow.db.connection_settings()` loads the server environment, parses the
existing URL, then replaces its password with a nonempty `VERIFLOW_APP_PASSWORD`.
`connect()` passes the resulting settings to `psycopg.connect` as keyword
arguments. The worker calls this same `connect()` before `run_cycle()`; there is
no separate worker connection implementation. Host/user/project guards,
session port 5432, verify-full TLS, CA and timeouts are retained.

A bare `psycopg.connect(os.environ['SUPABASE_DATABASE_URL'])` does not use the
separate application variable. Its authentication failure is therefore expected
when the URL contains an old password. It does not prove that the application's
connection path fails. The worker's generic `worker_database_unavailable` message
also covers errors later in its cycle, not only password failures.

## Safe check in the existing container

Use the **existing worker container's** Northflank command console, working
directory `/app`. This reads the existing environment and executes only
`SELECT 1`; it neither runs the worker cycle nor changes jobs. It prints only
booleans, the module path, exception class and SQLSTATE. Do not print the URL,
settings dictionary, password, environment, exception text or traceback.

```sh
python - <<'PY'
import json
import os
from veriflow import db

try:
    settings = db.connection_settings()
    override = os.environ.get('VERIFLOW_APP_PASSWORD')
    print(json.dumps({
        'module': db.__file__,
        'override_present': bool(override),
        'override_applied': bool(override) and settings.get('password') == override,
    }))
    with db.connect() as conn:
        ok = conn.execute('SELECT 1 AS ok').fetchone()['ok'] == 1
    print(json.dumps({'application_select_1': ok}))
    raise SystemExit(0 if ok else 1)
except Exception as exc:
    print(json.dumps({'application_select_1': False,
                      'error_type': type(exc).__name__,
                      'sqlstate': getattr(exc, 'sqlstate', None)}))
    raise SystemExit(1)
PY
```

Expected: module `/app/veriflow/db.py`, `override_present=true`,
`override_applied=true`, `application_select_1=true`. These values reveal no
credential. A successful result verifies application authentication only, not
the entire collection cycle. Do not run `worker --once` as a connection test:
it can process previously queued work.

If `override_present` is false, the variable is not available to this process.
If `override_applied` is false despite a present override, inspect the actual
deployed module/image/revision: it does not match this verified code path.
If both are true but connection fails, do not reset anything. Use the error
class/SQLSTATE and confirm the test was in the same service/container and used
the existing value that already passed your explicit-password check.

## Runtime settings and controlled restart

No new image is necessary to obtain override support: `66dc234` already has it.
The verification branch `verify/northflank-password-override` has identical
application and Docker code, so switching branches is optional.

Before changing runtime settings or restarting, pause/scale the worker to zero
in Northflank. Restoring working authentication on a running worker can
immediately process existing queued work. Preserve all database checkpoints;
do not change job states or renew approvals to troubleshoot authentication.

In the **veriflow-worker service**, verify the existing secret/group is attached
as **runtime** environment configuration, not build variables or only the
dashboard's configuration:

- `SUPABASE_DATABASE_URL`: preserve the existing verified app-role session URL.
- `VERIFLOW_APP_PASSWORD`: bind the existing working dedicated-role secret.
  Use its raw value, without added quotes or URI percent-encoding. Do not trim
  or transform the password; do not reset or regenerate it.
- Preserve `SUPABASE_SSL_ROOT_CERT=/app/certificates/supabase-ca.crt` and
  `SUPABASE_PROJECT_REF=qrejfpeclncrevmepgzx`.
- Keep all three paid Apify switches/budgets disabled/zero.

Saving runtime variables may trigger a service restart; keep the worker paused
until approved. Keep the Dockerfile `deploy/portable/Dockerfile`, repository-root
build context, image entrypoint `python -m veriflow`, eventual CMD `worker`,
exactly one replica, no ports, autoscaling off and automatic deployment off.
No pre-deploy/migration commands are needed.

For a read-only check before resuming collection, use Northflank's one-off command
facility if available with the same image/runtime secret configuration and run
`python -m veriflow check-database`. If it offers only a CMD override while
preserving the image entrypoint, use `check-database`. This command only reads
database health/security metadata and counts. Do not add a second worker or
change the deployed worker's command to `worker --once` for verification.
If no one-off facility is available, use the existing-container check above;
do not resume paused collection solely to open a shell.

After approval, restart/resume only the single existing worker. Existing
checkpoints, deduplication, approvals, licensing, budgets, Breadth First and
operator controls remain exactly as in `66dc234`. Live authentication through
the application still requires the container check above; local tests use
synthetic credentials and mocked transport, not production secrets.
