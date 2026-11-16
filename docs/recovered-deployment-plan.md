# Actual recovered application: deployment review

Date: 2026-11-16. This supersedes prior assessments whose blocker was missing
Replit source. **The application source has now been recovered and preserved.**

## Recovery and provenance

Archive: `veriflow-complete-source-20261115-172244.zip`.
SHA256: `5f003483ac8433b763c10dbb537cdc979e7f8ba85395a0effaf09ad0b1424b63`.
All 277 entries in SOURCE-MANIFEST.json match their file hashes; the manifest
itself is the 278th file. There are no unsafe paths, symlink members or duplicate
archive names. Source was inspected before testing, without running startup,
post-merge, seeding or migration commands.

An unchanged, byte-matching snapshot is backed up in the existing GitHub repo on
`backup/replit-20261115-172244`, commit
`06f8a4df9cf92df25649fc94fac5153d2c71e91a`. It has its own root history so it does
not mix or overwrite the two different application trees. Draft PR #1, Codex's
feature branch and the isolated Mangrove integration branch remain intact.

The archive has no production secret environment file, provider token or private
key found by the performed checks. Credential-looking URLs are documentation
placeholders or local synthetic test values; no configured credential values
matched. The included Supabase CA is public certificate material, not a key.
This is a source backup, not a backup or verification of live database records.

At matching paths, comparison with each prior Codex branch found 20 identical and
24 changed files; 234 recovered files are absent at those same paths in the old
branches. Some documentation moved under docs/veriflow/. The old feature branch
has 52 paths absent from the archive; the old integration branch has 60. Do not
overlay either older tree or its migrations onto this application.

## What this archive actually runs

- `.replit` starts the existing Python worker with `python -m veriflow worker`
  and the existing private Python dashboard with `python -m veriflow admin`.
  The other React/Express workspace artifacts are preserved, but are not the
  application configured as the working private Preview. Do not deploy the mockup
  frontend instead of the functioning Python dashboard.
- `veriflow/strategy.py` and `jobs.py` preserve Breadth First as default, target
  five total unique evidence reviews per canonical product, prioritize products
  with fewer reviews, then poorer category coverage. Five is a prospective target,
  not a historical storage/deletion limit. No default was changed in recovery.
- The worker handles validated queued imports, collection-job pages, and bounded
  free-batch tasks. It resumes existing Supabase cursors, counters and deadlines;
  no batch activation is required to resume a still-active authorized task. That
  also means starting it can immediately perform real collection, so it stays off
  during this preparation.
- Mangrove is already integrated into the existing authorized-API worker. Reuse
  this implementation, not the earlier isolated patch or a second queue. Its
  source definition and classification migration keep it disabled and pending
  authorization. Google Play and App Store Connect have separate official API
  adapters requiring existing publisher credentials and scoped permissions.
- The seven product corrections are present in
  `20261115190000_mangrove_and_product_classifications.sql` and documented with
  official product references: AnkiDroid, Euro Truck Simulator 2, KeePassXC,
  LibraryThing, Parabola GNU/Linux-libre, PeerTube and SecureDrop. This review
  confirms source inclusion, not that it independently applied or verified their
  current live database associations. No classification SQL was executed.
- The existing Basic administrator authentication, CSRF checks and five export
  formats remain. This recovered export code renders private downloads in memory;
  it does not require Codex's different shared export volume/admin-job system.
  Its 20 MB export ceiling still needs consideration on a serverless response
  path; do not reduce it silently or claim all exports are platform-tested.

## Offline verification

The recovered suite discovered **144 tests: 102 passed and 42 database-dependent
tests were skipped**. Environment variables were cleared; actual network socket
connections and psycopg.connect were denied by the harness. No source data was
retrieved or database modified. The passing tests cover existing Breadth First
selection, worker fixtures, Mangrove/API routing, licensing, exports, configuration
and source safeguards. These are not a new live ingestion or deployed-browser
acceptance test.

The original snapshot has one existing whitespace warning (an extra blank line
at the end of lib/api-spec/openapi.yaml); it was preserved rather than altering
the verified source. Preparation changes are separate from that snapshot.

## Vercel decision for these exact methods

**NO-GO for the full current production workload on $0 Hobby under the published
rules. No Vercel deployment was created or activated.**

The [Vercel AUP section 2][aup] prohibits: "Scrape, proxy, act as a VPN, or host
media for hot-linking;". Permission from a source is separate from permission to
perform that activity on a host.

