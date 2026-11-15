# Review of the two pending migrations

Review date: 2026-11-15. Target only the existing Veriflow project `qrejfpeclncrevmepgzx`. **Review completed; no live migration applied.**

Supabase's migration history lists the five earlier versions through `20261114133207`. Both versions below are pending. Live read-only preflight found 42 disabled sources, zero products, reviews and Apify jobs, zero normalized product conflicts and RLS enabled. Security advisor returned no findings. These checks do not replace a final preflight immediately before deployment.

## 20261114230002_apify_poll_schedule.sql

Adds `next_poll_at`, nonnegative `poll_failures` and a partial due-running-job index to the existing private Apify jobs table. It does not start jobs, enable collection, change roles/passwords, alter RLS policies or expose a schema. The currently empty live jobs table makes backfill/index work small. PostgreSQL still needs a table lock for ALTER TABLE; apply with a short lock timeout in a maintenance transaction, not a web request.

## 20261115003835_private_administration_jobs.sql

Adds categories, product-category links, private admin settings/jobs, a product website field, normalized product identity index and supporting indexes. New tables have RLS enabled and explicit runtime-role policies/grants; PUBLIC/anon/authenticated permissions are revoked. Existing table policies/role flags remain unchanged. There are no SECURITY DEFINER functions, public views/API grants, credential operations, seed operations or destructive product merges.

The normalized product index can reject pre-existing case/whitespace duplicates. Live preflight currently reports zero conflicts, but a concurrent write could change that. Reconcile any conflict explicitly before application. Never remove product rows or weaken the index just to make deployment succeed.

## Upgrade evidence

Two isolated PostgreSQL upgrade tests applied these exact pending SQL files on top of the prior five migrations with existing product data. They verified retained data, unchanged existing RLS policies and denied public reads across all private tables. A separate conflict test deliberately inserted normalized duplicate products: applying the administration migration failed transactionally and rolled back partial tables/columns without deleting either product.

The fixture harness uses separate disposable databases and reuses their cluster-wide test roles; it does not run against Supabase. The real fetched review lives in a separate local validation database and was preserved throughout these tests.

## Safe application sequence after review

1. Use the existing project's authorized migration connection; never the runtime application's ordinary job connection. Do not create another project or rotate credentials.
2. Run the read-only `scripts/preflight_pending_migrations.sql`; confirm expected project selection in the management client, no normalized product conflicts, current table privacy and expected role flags.
3. Apply **only** these two pending migrations in timestamp order, transactionally, with an explicit lock timeout (for example 5 seconds) and bounded statement timeout. A timeout/conflict should roll back; investigate rather than disabling constraints or replaying old migrations. Do not add timeout settings globally.
4. Verify migration history, all 17 expected tables/private policies, application-role read access, original source IDs and no public Data API exposure. Run the application readiness command on the chosen reachable runtime.
5. Deploy the updated application and workers. Source activation is separate: migrations themselves register/enable no sources. The optional free connector is installed through its explicit reviewed UI action.

Application health expects the new tables and monitor columns. Do not deploy this revision against the old schema or represent management API queries as an application login test. No broad grants, anonymous access, owner runtime login or TLS downgrade is part of this plan.
