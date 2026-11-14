# Android: dedicated Veriflow application password on Replit

## Verified live role; reset not yet performed

In Supabase project `qrejfpeclncrevmepgzx`, `veriflow_app` exists, is LOGIN/INHERIT, has no expiration, is a member of `veriflow_runtime`, and has schema USAGE plus SELECT on sources. It has no superuser, BYPASSRLS, CREATEROLE or CREATEDB privilege. The existing `postgres` role has ADMIN OPTION for this role. The registry still contains 42 sources. Resetting the main database password affects `postgres`, not the dedicated role.

The connected Replit integration returned no exact or search match for **Review Capture Hub**. It cannot access the requested app under the user's reported `service362` browser account. This does not prove the app is absent; it means the current connector cannot operate on it. No replacement app is created and no live password is reset here.

## Phone-only procedure in the existing app

1. In your password manager, create and save a **32-character random password consisting of letters and digits** for `Veriflow / veriflow_app`. You choose/retain it before any reset; the assistant never generates an inaccessible password. This character set also avoids connection-URL encoding mistakes. Do not use the main Supabase password for this new role password.
2. Sign into Replit as `service362` in your Android browser and open **Review Capture Hub**. Open the workspace **Secrets** tool (use the tools search, or the browser's Desktop site mode if the mobile layout hides it). Enter values only in the native Secrets form, never Replit Agent chat, this conversation, files or commands. Do not publish the app to configure secrets.
3. Add `VERIFLOW_APP_PASSWORD` with the password retained in your password manager. Add the **temporary** `VERIFLOW_RESET_POSTGRES_PASSWORD` secret with the current main Supabase password you already reset. Add `VERIFLOW_RESET_CONFIRM` with the non-secret value `qrejfpeclncrevmepgzx:veriflow_app`. Existing secrets should be updated in place rather than duplicated.
4. In that existing Replit app, ask Replit Agent to bring in only the reviewed one-time helper `scripts/reset_app_password.py` and its required existing Veriflow Python modules/dependencies from `Unity20092024/Veriflow`, branch `feature/step-1-private-collection`. Do not replace unrelated app code, import database migrations, run seed/setup or create another app. If it already has that repository/revision, reuse it. Ask it to execute the helper once as a maintenance action, **not as the normal Run/start command or a web endpoint**. The native Secrets form supplies values to the process; the Agent should not inspect, print, quote or summarize any secret value.

A non-secret request you can send to Replit Agent:

> In this existing Review Capture Hub app, use the reviewed one-time Veriflow application-role password reset helper from the existing GitHub feature branch. Run it once using the environment supplied by Replit Secrets, without reading or displaying any secret values. Do not run migrations, seed data, change grants/RLS, alter postgres's password, enable collectors, publish, or create another app. Show only the helper's sanitized status. Afterward use the dedicated application role for normal jobs, never the maintenance administrator credentials.

This procedure temporarily entrusts the current administrator password to this Replit app for the single administrative operation. Anyone who controls the app/runtime can potentially access its environment; only do this in your own trusted app with trusted collaborators. It is never used for ordinary collection jobs. If you do not want to grant that temporary administrative access to Replit, stop before adding that secret: a trusted administrative client using PostgreSQL's `\password veriflow_app` is the alternative, but that requires a separate secure interactive client. Pasting plaintext `ALTER ROLE ... PASSWORD` into saved SQL/chat is not the proposed method.

5. The helper uses the exact existing session-pooler endpoint and verified TLS, checks the expected role, generates a SCRAM verifier locally from your chosen password, and executes **only an ALTER ROLE password change targeting veriflow_app**. Plaintext passwords never appear in SQL, command arguments, helper output or logs. It then authenticates as the application role and checks the private database health/source count. It does not modify the main password, grants, role flags, schema, RLS or sources. It does not generate a new secret for you.
6. After successful verification, immediately delete `VERIFLOW_RESET_POSTGRES_PASSWORD` and `VERIFLOW_RESET_CONFIRM` from the app's Secrets and from any deployment-secret copy if one was added. Keep `VERIFLOW_APP_PASSWORD` and your password-manager copy. Do not leave a maintenance process running or wire it to app startup. If the helper reports an error, its password-change status can be unconfirmed (for example, a commit connection loss); do not expose errors/credentials or automatically loop password resets. Your chosen password remains available in your password manager.
7. Configure the app's normal database connection in its native secret settings: host `aws-1-us-west-2.pooler.supabase.com`, port `5432`, database `postgres`, username **`veriflow_app.qrejfpeclncrevmepgzx`**, and the saved application password. For the existing Python implementation, put the connection string in `DATABASE_URL`, with `sslmode=verify-full&sslrootcert=system`; set non-secret `SUPABASE_PROJECT_REF=qrejfpeclncrevmepgzx`. A password without the project-suffixed pooler username will not route correctly. Do not use the main password for this app login. If a different Replit database driver is used, configure verified hostname/CA validation using that driver's supported settings rather than disabling certificate checks.
8. Keep paid execution false, verify the normal application health command reads 42 sources, and require an authenticated dashboard 200 response plus denied anonymous access. Existing sessions may need reconnecting; a password change does not terminate old sessions. No production collection is authorized by this reset.

## Maintenance invocation reference

For Replit Agent/your administrator, the one-time command is:

```sh
python scripts/reset_app_password.py
```

It accepts no password arguments. All credentials come from native server environment secrets. It is not deployed as an HTTP form/endpoint. Normal application startup remains separate. No attempt is made from the blocked Codex PostgreSQL network.

## Validation

All **86 tests passed** against disposable PostgreSQL 17, including a real password-login roundtrip after the helper, an unchanged main-role password, unchanged role attributes and RLS policies, and a 42-source read as `veriflow_app`. Unit tests ensure the fixed role target, fail-closed checks and secret-free output. The production helper has not run: the requested Replit app is inaccessible through this connector and its owner must enter the chosen secrets through native controls. No live password or successful Replit connection is claimed.

References: [Supabase roles/passwords](https://supabase.com/docs/guides/database/postgres/roles), [PostgreSQL psql password handling](https://www.postgresql.org/docs/17/app-psql.html), [Replit Secrets](https://docs.replit.com/replit-workspace/workspace-features/secrets).
