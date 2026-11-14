import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from psycopg.types.json import Jsonb
from .connectors import AccessDenied, CollectionError, ConnectorRegistry, RateLimited, normalize


CONNECTORS = ConnectorRegistry()


def authorization(conn, source_id, grant_id, method):
    grant = conn.execute('''SELECT * FROM veriflow.authorizations
        WHERE id=%s AND source_id=%s AND method=%s AND revoked_at IS NULL
        AND expires_at>now() FOR SHARE''', (grant_id, source_id, method)).fetchone()
    if not grant:
        raise AccessDenied('Valid source authorization required')
    return grant


def validate_products(conn, source, grant, records):
    mappings = {}
    for record in records:
        if record.product_key not in grant['product_keys']:
            raise AccessDenied('Product outside authorization scope')
        mapping = conn.execute('''SELECT * FROM veriflow.source_products
            WHERE source_id=%s AND external_key=%s FOR SHARE''',
            (source['id'], record.product_key)).fetchone()
        if not mapping or normalize(record.software_name) != normalize(mapping['expected_name']):
            raise CollectionError('Unresolved product mapping')
        mappings[record.product_key] = mapping['product_id']
    return mappings


def enqueue(conn, source_id, grant_id, payload, format, provider_job_id=None):
    if len(payload.encode()) > 5_000_000:
        raise CollectionError('Import exceeds 5MB')
    source = conn.execute('SELECT * FROM veriflow.sources WHERE id=%s FOR SHARE', (source_id,)).fetchone()
    if not source or not source['enabled'] or source['access_status'] != 'approved' or source['category'] == 'market_research':
        raise AccessDenied()
    grant = authorization(conn, source_id, grant_id, source['collection_method'])
    records = CONNECTORS.get(source['collection_method']).collect(payload, format, source, grant)
    validate_products(conn, source, grant, records)
    if source['collection_method']=='apify':
        if provider_job_id is None:
            raise AccessDenied('Actor imports require a budgeted job reference')
        job=conn.execute('''SELECT reserved_records FROM veriflow.apify_jobs
            WHERE id=%s AND source_id=%s AND authorization_id=%s AND state='running' FOR SHARE''',
            (provider_job_id,source_id,grant_id)).fetchone()
        if not job or len(records)>job['reserved_records']:
            raise AccessDenied('Dataset does not match its reserved source/job allowance')
    # Store normalized allowlisted fields only. Never persist the original import.
    return conn.execute('''INSERT INTO veriflow.import_batches(source_id,authorization_id,records,provider_job_id)
        VALUES (%s,%s,%s,%s) RETURNING id''',
        (source_id, grant_id, Jsonb([asdict(r) for r in records]),provider_job_id)).fetchone()['id']


