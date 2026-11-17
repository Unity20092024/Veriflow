# Northflank Android setup: recovered Veriflow

For the subsequent collection-controls patch and safe worker cutover, use
[the collection operations report](collection-operations-go-no-go.md). Its branch
and checks supersede the historical preparation settings below. Updating both
dashboard and worker code is required for Pause / Stop / Resume.

Prepared 2026-11-16. **Settings only: no service, image deployment, worker or
collection was started.** This branch derives from the verified recovered Replit
source, not the older Codex implementation. No application code changed.

## Stop before deployment

Northflank's **Create service** action on a Combined service starts a build and
normally deploys it. Saving a new command on a running service can restart it.
Do not click Create, Deploy, Resume, Restart or Run while reviewing this setup.
Do not create first and pause afterward: the worker could already have fetched a
review by then. If the UI cannot save a non-running draft, leave these as settings
to enter after deployment approval.

Keep CI and CD off, and instances at zero/paused where the UI offers that choice.
The final intended instance counts below are for a later approved launch, not
instructions to start them now. Creating a Sandbox account or adding a card for
verification does not authorize paid resources or collection.

## Shared build settings

Use the same settings for both services. On Android Chrome, Desktop site may
make Northflank's configuration tabs easier to reach.

| Northflank field | Select/enter |
| --- | --- |
| Cloud | Northflank Cloud; not BYOC |
| Region | US Central (Council Bluffs); internal region identifier us-central |
| Billing plan | Free Developer Sandbox |
| Project | Select the existing Veriflow project in that region; intended name veriflow |
| Repository provider | GitHub, connected Unity20092024 account |
| Repository | Unity20092024/Veriflow |
| Branch | prep/northflank-sandbox |
| Build type | Dockerfile, not Buildpack / Node / pnpm |
| Build context / root | Repository root, `.` (or `/` if the UI denotes root that way) |
| Dockerfile path | deploy/portable/Dockerfile |
| Build arguments | None; never add credentials here |
| Build command | No custom command; use the Dockerfile |
| Pre-deploy/release/migration commands | None |
| Compute | nf-compute-20: 0.2 vCPU / 512 MiB per service, only if included as $0 in this Sandbox |
| Instances | Zero/paused during preparation; one per service only after approval |
| Autoscaling, cron jobs, preview workers | Off / none |
| Automatic CI / CD | Off for preparation; keep worker CD off for controlled single-worker updates |
| Databases/addons, persistent volumes, dedicated egress IP | None; retain the existing Supabase project |

Two **Combined** services are the simplest identical source configuration and
fit the advertised two-service Sandbox count. Each builds the same small Python
recipe; their runtime commands differ. This avoids assuming the UI can reuse a
Combined service's build as another service's internal image source. Once a build
is available, reuse of that exact image is optional, not necessary to prepare.

The actual account quote must remain **$0**. Do not accept a paid compute upgrade,
Pay-as-you-go, BYOC infrastructure charges, a new database, paid storage or static
egress. Public pricing advertises up to $20/month of resources; that is not proof
of an unlimited allowance or a hard invoice cap. Inspect the Sandbox allocation
and remaining usage before activation. This guide does not claim account access
or confirm your team's current consumption.

## Dashboard service

| Field | Value for the eventual approved deployment |
| --- | --- |
| Service name | veriflow-dashboard |
| Service type | Combined |
| Docker runtime mode / CMD override | Custom command |
| Custom command | `admin --host 0.0.0.0 --port 8080` |
| Entrypoint | Leave the image default unchanged: python -m veriflow |
| Working directory | Leave image default: /app |
| Public port | 8080, HTTP, Public; name http |
| URL | Use the generated Northflank HTTPS code.run URL; no custom domain purchase |
| Initial intended replicas after approval | 1 |
| Readiness health check | TCP, port 8080; initial delay 10s, period 10s, timeout 3s, failure threshold 3, success threshold 1 |

Do not configure an anonymous HTTP GET `/` health check: the preserved dashboard
correctly returns **401 without the existing administrator credentials**. TCP
readiness verifies the listening process, not database health. An authenticated
read-only dashboard check verifies actual database access later. No new anonymous
route, authentication system, user or password is needed.

Northflank terminates public HTTPS and routes it to container HTTP on 8080. Keep
the existing Basic authentication and CSRF checks. Do not put secrets into the
URL, route query, health-check headers, build arguments or screenshots.

## Worker service

| Field | Value for the eventual approved deployment |
| --- | --- |
| Service name | veriflow-worker |
| Service type | Combined; continuous service, not a Job or scheduled task |
| Docker runtime mode / CMD override | Custom command |
| Custom command | `worker` — do not save/run this on an active service before approval |
| Entrypoint | Leave image default unchanged: python -m veriflow |
| Working directory | Leave image default: /app |
| Ports | None. Remove any automatically detected public 8080 port inherited from the shared image |
| HTTP/TCP health check | None; this process does not listen on a port |
| Current preparation state | Not created/deployed, or zero instances/paused if the UI supports a genuinely non-running draft |
| Replicas after approved cutover | Exactly 1 |
| Automatic CD / autoscaling | Off |

**Do not enter `python -m veriflow worker` as the Custom command.** Northflank
concatenates a preserved Docker ENTRYPOINT with the overridden CMD. The image
already supplies `python -m veriflow`; entering it twice produces invalid CLI
arguments. The same applies to the dashboard command. Check the parsed argument
preview if shown; no shell or quoted whole-command wrapper is necessary.