| Actual adapter | What it does | Hosting/authorization consequence |
| --- | --- | --- |
| lib.reviews + generic permitted crawler | Fetches and extracts public HTML, with robots/license safeguards | Conflicts with the host's published scraping prohibition absent an applicable Vercel exception. The current worker invokes the bounded lib.reviews path on every iteration; merely selecting an API source elsewhere is not an API-only host restriction. |
| Mangrove | Fixed documented JSON API, source/product/grant checks, CC-BY-4.0-only content and original attribution | Ordinary official API consumption is different from HTML scraping. No explicit Vercel clarification approving this bulk-review workload was found. Source availability or a passing fixture is not a live product-scope approval. |
| Google Play Android Publisher | androidpublisher.googleapis.com reviews for apps owned/managed by an authorized publisher | Not a general public-software review feed. Requires existing eligible credentials, exact app mapping, permissions and a new approved scope. The ZIP contains adapter code, not proof of that account access. |
| Apple App Store Connect | api.appstoreconnect.apple.com customerReviews for apps under authorized account access | Same ownership/access distinction; not unrestricted arbitrary-app collection. No new publisher account, subscription or credential is proposed. |
| Apify / Composio | Optional provider code remains in the archive | No paid execution or new collection scope is enabled. Neither is a policy workaround for the HTML method. |

