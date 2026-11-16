# Configure APIFY_TOKEN from Android

## Current workspace limitation

The current Cloud workspace reports no bound secrets and exposes no vault-binding/change tool, browser handoff or mobile secret-entry surface. The environment skill documents a running-environment settings fallback in **Codex desktop**, not a verified Android path. The previous terminal command is not usable without an interactive terminal. Do not put the token in this conversation, an attachment, a repository file, an issue, an Actions input, or a command pasted into chat.

This change sets up a supported alternative in the **existing Unity20092024/Veriflow GitHub repository**: a repository Actions secret and a manual read-only verification workflow. No new account, project, conversation, database, public application or collection schedule is created. This alternative does **not** inject secrets into the current Codex machine. GitHub Actions and the current workspace are separate runtimes.

## Phone-only secret entry

1. Open [New Actions repository secret](https://github.com/Unity20092024/Veriflow/settings/secrets/actions/new) in your Android browser while signed into the GitHub account with repository administration rights. If the mobile layout hides settings, use the browser's **Desktop site** mode. The normal navigation is repository **Settings → Secrets and variables → Actions → New repository secret**.
2. Set **Name** to `APIFY_TOKEN`. Paste the token from your vault into GitHub's **Secret** field and tap **Add secret**. If an `APIFY_TOKEN` entry already exists, use its update control instead; do not create a differently named duplicate. Enter the key only in that native GitHub secret form, never in an Actions workflow input.
3. Return to this same conversation and say only that the GitHub secret has been saved. The key itself must never be sent here.

GitHub encrypts repository secrets and does not provide their plaintext through the repository UI/API. Secret storage is separate from Git source history. Because this repository is public, workflow status and safe summaries can be public; never print tokens or account/provider payloads. Repository secrets are available to authorized workflows, so repository administrators should review workflow changes before running them.

## Read-only verification

The existing repository's default branch is currently `feature/step-1-private-collection`, so the manual workflow is available without merging Draft PR #1. Open [Verify Apify credentials (read only)](https://github.com/Unity20092024/Veriflow/actions/workflows/apify-credentials.yml), tap **Run workflow**, select `feature/step-1-private-collection`, and run it. Other branch refs are skipped. No secret or account identifier is accepted as a workflow input.

The secret is attached only to the final check step, after dependency installation. The workflow:

- Runs the existing `apify-config` safe presence/limit summary and `apify-check` authenticated **GET /v2/users/me**.
- Prints authentication success or sanitized failure codes, not the token, account details, headers or API response. It has no debug tracing or artifact upload.
- Keeps the paid switch false and run/day spending allowances at zero, and never calls an Actor, starts a collection job or connects to Supabase. The versioned paid-authorization policy also remains false.
- Runs only on explicit manual dispatch, with read-only repository permissions and a five-minute timeout. No automatic trigger or collector is added.

**Known blocker:** the repository's GitHub Actions account is currently locked for billing. The secret can be configured securely now, but this runner cannot execute until the repository owner resolves that lock. Do not interpret a failed-to-start workflow as invalid Apify credentials. No authentication success is claimed until the check actually executes.

## What this does and does not complete

This supplies a secure phone-accessible secret store and a prepared read-only check for the existing project. It does not configure `APIFY_TOKEN` in the current Cloud workspace or fix its PostgreSQL networking. No supported secret transfer from GitHub into this running machine is exposed here; a custom public token-entry form or tunnel is not being introduced. To run locally later, the workspace still needs an actual supported vault/environment binding (through desktop controls when offered), or the private application can run in an existing deployment with its native secret settings. Do not publish a new Codex environment or start another conversation just to use this GitHub alternative.

Paid collection remains disabled independently of whether the secret is saved or authentication passes.
