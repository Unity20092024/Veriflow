# Portable private deployment

No hosting has been purchased and nothing is published. Reuse the existing dedicated Supabase project `qrejfpeclncrevmepgzx`; only application processes move between hosts.

## Runtime package

The Dockerfile builds the Python application with pinned core dependencies, the existing registry/policy and no secrets. Composio remains optional: `--build-arg INSTALL_COMPOSIO=true` installs the existing full requirements; the default image omits it. The image runs as UID/GID 10001. CSV/JSON/JSONL/ZIP/XLSX writers use the standard library rather than introducing an optional service or spreadsheet dependency.

```sh
docker build -t veriflow-private:development .
```

In this Codex workspace's TLS-inspecting build network, a trusted build CA was supplied through BuildKit's optional `build_ca` secret. It is used only for dependency installation and removed from the image trust configuration afterward. Never disable certificate validation or use a private API/database credential as a build argument. Ordinary deployments should use their native CA trust.

## Server configuration

Keep the existing application-role DATABASE_URL, SUPABASE_PROJECT_REF, ADMIN_USERNAME and ADMIN_PASSWORD in the host's native server-side secret settings or a mode-0600 environment file outside Git. APIFY_TOKEN is optional while no provider calls are made. The existing GitHub secret is not automatically injected into another runtime. Never use the owner account for normal jobs.

The supplied Compose file requires Docker Compose 2.30+ for raw env-file handling and uses `VERIFLOW_RUNTIME_ENV_FILE` to locate that existing private file. Do not place the file in the build context. Compose explicitly keeps paid execution false, run/day allowances zero and records at most 20 regardless of file values. Verify no conflicting VERIFLOW_ENV_FILE path points to an unmounted file.

```sh
# Set this non-secret path through the host's own environment settings.
# VERIFLOW_RUNTIME_ENV_FILE=/absolute/private/server.env
docker compose config --quiet
docker compose up -d
```

Avoid plain `docker compose config` in shared logs: it can expand secret values. Use `--quiet` for validation.

## Processes and storage

- **dashboard:** authenticated private administration. Host port is bound to 127.0.0.1:8080; use the host's HTTPS reverse proxy/access controls for remote access. No browser database credentials or anonymous data endpoints.
- **application-worker:** recurring free-source dispatch, durable administration requests, catalog discovery and exports. Session locks serialize requests; running state is committed before work, so interrupted requests recover on a new worker session. Work/results commit atomically. No paid Actor POST is sent by this worker.
- **ingestion-worker:** scheduled processing of approved import batches; source locks prevent concurrent duplicate ingestion.
- **apify-monitor (optional Compose profile `apify`):** resumes existing known runs only, with durable retry scheduling. Never submits or retries an uncertain paid start.

All containers use no-new-privileges, dropped capabilities and read-only root filesystems. A shared private `exports` volume is writable only by the application-worker and read-only in the dashboard. Export downloads expire after seven days and worker cleanup removes expired artifacts. Back up private storage according to the applicable retention terms. No local PostgreSQL service is included in this stack.

The optional systemd `veriflow-application-worker.service` supports existing Linux deployments. Set VERIFLOW_ARTIFACT_DIR consistently for dashboard/worker to `/var/lib/veriflow/exports`; the worker's StateDirectory creates writable private application storage under the hardened service settings. Existing worker/monitor/dashboard units remain available.

## Deployment acceptance

1. Review/apply only the three pending migrations listed in pending-migration-review.md. Preserve existing data, RLS, grants and credentials.
2. On the chosen host, run `python -m veriflow check-database` with the existing application-role connection and verified TLS. Require healthy=true, 42 registry sources and all required tables/columns. No new live database probe is made here.
3. Verify anonymous HTTP access is denied, authenticated pages load, CSRF-less writes fail, export storage is persistent/private and restarts preserve jobs.
4. Confirm paid policy/runtime switches remain false. No sources should be enabled just because the stack starts.

The application is packaged and locally exercised, not deployed or live-collection validated. The $10 reported account balance is not a hosting budget or spending authorization.
