"""Read-only acceptance checks on the actual intended application runtime."""
from .health import database_health
from .pilot import paid_enabled


def check(conn,source_policy=False):
    health=database_health(conn)
    policies=[]
    if source_policy:
        # Explicit read-only HTTPS policy checks; no reviews, source activation
        # or database writes. Each client is isolated from paid integrations.
        from .libreviews_live import LibreReviewsClient
        from .mangrove_live import MangroveClient
        for name,client in (('lib-reviews',LibreReviewsClient()),('mangrove-reviews',MangroveClient())):
            try:
                digest=client.verify_policy();policies.append(dict(source=name,policy_verified=True,terms_hash=digest))
            except Exception:
                policies.append(dict(source=name,policy_verified=False,error_code='source_policy_unavailable'))
    disabled=not paid_enabled()
    return dict(ready=health['healthy'] and disabled and all(p['policy_verified'] for p in policies),
                database=health,paid_execution_disabled=disabled,source_policies=policies,
                recurring_worker_required=True,hosting_or_collection_started=False)
