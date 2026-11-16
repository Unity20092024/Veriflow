# Veriflow: Android migration without changing credentials

## First: preserve what works

Do not reset, rotate, delete, overwrite or recreate any working credentials.
Keep the existing Replit project and your signed-in owner session until your
credential backup has been saved and checked privately. Do not stop the current
worker just to download backups. Source and review exports do not move or remove
anything from Supabase.

**A source ZIP is not a credential backup.** The downloadable source ZIP and
review-data ZIP deliberately contain no configured passwords or API tokens.
GitHub does not preserve Replit Secrets. Do not put real credentials in either ZIP,
a Git commit, an issue, a screenshot, an email, or Agent chat.

## Verified storage inventory

The Secrets control plane reported these nine names as present, and they were
also present by name in the development runtime. No values were displayed.
This verifies presence, not every key's validity, production-secret copies,
or a separately recoverable backup outside this Replit project.

| Name | Needed at destination? | Treatment |
| --- | --- | --- |
| SUPABASE_DATABASE_URL | Yes | Copy the existing value privately; do not rebuild it from memory. |
| VERIFLOW_APP_PASSWORD | Yes | Copy the existing working application-role password privately. |
| ADMIN_USERNAME | Yes | Reuse the existing private dashboard administrator name. |
| ADMIN_PASSWORD | Yes | Reuse the existing private dashboard password. |
| SESSION_SECRET | Preserve | Configured; not referenced by the current Python Basic-auth dashboard. Preserve for compatibility, not as a replacement for the administrator password. |
| APIFY_API_KEY | Optional integration | Preserve securely, but do not enable paid execution. Not needed for the free lib.reviews collector. |
| COMPOSIO_API_KEY | Optional integration | Preserve securely; not needed for the free collector. |
| VERIFLOW_RESET_POSTGRES_PASSWORD | No, not for normal deployment | Privileged temporary administrator/reset credential. Keep unchanged in the current project; if backing it up, store separately in your private vault, not the normal deployed application's environment. |
| VERIFLOW_RESET_CONFIRM | No, not for normal deployment | Temporary reset-helper confirmation. Preserve unchanged; do not run the reset helper. |

These two ordinary environment variables were also configured:

| Name | Needed at destination? | Treatment |
| --- | --- | --- |
| SUPABASE_PROJECT_REF | Yes, preserve | Same existing Supabase project; not a password. |
| SUPABASE_SSL_ROOT_CERT | Yes | Certificate-file path, not a password. Restore the public CA certificate and adjust only the destination path if necessary. |

The source ZIP includes the public CA certificate under
`veriflow/certificates/supabase-ca.crt`. Never replace `verify-full` with a weaker
SSL mode. Keep the current source environment and certificate path unchanged.

No private environment-file override (`VERIFLOW_ENV_FILE`) was configured.
`APIFY_TOKEN` was not configured; the application already supports the existing
`APIFY_API_KEY` alternative, so no replacement token is requested.
`COMPOSIO_USER_ID`, `APIFY_MAX_RECORDS`, `APIFY_MAX_RUN_USD`,
`APIFY_ROLLING_24H_BUDGET_USD`, and `APIFY_PAID_RUNS_ENABLED` were not configured
as environment variables. Do not enable paid services during migration.

The separate names-only environment inventory lists every variable name exposed
to the inspected development process, including automatically injected platform
variables. It contains no values. Entries such as `DATABASE_URL`, `PGPASSWORD`,
`PGHOST`, `REPLIT_*`, Git proxy tokens, `PATH`, and package-manager configuration
are not evidence of user-managed Secrets. Do not copy runtime-injected platform
credentials to another host. Veriflow uses `SUPABASE_DATABASE_URL` in preference
to `DATABASE_URL` and validates its existing Supabase target.

## Retrieve your existing values privately on Android

1. Stay signed in to the Replit account that owns this project.
2. Open the project in the editor. Open the tools list/search and select
   **Secrets**. Depending on the Android app/editor version, the tools control
   may have a different location. Search for “Secrets” rather than creating
   another key.
3. Find an existing key by its exact name above. Use the **eye icon** to reveal
   its existing value privately. If a copy control is offered, use it; otherwise
   copy the revealed value yourself.
4. Paste it directly into a trusted password manager's encrypted secure note or
   credential field. Label it with this application and the exact variable name.
   Do not paste into Agent chat, a source file, a terminal command, or a shared
   note. Avoid screenshots and screen sharing while values are visible.
5. Repeat for the necessary application credentials and the optional keys you
   want to retain. Keep privileged temporary reset credentials in a separate
   vault entry, not alongside the normal deployment environment.
