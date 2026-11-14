# Live database connectivity diagnosis — 2026-11-14

Status: **BLOCKED — application connectivity has not been verified.** No migration, role, source activation, password reset or network-security change was performed during this diagnosis.

## Verified findings

| Check | Result |
|---|---|
| Exact project | `qrejfpeclncrevmepgzx`, Veriflow, us-west-2, ACTIVE_HEALTHY |
| Official direct host from project metadata | `db.qrejfpeclncrevmepgzx.supabase.co:5432`, database `postgres` |
| Direct IPv4 DNS | No A record |
| Direct IPv6 DNS | AAAA record exists |
| Direct IPv6 TCP from this workspace | Fails with OS errno 101, Network is unreachable, before TLS/authentication |
| Current client | psycopg/libpq 17.6; `sslmode=verify-full`, `sslrootcert=system`; 153 system CA roots available |
| TLS handshake / password authentication | Not reached; neither certificate validity nor password correctness can be claimed |
| Application login metadata | `veriflow_app` is LOGIN, no expiration, no connection limit; inherits `veriflow_runtime`; no superuser/BYPASSRLS |
| Schema checks through management API | 13 private tables, all RLS enabled; app SELECT allowed; anon/authenticated schema and table SELECT denied |
| Source count through management API | 42, all disabled |
| Supabase health / security advisors | No findings |
| Real local dashboard HTTP check | Anonymous `/sources`: 401; authenticated `/sources`: 503 with generic Database unavailable message |
| Apify | Paid execution remains disabled |

The management API runs outside the application's PostgreSQL transport. Its successful source count is not evidence of a successful application connection. `sslrootcert=system` is a supported libpq sentinel, not a missing certificate filename. No TLS verification was weakened.

## Session pooler: exact settings required

Current [official Supabase connection guidance](https://supabase.com/docs/guides/database/connecting-to-postgres) recommends the shared session pooler for persistent applications on IPv4-only networks. In this project's dashboard, open [Connect → Session pooler](https://supabase.com/dashboard/project/qrejfpeclncrevmepgzx?showConnect=true&method=session). Obtain **only the Host and Port** fields. The documented session port is 5432; use the actual panel values.

Supabase explicitly says a pooler cluster index cannot be inferred from region. Previous regional hostname guesses are not verified project settings and are not a valid basis for declaring this project's session pooler unreachable. The current Supabase connector exposes project/direct-host metadata but no pooler-configuration endpoint, and no connected browser tool or separate management credential is available in this workspace. The exact session-pooler Host/Port has been requested as non-secret information; no passwords or tokens are requested.

Once those settings are available, preserve the existing application password in server configuration and use the shared-pooler username `veriflow_app.qrejfpeclncrevmepgzx`. Keep database `postgres` and verified TLS. Test the actual endpoint's DNS, TCP, TLS chain/hostname and application authentication separately. Do not use the owner login or transaction-mode port as a workaround. If certificate verification fails, obtain the official applicable CA chain from this project's Database settings; do not replace verify-full with require/disable.

Then run:

```sh
cd /workspace/Veriflow
VERIFLOW_ENV_FILE=/workspace/.veriflow-secrets/runtime.env .venv/bin/python -m veriflow check-database
```

A successful result must identify the real application role, verified encrypted transport, all expected private tables, 42 source rows and preserved security controls. Next repeat authenticated dashboard `/sources` and require HTTP 200 with all 42 source names. Never print the runtime file, connection string, Authorization header or password. No reseed/migration rerun is needed.

## Infrastructure fallback

The confirmed infrastructure blocker is missing usable outbound IPv6 routing to the project's direct endpoint. There is not yet evidence establishing that this exact project's IPv4 session pooler is unreachable. Try the confirmed session endpoint before moving anything.

If the workspace also cannot reach the confirmed session endpoint, the simplest alternative is an existing persistent Linux server/container host with working outbound TCP 5432: use the session pooler over IPv4, or the official direct endpoint if the host has working outbound IPv6. Move only the private Python application/dashboard and server-side configuration, keeping the same existing Supabase database. Bind the dashboard to loopback and use an authenticated HTTPS reverse proxy or SSH tunnel for access. No new database, public Data API exposure, public website or paid IPv4 add-on is needed for that approach. Test from the chosen host before deploying.

**READY FOR APIFY CONFIGURATION must not be reported until the application health command and authenticated dashboard both pass against the live database.**