Additionally, [Vercel's commercial-use guidelines][fair-use] restrict Hobby to
non-commercial personal use and define financial-gain deployments broadly.
The recovered product-coverage documentation expressly describes the future
software-review/affiliate business purpose. A private dashboard does not establish
Hobby eligibility. Even an API-only variant is not cleared for this purpose
without Vercel's applicable clarification. No support message was sent on the
user's behalf and no plan upgrade or trial was started.

### Runtime support is real, but does not override those policy gates

Vercel now supports [continuous Daemons][daemons] in public beta, including Hobby.
It is incorrect to say it cannot run any persistent Python worker. However,
[Hobby limits][daemon-limits] include 5 Active CPU-hours and 420 GB-hours of
provisioned memory per month, with 1 GiB minimum / 2 GiB default instances.
One continuous 1 GiB worker reaches that memory quota in roughly 17.5 days;
default 2 GiB in 8.75 days. Other use/CPU can stop it earlier. Daemons cannot serve
the dashboard's inbound HTTP themselves.

[Python Functions][python] could serve a compatible HTTP app; Hobby function
duration is [at most 300 seconds][functions]. The existing indefinite worker
cannot simply be its handler. A bounded one-page invocation could be scheduled
using the new [Schedules beta][schedules] (Hobby at most every 15 minutes, 15-minute
jitter and 5,000 runs per billing period), if policy and authorization were first
cleared. The old daily-only Cron rule is not the limit of all current scheduling.

Those are conditional technical paths, not a prepared or approved API-only
deployment. Moving the exact stdlib dashboard to a supported HTTP/container
entrypoint and splitting/gating the worker would need additional runtime-specific
work. That work is not justified while host/plan eligibility is unresolved, and
must not silently remove working lib.reviews coverage or renew old batches.

## Minimal portable preparation, using the recovered app unchanged

Branch `prep/replit-portable-deployment` starts from the immutable backup above.
The only additions are deployment packaging, this review and recovery metadata,
plus secret/cache exclusions. No application Python, UI, dependency manifest,
credential, source registry, migration or collection strategy was replaced.
The original SOURCE-MANIFEST.json deliberately remains a record of the immutable
backup snapshot; added preparation files and the documented .gitignore exclusions
are not represented as original ZIP contents.

- `deploy/portable/Dockerfile` packages the current Python app. It uses the same
  two pinned core dependencies from the recovered pyproject.toml. It does not run
  Node builds, Replit scripts, migrations, activation commands or a worker during
  build. Default container command is `--help`, which does not connect to data.
- `deploy/portable/compose.yaml` reuses the existing `admin` and `worker` commands.
  The dashboard binds to loopback for an HTTPS reverse proxy. The worker is in
  the opt-in `collection-approved` profile; a normal dashboard start does not
  start collection. Do not invoke that profile until cutover and collection have
  been approved. No service was actually started during preparation.
- Existing source/vendor grants and historical checkpoints stay in the existing
  Supabase project, using the dedicated veriflow_app login and verify-full TLS.
  Native server-side configuration must supply the existing secret values; they
  were correctly excluded from the source archive. No password memory, reset,
  rotation or credential disclosure in chat is required.
- The included CA's container path is configured explicitly. Do not reuse the
  stale Replit attached_assets filesystem path on another host. This changes a
  certificate file location, not the CA, password or permissions.
- Do not run `scripts/post-merge.sh` or a generic pnpm build/deploy pipeline during
  restoration: the archived post-merge script includes a database push command.
  The portable recipe copies only the actual Python runtime, its registry data
  and public CA. Mockups, JS dependencies, secrets and migration scripts are not
  part of the image.

The packaging is a deployment preparation artifact, not a working host or a
verified image build. Compose syntax/core-dependency alignment are checked
separately; no cloud account, image registry or runtime is provisioned by them.
Compose validation confirmed that the default service selection contains only
the dashboard, with the worker added only by explicit opt-in. The CLI help path
also ran without starting a worker. No container or HTTP server was started.

## Nearest viable genuinely free runtime

An [Oracle Cloud Always Free Linux VM][oracle-free] is the closest fit found for
running both existing processes without a serverless rewrite. Its Always Free
allocation is distinct from the expiring trial credits. It can keep processes
running independently of the phone and Codex and supports normal outbound TCP
for the existing Supabase session pooler. Connectivity, exact free resource
eligibility and source/provider permission still require validation before go-live.

Use only Always Free eligible compute, disk and networking within their limits;
do not accept a paid replacement shape or upgrade. Regional capacity is not
guaranteed, card/identity verification can involve a temporary authorization hold,
and idle instances may be reclaimed. See [Oracle's free-tier FAQ][oracle-faq].
This is a real $0-capable option, not a promise that a VM is reserved or that uptime
is guaranteed. No Oracle account or resource was created.

[Render Free][render-free] is not an equivalent persistent-worker host: free web
services sleep after 15 minutes without inbound traffic and workers are not a
free service type. No keepalive workaround or paid plan is proposed. If an Always
Free VM cannot be obtained, this review does not establish another guaranteed $0
always-running managed host. The portable app can later move to Render without
rebuilding the dashboard, collector or database.

## Controlled deployment and one-worker cutover plan

1. Select an actually available $0 eligible runtime and approve the final host
   plan. Configure the existing secrets directly in its protected server settings,
   not source control. Add no authentication system and preserve the current one.
2. Validate the package locally/with fixtures, then test dashboard-only access and
   a read-only application-role/TLS database check from that chosen host. Keep
   the worker off. No repeat Codex-to-Supabase probes are part of this preparation.
3. Compare the actual current database capabilities to this recovered revision.
   Do not replay its SQL or Codex's overlapping SQL. A source-archive statement
   that migrations were applied is not sufficient authority to apply them again.
4. Confirm the old production worker and any scheduled triggers are stopped;
   drain/terminate them before starting a replacement. Credits being exhausted
   does not itself prove every old process is stopped. Preserve jobs, counters,
   reviews, grants and expiry/deadline values; do not rearm an expired batch.
5. Run exactly one replacement worker process/replica. Keep previews from the
   production queue. The bounded batch already has a session advisory lock;
   ordinary job items have a two-minute lease and row claims. Generic completion
   updates are not fenced by an owner token, so those leases alone are not proof
   of safety for overlapping old/new workers after lease expiry. Use a stopped-old,
   single-new-process cutover; do not autoscale or run competing schedulers. Verify
   restart/deduplication/checkpoint behavior before any future concurrency change.
6. Obtain a new exact collection-scope approval before enabling real source
   retrieval/resuming active collection. Include distinct products, category
   diversity, eligible source/product mappings, request/page/new-review limits,
   duration, retention/license conditions and a $0 paid-service budget. The old
   declined two-product scope is not revived by a source recovery or deployment.
7. Only after approval, enable that one worker and inspect retrieved/inserted/
   duplicate/error counts plus one attributed private export. Rollback means stop
   the new worker first and keep the database intact; never start two versions to
   compare their output against production.

No production readiness, new live review count, independent collection, image
build success, deployment or approved collection scope is claimed by this plan.

[aup]: https://vercel.com/legal/acceptable-use-policy
[fair-use]: https://vercel.com/docs/limits/fair-use-guidelines.md
[daemons]: https://vercel.com/docs/daemons
[daemon-limits]: https://vercel.com/docs/daemons/limits
[python]: https://vercel.com/docs/functions/runtimes/python
[functions]: https://vercel.com/docs/functions/limitations
[schedules]: https://vercel.com/docs/schedules/limits
[oracle-free]: https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm
[oracle-faq]: https://www.oracle.com/cloud/free/faq/
[render-free]: https://render.com/docs/free