6. Privately confirm that the saved vault entries can be reopened. Clear the
   clipboard afterward; avoid clipboard history/sync or untrusted clipboard apps.
   Do not change or save over any key in the original Secrets tool.

If the mobile app does not expose the tool, try the same project in your Android
browser; the browser's **Desktop site** option may make the editor controls easier
to reach. This is a navigation workaround, not a guarantee about every mobile UI.
Never use a third-party “secret recovery” website.

Replit also documents **Edit as .env** and **Edit as JSON**, which can reveal
multiple values. These are editing interfaces, not a secure downloaded backup.
The single-key reveal/copy approach is safer here because it avoids accidentally
overwriting other working settings. Do not save edits in the original project.
There is no documented direct “export Secrets to file” button.

## Transfer existing values, not new accounts or passwords

For another Replit application, use the destination project's Secrets tool to
paste the existing values from your vault. Replit also documents Account Secrets
for sharing credentials between apps, but do not move or relink the current
project's working configuration as part of this backup.

For another host or a personal machine, use that runtime's protected secret or
environment configuration interface. Keep credentials out of source control and
public files. Do not transmit a plaintext credential file through chat or email.
If you choose an encrypted password-manager export, make it yourself in that
manager and keep its encryption credentials separate.

Development presence does not verify published/deployment-secret copies.
If publishing later, inspect the destination's deployment Secrets separately;
do not assume a ZIP import or GitHub push configured them. No publishing or hosting
purchase is required for this backup.

**Copy both `SUPABASE_DATABASE_URL` and `VERIFLOW_APP_PASSWORD`.** The working
Python connection reads the URL settings and supplies the separate application
password in memory. Do not assume a password embedded in an older saved URL is
the current working role password. Preserving both values avoids another reset.

## Restore the application without touching the working source runtime

1. Download the source ZIP, the separate review-data ZIP, this guide, and the
   names-only inventory to Android. Keep review exports in private storage.
2. Extract the source ZIP on the destination. It contains collectors, the worker,
   private dashboard, exports, database migrations, dependency files, tests,
   deployment examples, and restore documentation.
3. Install the documented Python dependencies on the destination. Use the
   JavaScript dependency manifests if you also run the existing web workspace.
4. Securely configure the same database/application credentials listed above.
   Point the destination certificate variable at the restored public CA file.
5. Reuse the same existing Supabase database, schema, application account and
   records. Do not create another database. Do not replay migrations already
   applied to it. Do not alter roles, RLS, permissions, or passwords.
6. Keep the dashboard private and authenticated. Existing command:
   `python -m veriflow admin --host 127.0.0.1 --port 8099`.
7. Before moving worker ownership, verify the destination with a read-only check.
   Do not turn migration into repeated TLS tests or password resets. The current
   worker stays running until you explicitly approve any actual cutover.
8. The worker command is `python -m veriflow worker`. The batch counters,
   checkpoints and original expiry live in Supabase. Do not recreate or reactivate
   a completed/expired batch to get another collection allowance. Keep paid
   execution disabled and do not authorize new collection during migration.

The exported review data includes CSV, JSON, JSONL and Excel plus attribution,
license links, original URLs, modification notices and a verification report.
It is a separate backup, not a replacement database and not something to commit
to the public GitHub repository.

## If a value cannot be revealed or transferred

- This Agent can verify Secret presence but does not receive Secret values from
  the Secrets-inventory tool. It cannot provide a password through chat.
- Make sure you are the owner, in the correct project and Secrets scope. A
  deployment-only or account-level secret may require the matching owner UI.
- If your permitted UI offers no reveal/copy option, the existing value has not
  been backed up. Record the exact missing key name and preserve the original
  running project. Do not assume source ZIPs, GitHub, or a new project recover it.
- Some connector/platform-injected credentials are managed rather than
  user-exportable. Their names in the process environment do not make them
  transferable application Secrets. They are not required for normal Supabase
  review collection.
- PostgreSQL stores password verifiers, not a readable copy of the role password.
  Database access alone is not a way to recover the original plaintext password.
- If the owner interface still cannot reveal a required value, that is an
  unresolved portability blocker. Do not rotate or replace it without your
  separate explicit approval.

## Official Replit documentation checked

- [Secrets: storage, reveal, bulk edit and reuse](https://docs.replit.com/core-concepts/project-editor/app-setup/secrets)
- [Replit mobile app](https://docs.replit.com/features/platforms/mobile-app)
- [Projects and files](https://docs.replit.com/help/projects-and-files)

Replit documents encryption at rest and in transit for Secrets. This does not
mean you have an independent backup or that Secrets are included in source
downloads. This guide intentionally contains no configured secret values.
