"""Persist sanitized integration health and normalized Google Trends research."""
import math
from datetime import date
from psycopg.types.json import Jsonb
from .composio import ComposioClient
from .connectors import AccessDenied, CollectionError, canonical_url
from .worker import authorization

KEYWORDS = {
    'google_trends': ('google trends', 'googletrends', 'google_trends'),
    'software_reviews': ('review', 'rating', 'capterra', 'g2'),
    'product_discovery': ('product', 'software', 'alternativeto'),
    'search_research': ('search', 'research', 'crawl'),
    'community': ('reddit', 'youtube', 'forum', 'discussion'),
}


def capability_summary(tool):
    material = ' '.join(str(tool.get(k) or '') for k in ('name','slug','toolkit','description')).lower()
    return dict(slug=tool['slug'],name=tool.get('name'),version=tool.get('version'),
                categories=[key for key,words in KEYWORDS.items() if any(w in material for w in words)],
                read_only_status='requires_contract_review')


def set_status(conn, provider, status, error_code=None, capabilities=None, discovered=False, success=False):
    conn.execute('''INSERT INTO veriflow.integration_status
        (provider,status,error_code,capabilities,last_discovered_at,last_success_at)
        VALUES (%s,%s,%s,%s,CASE WHEN %s THEN now() END,CASE WHEN %s THEN now() END)
        ON CONFLICT(provider) DO UPDATE SET status=excluded.status,error_code=excluded.error_code,
        capabilities=CASE WHEN %s THEN excluded.capabilities ELSE veriflow.integration_status.capabilities END,
        last_discovered_at=coalesce(excluded.last_discovered_at,veriflow.integration_status.last_discovered_at),
        last_success_at=coalesce(excluded.last_success_at,veriflow.integration_status.last_success_at),updated_at=now()''',
        (provider,status,error_code,Jsonb(capabilities or []),discovered,success,capabilities is not None))


def discover(conn, client=None):
    client = client or ComposioClient()
    try:
        inventory = client.discover()
        # Clear stale health from the previous inventory. Preserve last success.
        conn.execute("UPDATE veriflow.integration_status SET status='unsupported',error_code='not_in_latest_discovery',updated_at=now() WHERE provider<>'composio'")
        providers = sorted({a['toolkit'] for a in inventory['connected_services']})
        for provider in providers:
            capabilities = [capability_summary(t) for t in inventory['tools'] if t['toolkit']==provider and t['connected']]
            set_status(conn,provider,'discovered',capabilities=capabilities,discovered=True)
        set_status(conn,'composio','discovered',capabilities=[],discovered=True)
        return inventory
    except Exception as exc:
        missing = not client.api_key or not client.user_id
        code = 'credentials_missing' if missing else exc.code if isinstance(exc,CollectionError) else 'discovery_failed'
        # Existing providers must not appear current when refresh failed.
        conn.execute("UPDATE veriflow.integration_status SET status='error',error_code=%s,updated_at=now() WHERE provider<>'composio'",(code,))
        set_status(conn,'composio','pending_credentials' if missing else 'error',code)
        return dict(status='pending_credentials' if missing else 'error',error_code=code,
                    connected_services=[],tools=[],execution_enabled=False)


def normalize_trends(data, mapping):
    """Output adapter configured after inspecting the real provider response.

    Retain only ISO dates and numeric interest values; drop every other field.
    Paths are lists of object keys; no executable expressions or remote references.
    """
    rows = data
    path = mapping.get('rows_path',[])
    if not isinstance(path,list) or len(path)>10 or not all(isinstance(k,str) for k in path):
        raise CollectionError('Invalid output mapping')
    for key in path:
        if not isinstance(rows,dict) or key not in rows:
            raise CollectionError('Unexpected Trends response')
        rows=rows[key]
    if not isinstance(rows,list) or not 1 <= len(rows) <= 5000:
        raise CollectionError('Expected bounded Trends series')
    series=[]
    for row in rows:
        if not isinstance(row,dict):
            raise CollectionError('Unexpected Trends point')
        day=date.fromisoformat(row[mapping['date_key']]).isoformat()
        value=row[mapping['value_key']]
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0 <= value <= 100:
            raise CollectionError('Invalid Trends interest value')
        series.append(dict(date=day,value=value))
    return dict(series=series)


def collect_trends(conn,binding_id,grant_id,arguments,query,geography,time_range,original_url,client=None):
    client=client or ComposioClient()
    binding=conn.execute('SELECT * FROM veriflow.integration_bindings WHERE id=%s FOR SHARE',(binding_id,)).fetchone()
    if not binding or binding['source_id']!='google-trends':
        raise AccessDenied()
    provider=binding['provider']
    try:
        with conn.transaction():
            source=conn.execute("SELECT * FROM veriflow.sources WHERE id='google-trends' FOR SHARE").fetchone()
            if not source or not source['enabled'] or source['access_status']!='approved' or source['collection_method']!='composio':
                raise AccessDenied()
            grant=authorization(conn,'google-trends',grant_id,'composio')
            if query not in grant['product_keys'] or any(not isinstance(v,str) or not v.strip() or len(v)>500 for v in (query,geography,time_range)):
                raise AccessDenied()
            # Bind labels to the provider's real argument names after contract review.
            labels=binding['output_mapping'].get('argument_keys',{})
            for label,value in [('query',query),('geography',geography),('time_range',time_range)]:
                if label not in labels or arguments.get(labels[label])!=value:
                    raise AccessDenied('Research labels must match provider arguments')
            url=canonical_url(original_url)
            from urllib.parse import urlsplit
            if urlsplit(url).hostname!='trends.google.com':
                raise AccessDenied()
            inventory=client.discover()
            raw=client.execute_read_only(binding,arguments,inventory)
            normalized=normalize_trends(raw,binding['output_mapping'])
            result=conn.execute('''INSERT INTO veriflow.trends_research
                (source_id,query,geography,time_range,tool_slug,tool_version,original_url,data,authorization_id)
                VALUES ('google-trends',%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
                (query,geography,time_range,binding['tool_slug'],binding['tool_version'],url,Jsonb(normalized),grant_id)).fetchone()
            set_status(conn,provider,'ready',success=True)
            return dict(status='success',research_id=str(result['id']),points=len(normalized['series']))
    except Exception as exc:
        code=exc.code if isinstance(exc,CollectionError) else 'integration_failed'
        set_status(conn,provider,'error',error_code=code)
        # Persist health in caller transaction without committing partial research.
        return dict(status='error',error_code=code)