The image's unmodified default command is `--help`. It neither connects to the
database nor starts collection, but it exits and is not a placeholder healthy
worker. Keep the real worker undeployed/paused, rather than repeatedly restarting
a help-only container.

## Existing credentials: runtime only

Use Northflank's **runtime variables / secret groups**, not build arguments.
Transfer existing working values directly from your secure store; do not invent
or reset any password and do not paste credentials into chat or GitHub.

| Variable | Service | Value/source |
| --- | --- | --- |
| SUPABASE_DATABASE_URL | Both | Existing working application-role session URL; preserve its password/value |
| VERIFLOW_APP_PASSWORD | Both, if already configured separately | Existing dedicated-role password override; preserve it if the working app relies on it |
| ADMIN_USERNAME | Dashboard only | Existing username |
| ADMIN_PASSWORD | Dashboard only | Existing administrator password; the preserved app requires 24+ characters |
| SUPABASE_PROJECT_REF | Both | qrejfpeclncrevmepgzx |
| SUPABASE_SSL_ROOT_CERT | Both | /app/certificates/supabase-ca.crt |
| APIFY_PAID_RUNS_ENABLED | Both | false |
| APIFY_MAX_RUN_USD | Both | 0 |
| APIFY_ROLLING_24H_BUDGET_USD | Both | 0 |

If the working app used DATABASE_URL rather than SUPABASE_DATABASE_URL, transfer
that exact existing app URL into SUPABASE_DATABASE_URL; the application prioritizes
it. Do not use a Northflank addon/managed DATABASE_URL. Do not copy an obsolete
VERIFLOW_ENV_FILE path or the Replit attached_assets CA path into the container.
The public CA is already packaged at the path above. No API tokens are required
to start this dashboard, and Mangrove remains disabled/pending by default.

The app accepts only the existing project's app login and postgres database with
verify-full TLS. The official session-pooler target is
aws-1-us-west-2.pooler.supabase.com, port 5432, username
veriflow_app.qrejfpeclncrevmepgzx. This is a target description, not a new connection
string or password. Do not change to transaction port 6543, use the owner login,
disable TLS, expose the private schema, or replay migrations.

## Verified locally / remaining checks

- Recovered snapshot: backup/replit-20261115-172244 at 06f8a4d, all original 277
  manifest hashes verified. Preparation ancestor: 11833ec. This branch adds
  Northflank instructions/reference settings only; the Dockerfile and Python app
  remain the recovered preparation version.
- The core dependency pins match the recovered pyproject.toml. PyPI metadata
  confirms all pinned releases exist, including an amd64 Linux Python 3.12
  psycopg-binary wheel. No Node build or optional Composio/AI SDK is required.
- An additional offline smoke check imported the worker, jobs, bounded collection,
  strategy, Mangrove, exports and dashboard while optional SDKs were unavailable.
  Breadth First remains default; Mangrove remains disabled by default.
- The original dashboard handler returned 401 without auth and 200 with synthetic
  existing-auth credentials plus a stubbed database. No HTTP server, real source
  request or actual database connection was started by that check.
- The packaged public CA parses and is valid through 2031-04-26. This does not
  claim a new live Supabase TLS/authentication check from Northflank.
- Earlier recovered-suite evidence is 102 passing offline tests / 42 skipped
  database-dependent tests. No database migration was run for this preparation.
- A full image build is still pending: this workspace has under 1 GB free with a
  copying VFS Docker storage driver; building multiple large layers risks filling
  the workspace containing retained validation data. No data/image/volume was
  deleted to force a build. Local recipe/Compose checks are not an image-build
  success claim. The first approved Northflank build must be checked before use.

## Approval boundary and launch order

For now, **review/fill settings and stop before Create/Deploy**. Do not assume the
default paused state or disabled CD is offered in every version of the creation
form. A single Create action can build and deploy immediately.

After separate deployment approval, start dashboard-only, verify HTTPS plus the
existing authenticated views and a read-only app-role/TLS connection from that
host. Keep the worker off. This does not require or authorize changing Supabase.

Before later worker activation: confirm the previous production worker/triggers
are stopped, preserve existing checkpoints/deadlines, obtain the new collection
scope approval and resolve any outstanding host/source permission conditions.
Then start exactly one worker. Do not activate a batch, seed sources or rearm an
expired job merely to test a deployment. The worker may immediately resume any
existing eligible job, so its startup itself requires the collection decision.

During worker updates, stop/drain its old instance before starting the new one.
One replica is not sufficient protection against overlapping rolling replacements:
Northflank normally waits for a new container before stopping the old one. The
existing ordinary job leases are not a distributed fencing mechanism. Keep CD
off and perform controlled stop-before-start updates; preserve the app's existing
claim/deduplication logic. Keep preview workers away from production secrets/jobs.

No Northflank account setting, service, credential, database or worker was
modified by preparing this guide. Draft PR #1 and existing source branches remain
untouched. No paid service or collection was activated.

## Northflank references checked

- [Build and deploy; creation and CI/CD behavior](https://northflank.com/docs/v1/application/getting-started/build-and-deploy-your-code)
- [Exact CMD/ENTRYPOINT override behavior](https://northflank.com/docs/v1/application/run/override-command-entrypoint)
- [Ports and generated HTTPS](https://northflank.com/docs/v1/application/network/configure-ports)
- [TCP readiness checks](https://northflank.com/docs/v1/application/observe/configure-health-checks)
- [Compute plan definitions](https://northflank.com/docs/v1/application/billing/resource-plans-and-quotas)