def run_one(conn):
    """One transaction locks a due source; parallel workers skip it safely.

    Caller commits per call. Process death rolls back the batch and lease.
    Each retry revalidates policy, authorization expiry, and product mapping.
    """
    started = datetime.now(timezone.utc)
    source = conn.execute('''SELECT * FROM veriflow.sources WHERE enabled
        AND next_run_at<=now() ORDER BY next_run_at FOR UPDATE SKIP LOCKED LIMIT 1''').fetchone()
    if not source:
        return None
    batch = conn.execute('''SELECT * FROM veriflow.import_batches WHERE source_id=%s
        AND status='pending' ORDER BY created_at LIMIT 1 FOR UPDATE''', (source['id'],)).fetchone()
    status, code, inserted, duplicates = 'idle', None, 0, 0
    delay = max(source['schedule_seconds'], source['minimum_interval_seconds'])
    run_id = None
    try:
        with conn.transaction():
            if batch:
                if source['access_status'] != 'approved' or source['category'] == 'market_research':
                    raise AccessDenied()
                grant = authorization(conn, source['id'], batch['authorization_id'], source['collection_method'])
                # Parse again through the connector to reject permissions changed since enqueue.
                rows = [dict(r, review_text=r['text']) for r in batch['records']]
                records = CONNECTORS.get(source['collection_method']).collect(json.dumps(rows), 'json', source, grant)
                mappings = validate_products(conn, source, grant, records)
                run_id = conn.execute('''INSERT INTO veriflow.collection_runs
                    (source_id,batch_id,status,started_at,provider_job_id) VALUES (%s,%s,'success',%s,%s) RETURNING id''',
                    (source['id'], batch['id'], started,batch['provider_job_id'])).fetchone()['id']
                for r in records:
                    product_id = mappings[r.product_key]
                    material = [str(product_id), normalize(r.text), r.published_at] if r.text else [str(product_id), r.original_url, r.external_id]
                    fingerprint = hashlib.sha256(json.dumps(material).encode()).hexdigest()
                    group = fingerprint if r.text else None
                    if r.license_metadata:
                        # Do not collapse distinct authors' licensed contributions.
                        fingerprint=hashlib.sha256(json.dumps([fingerprint,r.license_metadata['public_credit'],r.license_metadata['attribution_url']]).encode()).hexdigest()
                    result = conn.execute('''INSERT INTO veriflow.reviews
                        (source_id,product_id,external_id,software_name,review_text,rating,rating_scale,
                        published_at,original_url,authorization_id,run_id,fingerprint,duplicate_group)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id''',
                        (source['id'],product_id,r.external_id,r.software_name,r.text,r.rating,r.rating_scale,
                         r.published_at,r.original_url,grant['id'],run_id,fingerprint,group))
                    count=result.rowcount
                    if count and r.license_metadata:
                        review_id=result.fetchone()['id']
                        m=r.license_metadata
                        conn.execute('''INSERT INTO veriflow.review_licenses
                            (review_id,license_id,license_url,source_terms_url,public_credit,attribution_url,text_modified,change_note)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''',
                            (review_id,m['license_id'],m['license_url'],m['source_terms_url'],m['public_credit'],m['attribution_url'],m['text_modified'],m.get('change_note')))
                    inserted += count
                    duplicates += 1-count
                conn.execute("UPDATE veriflow.import_batches SET status='completed',records='[]',completed_at=now() WHERE id=%s", (batch['id'],))
                status = 'success'
    except Exception as exc:
        # Never write raw exceptions, request bodies, credentials, or review text to logs.
        code = exc.code if isinstance(exc, CollectionError) else 'collection_failed'
        status = 'rate_limited' if isinstance(exc, RateLimited) else 'error'
        delay = max(source['minimum_interval_seconds'], min(86400, 60 * 2 ** min(source['failures'], 10)))
        if isinstance(exc, RateLimited):
            delay = max(delay, exc.retry_after)
        elif batch:
            # Invalid imports require correction; do not retry permanently bad input.
            conn.execute("UPDATE veriflow.import_batches SET status='failed',records='[]',completed_at=now() WHERE id=%s", (batch['id'],))
        inserted, duplicates, run_id = 0, 0, None
    if run_id:
        conn.execute('UPDATE veriflow.collection_runs SET inserted=%s,duplicates=%s,finished_at=now() WHERE id=%s', (inserted,duplicates,run_id))
    else:
        conn.execute('''INSERT INTO veriflow.collection_runs(source_id,batch_id,status,error_code,started_at,provider_job_id)
            VALUES (%s,%s,%s,%s,%s,%s)''', (source['id'],batch['id'] if batch else None,status,code,started,batch['provider_job_id'] if batch else None))
    if batch and batch['provider_job_id'] and status in ('success','error'):
        conn.execute('''UPDATE veriflow.apify_jobs SET state=%s,inserted=%s,duplicates=%s,error_code=%s,updated_at=now() WHERE id=%s''',
            ('ingested' if status=='success' else 'failed',inserted,duplicates,code,batch['provider_job_id']))
    if batch and batch['provider_job_id'] and status in ('success','error'):
        conn.execute('''INSERT INTO veriflow.integration_status(provider,status,error_code,last_success_at)
            VALUES ('apify',%s,%s,CASE WHEN %s THEN now() END)
            ON CONFLICT(provider) DO UPDATE SET status=excluded.status,error_code=excluded.error_code,
            last_success_at=coalesce(excluded.last_success_at,veriflow.integration_status.last_success_at),updated_at=now()''',
            ('ready' if status=='success' else 'error',code,status=='success'))
    conn.execute('''UPDATE veriflow.sources SET last_status=%s,last_run_at=now(),
        failures=CASE WHEN %s IN ('error','rate_limited') THEN failures+1 ELSE 0 END,
        next_run_at=now()+(%s * interval '1 second') WHERE id=%s''', (status,status,delay,source['id']))
    return dict(source=source['id'],status=status,inserted=inserted,duplicates=duplicates,error_code=code)
