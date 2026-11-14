# APIFY_TOKEN in the current Codex Cloud workspace

**Android without a terminal:** use the [mobile configuration alternative](apify-token-mobile.md). The terminal-only method below is unavailable in that interface; no current-workspace mobile binding is claimed.

The current running instance was checked directly. It reports **no bound secrets and no runtime-variable bindings**, and this chat exposes no environment-change tool. Saving an item in Personal Vault is not the same as attaching it to this machine. Publishing a reusable environment elsewhere does not retroactively configure this running instance.

The following workspace-local method is implemented and tested. It configures this machine directly; a separate chat or environment publication is not required for this method.

## 1. Open this Cloud workspace's terminal

Use a terminal attached to the running workspace containing `/workspace/Veriflow`. A terminal on your own laptop is a different filesystem. Run:

```sh
cd /workspace/Veriflow
.venv/bin/python -m veriflow configure-apify-token
```

At the `APIFY_TOKEN (hidden input):` prompt, enter/paste the existing token from your vault and press Enter. Input is not echoed. Do not put the token in chat, a command argument, an `export` command, a Git file or a screenshot. The command refuses non-interactive input and refuses any fallback to an echoed prompt.

The command writes `/workspace/.veriflow-secrets/runtime.env` with mode **0600** inside an owner-only **0700** directory, outside the repository. It atomically preserves the existing database and admin settings while updating only Apify configuration. It never prints the token or calls Apify. It records:

```text
APIFY_MAX_RUN_USD=1
APIFY_ROLLING_24H_BUDGET_USD=1
APIFY_MAX_RECORDS=20
APIFY_PAID_RUNS_ENABLED=false
```

This is an owner-only server configuration file, not a vault synchronization mechanism. It belongs to this running machine; new machines/deployments need their own secure binding. If the current UI does not provide a workspace terminal, use the environment's existing-secret binding controls when offered, selecting the saved Personal Vault entry for the environment variable `APIFY_TOKEN`. I cannot bind a vault entry through the tools exposed in this chat, and will not ask you to reveal it as a workaround.

## 2. Verify presence without revealing the value

```sh
VERIFLOW_ENV_FILE=/workspace/.veriflow-secrets/runtime.env .venv/bin/python -m veriflow apify-config
```

Expected safe output includes `apify_token_configured: true`, `max_total_usd: "1.00"`, `max_review_records: 20`, and `paid_runs_enabled: false`. Never use `cat`, `printenv`, or shell tracing to display the secret file/value.

## 3. Optional read-only authentication check

```sh
VERIFLOW_ENV_FILE=/workspace/.veriflow-secrets/runtime.env .venv/bin/python -m veriflow apify-check
```

This calls only the authenticated Apify account-read endpoint and reports success/failure without account details. It does not start an Actor. Continue running server commands with `VERIFLOW_ENV_FILE` pointing to the same file (or configure it through the process manager). Existing process environment values take precedence over file values; the non-secret `apify-config` command shows the effective configuration.

## Paid execution remains blocked

The first test is capped at **$1 total and 20 reserved review records across its jobs**; the total allowance does not renew after a day. Environment variables can lower the record cap, but cannot raise the approved ceiling. Unknown costs/starts remain reserved.

The versioned first-test policy and the runtime paid-run switch both remain disabled. An enabled, source-specific grant, confirmed text-storage rights, complete reviewed pricing and effective total-cost control are also required. An Actor's event-price limit alone is not proof that storage/export fees fit the $1 total budget. The recommended Cheerio Actor is pay per usage and is still rejected by the current PPE-only start policy. Adding the token never enables it automatically.

All development and tests continue with marked fixtures. No source has been activated, no real review imported and no paid Actor run started by this configuration work.

## Validation for this change

- All **82 tests passed**, including disposable PostgreSQL 17 integration tests for cumulative budget/record reservations, paid-run gates, authorization, fixture imports, deduplication, attribution persistence and private dashboard rendering. Dependency validation and `git diff --check` passed.
- Migration `20261114133207_pilot_limits_and_review_licenses.sql` was applied only to Supabase project `qrejfpeclncrevmepgzx`. The private license table has RLS enabled; anonymous and authenticated API roles have no SELECT permission. Supabase's security advisor returned no findings.
- The existing registry still has **42 sources, all disabled**. No production reviews, Actor jobs, authorizations or license records were created. Management API verification succeeded; the application's direct PostgreSQL connection/dashboard connection remains unverified because its network route is unresolved.
- Effective workspace configuration reports `$1.00`, `20`, paid execution disabled and **no APIFY_TOKEN configured**. No authenticated Apify check or live Actor run is claimed.
