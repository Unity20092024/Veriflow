# Veriflow source backup and restore

## What this ZIP contains

The current Replit application source, including the Python collectors, bounded
free batch, persistent worker, private dashboard, exports, source registry,
Mangrove API adapter, Breadth First product coverage, category corrections,
Supabase migrations, tests, JavaScript workspace, dependency manifests, existing
deployment examples and operational documentation. The runtime source catalog,
capability audit, and collection policy configuration are included. The
main Preview routes to the existing Python dashboard; its administrator
authentication remains enforced. SOURCE-MANIFEST.json records SHA-256 digests
for source files. The public Supabase CA certificate is included when available;
it is not a password or private key.

Excluded: real secrets, runtime environment files, private reset workspaces,
uploaded documents, database/review exports, caches, dependencies and virtual
environments. This is a **source backup**, not a database dump. Existing review
records and live batch checkpoints remain in the existing Supabase project.
Do not add private review exports or runtime secrets to the public GitHub repo.

## Download on Android

Use the ZIP download attachment in the chat. Save it to Downloads or your chosen
private storage. Android's Files app can open or extract ZIP archives. Keep a
separate secure copy of your working secrets; they are deliberately not in this ZIP.

## Restore the same application

1. Extract the `veriflow/` directory into the destination source workspace.
2. Use Python 3.12 or later. The core Python dependencies are in `pyproject.toml`;
   `requirements-veriflow.txt` is the complete existing Python dependency list.
   `package.json`, `pnpm-workspace.yaml` and `pnpm-lock.yaml` retain the JavaScript
   workspace dependency definitions.
3. Configure the **existing** Supabase project and existing working credentials
   through the destination runtime's secure environment facility. Preserve
   `SUPABASE_DATABASE_URL`, `VERIFLOW_APP_PASSWORD`, `SUPABASE_SSL_ROOT_CERT`,
   `ADMIN_USERNAME`, `ADMIN_PASSWORD` and any other working integration credentials.
   Set the certificate path to the restored public CA file if its location changed.
   Continue to require `sslmode=verify-full`. Never reset passwords just to restore.
4. Do not create a new database. Do not replay migrations already applied to the
   existing project. The product-coverage and Mangrove/classification migrations
   have already been applied in Supabase. Mangrove remains disabled and pending
   authorization, with no product mappings or collection jobs created. See
   `approved-free-batch.md` for the original approval and upstream DDL overlap.
5. From the source root, start:

   ```sh
   python -m veriflow worker
   python -m veriflow admin --host 127.0.0.1 --port 8099
   ```

   Run these as separate managed processes. Keep the dashboard private; do not
   expose it without the existing administrator authentication and encrypted
   transport. `deploy/` contains existing example service definitions; adapt the
   Python executable and source path to the destination runtime.
6. The worker resumes the same Supabase checkpoints. Its original counters and
   deadline remain unchanged. If the original batch is completed, blocked or
   expired, a restart must not renew it. Paid collection remains disabled.

Generate another versioned source snapshot with:

```sh
PYTHONPATH=. python scripts/export_veriflow_source.py
```

Export permitted real review data separately, never into GitHub source history:

```sh
PYTHONPATH=. python scripts/export_collected_reviews.py
```

## GitHub preservation

When GitHub write authorization is available, preserve the Replit snapshot on a
**separate branch** such as `replit/bounded-free-collection`. Do not force-push,
replace or merge over Codex's development branch without reviewing the changes.
The Replit and upstream administration migrations have overlapping category DDL;
reconcile that overlap before any merge or deployment. Until a GitHub push is
actually confirmed, this downloadable ZIP is the immediate portable backup.
