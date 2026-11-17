# Operations

## Initial policy setup

Run this pattern through a private operator script with your actual reviewed values. It uses parameters for source-specific values. Test fixtures and example evidence are never valid provider approval.

```python
from veriflow.db import connect

# Set these from a reviewed permission record, not from source registry membership.
source_id = 'capterra-reviews'
product_name, vendor, external_product_key = 'YOUR PRODUCT', 'YOUR VENDOR', 'SOURCE PRODUCT ID'
evidence = 'YOUR LICENSE / APPROVED EXPORT REFERENCE AND PERMITTED USE'
approver = 'YOUR OPERATOR ID'
expiry = 'YOUR APPROVAL EXPIRY AS ISO TIMESTAMP'
allow_text = False  # Set true only if full-text storage is expressly permitted.

with connect() as conn:
    product_id = conn.execute('''INSERT INTO veriflow.products(name,vendor)
        VALUES (%s,%s) ON CONFLICT (name,vendor) DO UPDATE SET name=excluded.name
        RETURNING id''', (product_name,vendor)).fetchone()['id']
    conn.execute('''INSERT INTO veriflow.source_products
        (source_id,external_key,product_id,expected_name) VALUES (%s,%s,%s,%s)''',
        (source_id,external_product_key,product_id,product_name))
    grant_id = conn.execute('''INSERT INTO veriflow.authorizations
        (source_id,method,evidence,product_keys,full_text_allowed,approved_by,expires_at)
        VALUES (%s,'approved_import',%s,%s,%s,%s,%s) RETURNING id''',
        (source_id,evidence,[external_product_key],allow_text,approver,expiry)).fetchone()['id']
    conn.execute('''UPDATE veriflow.sources SET enabled=true,access_status='approved',
        full_text_allowed=%s,next_run_at=now() WHERE id=%s''', (allow_text,source_id))
print(grant_id)
```

Keep approval documents outside this public repository. The repository is public; application data, environment files, actual imports, account inventory, and production database exports must remain private.

## Scheduling and monitoring

`worker` polls every five seconds when idle; each source's `next_run_at` controls collection. Success schedules its configured interval (at least its minimum interval); errors back off from 60 seconds up to 24 hours; rate-limit Retry-After can extend the delay. A continuous process or systemd service provides automation. The example units assume installation in `/opt/veriflow`, a dedicated OS user, and an owner-readable `/etc/veriflow.env`. Install and enable them through your deployment process after configuring credentials. They are examples, not a deployed schedule.

The dashboard's Sources and Runs & errors pages expose enabled state, policy, next run, failure count, status and sanitized error code. Database connection failures are written as `worker_database_unavailable` to process output because a failing database cannot persist its own error log. Send these logs to your existing private monitoring system. No external alerting service is provisioned.

- `access_denied`: approval expired/revoked, mismatched scope, disabled policy or denied full text. Review permission before resubmitting.
- `invalid_import`: check required fields, source URL, date, rating scale and explicit product mapping.
- `connector_unavailable`: adapter has not been implemented/registered; keep the source disabled.
- `rate_limited`: batch remains pending and collection resumes after the scheduler delay.
- `collection_failed`: inspect the original import privately and reproduce; raw exceptions are deliberately excluded from persistent logs.

## Revocation and retention

Set `authorizations.revoked_at=now()` and disable the source immediately when rights end. Revocation blocks new ingestion; it does not automatically erase previously lawfully collected content. Apply the agreement's retention/deletion requirements explicitly: delete or redact affected reviews, clear pending queue payloads for the grant, and remove related Trends data as required. Preserve only the audit references permitted by the agreement. The initial milestone does not infer legal retention periods or run automatic deletion.

## Database checks before deployment

Apply migrations to an empty development database and run the full integration suite. Check all `veriflow` tables have `relrowsecurity=true`, that `anon`/`authenticated` cannot use the schema, that your runtime login is not owner/superuser/BYPASSRLS, and that `veriflow` is absent from exposed Data API schemas. Run Supabase security advisors for the chosen project before deployment. The subsequent integration milestone applied the live Veriflow migrations and completed security advisors. See `supabase-composio-milestone.md` for runtime networking and Composio credential blockers.
