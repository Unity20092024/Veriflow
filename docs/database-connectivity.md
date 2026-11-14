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

## Session pooler: official settings supplied and tested

The user supplied the project's Connect-panel endpoint: **`aws-1-us-west-2.pooler.supabase.com:5432`**. This replaces the previous missing-host blocker; it is not a guessed hostname. Current [official Supabase guidance](https://supabase.com/docs/guides/database/connecting-to-postgres) recommends this session-mode connection type for persistent IPv4 applications.

All three resolved IPv4 addresses returned **ECONNREFUSED (111)** on TCP 5432. An approved outside-sandbox check produced the same result. The standard workspace HTTPS proxy accepted HTTP CONNECT, then returned EOF on PostgreSQL's initial SSLRequest. No password was sent in those transport probes. The available evidence establishes failure before TLS/authentication; it cannot distinguish an upstream egress filter, an ingress restriction or a pooler-side refusal. Do not claim a bad password or certificate failure, or that the displayed unrestricted workspace network policy guarantees native PostgreSQL connectivity.

The owner-only runtime file now uses the supplied official pooler hostname/port and `veriflow_app.qrejfpeclncrevmepgzx`, preserving the existing password, database, verified TLS and other server configuration. The application's health command still fails; a fresh real dashboard probe returns anonymous 401 / authenticated 503 with this configuration. No database changes or new credentials were created.

For deployment, preserve the existing application password in secure server configuration and use the shared-pooler username `veriflow_app.qrejfpeclncrevmepgzx`. Keep database `postgres` and verified TLS. Test the actual endpoint's DNS, TCP, TLS chain/hostname and application authentication separately. Do not use the owner login or transaction-mode port as a workaround. If certificate verification fails, obtain the official applicable CA chain from this project's Database settings; do not replace verify-full with require/disable.

Then run:

```sh
cd /workspace/Veriflow
VERIFLOW_ENV_FILE=/workspace/.veriflow-secrets/runtime.env .venv/bin/python -m veriflow check-database
```

A successful result must identify the real application role, verified encrypted transport, all expected private tables, 42 source rows and preserved security controls. Next repeat authenticated dashboard `/sources` and require HTTP 200 with all 42 source names. Never print the runtime file, connection string, Authorization header or password. No reseed/migration rerun is needed.

## Infrastructure fallback

The confirmed infrastructure blocker is missing usable outbound IPv6 routing to the project's direct endpoint. The supplied official IPv4 session-pooler endpoint also refuses TCP connections from this workspace, both inside and outside the sandbox; its proxy path closes before PostgreSQL TLS. The application therefore has no verified PostgreSQL transport from this machine.

The simplest alternative is an existing persistent Linux server/container host with working outbound TCP 5432: use the session pooler over IPv4, or the official direct endpoint if the host has working outbound IPv6. Move only the private Python application/dashboard and server-side configuration, keeping the same existing Supabase database. Bind the dashboard to loopback and use an authenticated HTTPS reverse proxy or SSH tunnel for access. No new database, public Data API exposure, public website or paid IPv4 add-on is needed for that approach. Test from the chosen host before deploying. A TCP-only test such as `nc -vz aws-1-us-west-2.pooler.supabase.com 5432` needs no credentials. If that host also cannot connect, inspect this project's Supabase Network Restrictions and pooler health before relocating again; preserve existing restrictions and allow only an explicitly approved deployment egress IP if needed. No allowlist was changed during this diagnosis.

**READY FOR APIFY CONFIGURATION must not be reported until the application health command and authenticated dashboard both pass against the live database.**

## Next architecture decision

See [deployment-decision.md](deployment-decision.md): move the existing Python runtime to an always-on host and retain the confirmed session-pooler/private-schema design. No PostgreSQL attempts from this workspace were repeated for that decision. HTTPS Data API and Edge Function alternatives were evaluated; a narrowly authorized Edge Function is the fallback rather than publicly exposing private tables.
