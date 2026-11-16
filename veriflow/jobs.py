"""Durable, authorization-scoped jobs for permitted source crawls."""
import json
import urllib.parse
import uuid

from .connectors import AccessDenied, CollectionError, RateLimited, SourceUnavailable, canonical_url
from .crawl import extract_page
from .worker import authorization, CONNECTORS
from .strategy import CLAIM_JOINS, CLAIM_ORDER, preferences, select_page

VALID_CATEGORIES = {
    'software_review_directory','software_discovery','app_marketplace',
    'community_discussion','review_aggregation','market_research',
}


def _eligible_targets(conn, scope, category=None, product_id=None, software_category_id=None):
    rows = conn.execute('''SELECT
        s.id AS source_id,s.category,s.url AS source_url,s.enabled,s.access_status,
        s.collection_method,s.full_text_allowed AS source_full_text_allowed,
        s.required_license_id,s.attribution_required,
        a.id AS authorization_id,a.method AS grant_method,a.product_keys,
        a.license_id,a.terms_url,a.full_text_allowed AS grant_full_text_allowed,
        a.expires_at,
        sp.product_id,sp.external_key,sp.expected_name,
        coalesce(p.canonical_product_id,p.id) AS canonical_id
      FROM veriflow.sources s
      JOIN veriflow.authorizations a ON a.source_id=s.id
      JOIN veriflow.source_products sp ON sp.source_id=s.id
      JOIN veriflow.products p ON p.id=sp.product_id
      WHERE s.enabled AND s.access_status='approved'
        AND s.collection_method IN ('permitted_crawl','authorized_api')
        AND s.category<>'market_research'
        AND a.method=s.collection_method AND a.revoked_at IS NULL AND a.expires_at>now()
        AND (%s::text IS NULL OR s.category=%s)
        AND (%s::uuid IS NULL OR sp.product_id=%s)
        AND (%s::uuid IS NULL OR EXISTS (
          SELECT 1 FROM veriflow.product_categories pc
          JOIN veriflow.products member ON member.id=pc.product_id
          WHERE coalesce(member.canonical_product_id,member.id)=coalesce(p.canonical_product_id,p.id)
            AND pc.category_id=%s))
      ORDER BY s.id,sp.product_id,a.expires_at DESC''',
      (category,category,product_id,product_id,software_category_id,software_category_id)).fetchall()
    targets = []
    seen = set()
    for row in rows:
        product_keys = row['product_keys'] or []
        if row['external_key'] not in product_keys:
            continue
        if row['collection_method'] == 'permitted_crawl':
            try:
                product_url = canonical_url(row['external_key'])
                source_url = canonical_url(row['source_url'])
            except (TypeError, ValueError, CollectionError):
                continue
            host = urllib.parse.urlsplit(source_url).hostname
            if urllib.parse.urlsplit(product_url).hostname != host:
                continue
        else:
            # API product identifiers are interpreted by a source-specific adapter,
            # never fetched as arbitrary URLs.
            product_url = row['external_key']
        key = (row['source_id'], str(row.get('canonical_id') or row['product_id']))
        if key in seen:
            continue
        seen.add(key)
        target = dict(row)
        target['start_url'] = product_url if row['collection_method'] == 'permitted_crawl' else None
        targets.append(target)
    return targets


def _refresh_job(conn, job_id):
    summary = conn.execute('''SELECT count(*) AS item_count,
        count(*) FILTER (WHERE state IN ('completed','failed','cancelled')) AS terminal,
        count(*) FILTER (WHERE state='completed') AS completed,
        count(*) FILTER (WHERE state='failed') AS failed,
        coalesce(sum(pages_fetched),0) AS pages,
        coalesce(sum(reviews_retrieved),0) AS retrieved,
        coalesce(sum(inserted),0) AS inserted,
        coalesce(sum(duplicates),0) AS duplicates
      FROM veriflow.collection_job_items WHERE job_id=%s''', (job_id,)).fetchone()
    completed_sources = conn.execute('''SELECT count(*) AS count FROM (
        SELECT source_id FROM veriflow.collection_job_items WHERE job_id=%s
        GROUP BY source_id HAVING bool_and(state='completed')
      ) finished''', (job_id,)).fetchone()['count']
    if summary['item_count'] == 0:
        state, error = 'failed', 'no_eligible_sources'
    elif summary['terminal'] < summary['item_count']:
        state, error = 'running', None
    elif summary['failed'] == 0:
        state, error = 'completed', None
    elif summary['completed'] == 0:
        state, error = 'failed', 'collection_failed'
    else:
        state, error = 'partial', 'some_sources_failed'
    conn.execute('''UPDATE veriflow.collection_jobs SET state=%s,error_code=%s,
        completed_sources=%s,pages_fetched=%s,reviews_retrieved=%s,inserted=%s,
        duplicates=%s,started_at=coalesce(started_at,now()),updated_at=now(),
        finished_at=CASE WHEN %s IN ('completed','partial','failed','cancelled') THEN now() ELSE NULL END
        WHERE id=%s''',
        (state,error,completed_sources,summary['pages'],summary['retrieved'],
         summary['inserted'],summary['duplicates'],state,job_id))
    return state


def start_job(conn, scope, category=None, product_id=None, *,
              strategy='breadth_first', target_reviews=None, software_category_id=None):
    strategy, target_reviews = preferences(strategy, target_reviews)
    if software_category_id:
        try:
            software_category_id = str(uuid.UUID(str(software_category_id)))
        except (ValueError, TypeError, AttributeError):
            raise CollectionError('Invalid software category') from None
    if scope not in ('category','product','all_eligible'):
        raise CollectionError('Invalid collection scope')
    if scope == 'category':
        if category not in VALID_CATEGORIES or category == 'market_research' or product_id:
            raise CollectionError('Invalid category scope')
    elif scope == 'product':
        if not product_id or category:
            raise CollectionError('Product scope requires a product')
        try:
            product_id = str(uuid.UUID(str(product_id)))
        except (ValueError, TypeError, AttributeError):
            raise CollectionError('Invalid product identifier') from None
    elif category or product_id:
        raise CollectionError('All-source scope takes no filter')

    targets = _eligible_targets(conn, scope,
        category if scope == 'category' else None,
        product_id if scope == 'product' else None, software_category_id)
    with conn.transaction():
        job_id = conn.execute('''INSERT INTO veriflow.collection_jobs
            (scope,category,product_id,state,requested_sources,strategy,target_reviews,software_category_id)
            VALUES (%s,%s,%s,'queued',%s,%s,%s,%s) RETURNING id''',
            (scope,category if scope == 'category' else None,
             product_id if scope == 'product' else None,
             len({row['source_id'] for row in targets}),strategy,target_reviews,
             software_category_id)).fetchone()['id']
        for row in targets:
            if row['source_id'] == 'lib-reviews':
                from .free_collection import reserve_test_job
                reserve_test_job(conn, row)
            conn.execute('''INSERT INTO veriflow.collection_job_items
                (job_id,source_id,product_id,product_key,authorization_id,cursor_url)
                VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
                (job_id,row['source_id'],row['product_id'],row['external_key'],
                 row['authorization_id'],row['start_url']))
        state = _refresh_job(conn, job_id)
    return {'job_id':str(job_id),'state':state,'eligible_sources':len({row['source_id'] for row in targets}),
            'eligible_products':len({str(r.get('canonical_id') or r['product_id']) for r in targets}),
            'strategy':strategy,'target_reviews':target_reviews,
            'error_code':'no_eligible_sources' if not targets else None}


def _fail_item(conn, item_id, job_id, code):
    conn.execute('''UPDATE veriflow.collection_job_items SET state='failed',error_code=%s,
        lease_until=NULL,updated_at=now(),finished_at=now() WHERE id=%s''', (code,item_id))
    return _refresh_job(conn, job_id)


def run_one_collection_page(conn):
    """Fetch and queue one permitted page; durable cursor state survives process restarts."""
    with conn.transaction():
        item = conn.execute(f'''WITH candidate AS (
            SELECT i.id,j.strategy,j.target_reviews FROM veriflow.collection_job_items i
            JOIN veriflow.collection_jobs j ON j.id=i.job_id
            {CLAIM_JOINS}
            WHERE j.state IN ('queued','running')
              AND (i.state='queued' OR (i.state='fetching' AND i.lease_until<now()))
              AND i.next_attempt_at<=now()
              AND (j.strategy IS NULL OR NOT EXISTS (
                SELECT 1 FROM veriflow.collection_job_items busy
                JOIN veriflow.products bp ON bp.id=busy.product_id
                WHERE coalesce(bp.canonical_product_id,bp.id)=coalesce(product.canonical_product_id,product.id)
                  AND busy.id<>i.id AND busy.state IN ('awaiting_ingest','fetching')
                  AND (busy.state='awaiting_ingest' OR busy.lease_until>now())))
              AND (j.strategy IS NULL OR NOT EXISTS (
                SELECT 1 FROM veriflow.collection_job_items recent
                JOIN veriflow.sources rs ON rs.id=recent.source_id
                WHERE recent.source_id=i.source_id AND recent.attempts>0
                  AND recent.updated_at>now()-
                    (greatest(rs.minimum_interval_seconds,3)*interval '1 second')))
            ORDER BY {CLAIM_ORDER}
            FOR UPDATE OF i SKIP LOCKED LIMIT 1
          )
          UPDATE veriflow.collection_job_items i SET state='fetching',
            lease_until=now()+interval '2 minutes',attempts=attempts+1,updated_at=now()
          FROM candidate WHERE i.id=candidate.id RETURNING i.*,candidate.strategy,
            candidate.target_reviews''').fetchone()
        if not item:
            return None
        conn.execute("UPDATE veriflow.collection_jobs SET state='running',started_at=coalesce(started_at,now()),updated_at=now() WHERE id=%s",
                     (item['job_id'],))
        if item.get('strategy'):
            limits = conn.execute('''SELECT e.reviews,j.created_at<now()-interval '48 hours' AS expired,
              (SELECT coalesce(sum(attempts),0) FROM veriflow.collection_job_items
               WHERE job_id=j.id) AS requests,
              (SELECT coalesce(sum(inserted),0) FROM veriflow.collection_job_items
               WHERE job_id=j.id) AS new_reviews
              FROM veriflow.collection_jobs j JOIN veriflow.products p ON p.id=%s
              JOIN veriflow.product_evidence e ON e.product_id=coalesce(p.canonical_product_id,p.id)
              WHERE j.id=%s''', (item['product_id'],item['job_id'])).fetchone()
            if limits['reviews'] >= item['target_reviews']:
                conn.execute("""UPDATE veriflow.collection_job_items SET state='completed',
                  lease_until=NULL,finished_at=now(),updated_at=now() WHERE id=%s""", (item['id'],))
                _refresh_job(conn,item['job_id'])
                return {'job_id':str(item['job_id']),'state':'completed','reason':'per_product_target_reached'}
            limit = ('original_job_expired' if limits['expired'] else
                     'job_request_limit' if limits['requests']>1500 else
                     'job_unique_limit' if limits['new_reviews']>=500 else
                     'product_page_limit' if item['pages_fetched']>=10 else None)
            if limit:
                _fail_item(conn,item['id'],item['job_id'],limit)
                return {'job_id':str(item['job_id']),'state':'failed','error_code':limit}
    try:
        with conn.transaction():
            source = conn.execute('SELECT * FROM veriflow.sources WHERE id=%s', (item['source_id'],)).fetchone()
            if not source or not source['enabled'] or source['access_status'] != 'approved':
                raise AccessDenied()
            grant = authorization(
                conn, item['source_id'], item['authorization_id'], source['collection_method']
            )
            mapping = conn.execute('''SELECT * FROM veriflow.source_products
                WHERE source_id=%s AND product_id=%s AND external_key=%s''',
                (item['source_id'],item['product_id'],item['product_key'])).fetchone()
            if not mapping or item['product_key'] not in grant['product_keys']:
                raise AccessDenied('Product authorization or mapping changed')
        if source['id'] == 'lib-reviews':
            from .free_collection import fetch_test_page
            page = fetch_test_page(source, grant, mapping, item['cursor_url'])
        elif source['collection_method'] == 'permitted_crawl':
            page = extract_page(source, grant, mapping, item['cursor_url'])
        elif source['collection_method'] == 'authorized_api':
            connector = CONNECTORS.get(source['collection_method'], source)
            result = connector.fetch_page(
                source, grant, mapping, item['cursor_url']
            )
            if isinstance(result, dict):
                page = result
            else:
                records, next_cursor = result
                page = {'records': records, 'next_url': next_cursor,'request_count':1}
        else:
            raise AccessDenied()
        with conn.transaction():
            batch_id = None
            selection_duplicates = 0
            if page['records'] and item.get('strategy'):
                page['records'],selection_duplicates = select_page(
                    conn,item,source,grant,page['records'])
            if page['records']:
                from .worker import enqueue
                batch_id = enqueue(conn,item['source_id'],item['authorization_id'],
                    json.dumps(page['records'],ensure_ascii=False),'json',
                    collection_job_item_id=item['id'])
            if selection_duplicates:
                conn.execute('UPDATE veriflow.collection_job_items SET duplicates=duplicates+%s WHERE id=%s',
                             (selection_duplicates,item['id']))
            next_url = page['next_url']
            if batch_id:
                state = 'awaiting_ingest'
                next_attempt = 'now()'
            else:
                state = 'queued' if next_url else 'completed'
                next_attempt = 'now()'
            conn.execute(f'''UPDATE veriflow.collection_job_items SET state=%s,cursor_url=%s,
                next_attempt_at={next_attempt},lease_until=NULL,pages_fetched=pages_fetched+1,
                reviews_retrieved=reviews_retrieved+%s,error_code=NULL,updated_at=now(),
                finished_at=CASE WHEN %s='completed' THEN now() ELSE NULL END
                WHERE id=%s''',
                (state,next_url,len(page['records']),state,item['id']))
            conn.execute('UPDATE veriflow.sources SET next_run_at=now() WHERE id=%s',(item['source_id'],))
            job_state = _refresh_job(conn,item['job_id'])
        return {'job_id':str(item['job_id']),'item_id':str(item['id']),
                'state':state,'job_state':job_state,'pages_fetched':1,
                'reviews_retrieved':len(page['records'])}
    except RateLimited as exc:
        if item['source_id'] == 'lib-reviews':
            with conn.transaction():
                conn.execute("""UPDATE veriflow.sources SET last_status='rate_limited',
                    next_run_at=now()+(%s * interval '1 second') WHERE id=%s""",
                    (exc.retry_after, item['source_id']))
                job_state = _fail_item(conn, item['id'], item['job_id'], 'rate_limited')
            return {'job_id':str(item['job_id']), 'state':'failed',
                    'job_state':job_state, 'error_code':'rate_limited'}
        if item['attempts'] >= 20:
            with conn.transaction():
                job_state = _fail_item(conn,item['id'],item['job_id'],'rate_limit_exhausted')
            return {'job_id':str(item['job_id']),'item_id':str(item['id']),
                    'state':'failed','job_state':job_state,'error_code':'rate_limit_exhausted'}
        with conn.transaction():
            conn.execute('''UPDATE veriflow.collection_job_items SET state='queued',
                next_attempt_at=now()+(%s * interval '1 second'),lease_until=NULL,
                error_code='rate_limited',updated_at=now() WHERE id=%s''',
                (exc.retry_after,item['id']))
            _refresh_job(conn,item['job_id'])
        return {'job_id':str(item['job_id']),'item_id':str(item['id']),
                'state':'rate_limited','error_code':'rate_limited'}
    except SourceUnavailable as exc:
        if item['attempts'] >= 6:
            with conn.transaction():
                job_state = _fail_item(conn,item['id'],item['job_id'],'source_unavailable')
            return {'job_id':str(item['job_id']),'item_id':str(item['id']),
                    'state':'failed','job_state':job_state,'error_code':'source_unavailable'}
        delay = min(3600,60 * (2 ** max(0,item['attempts']-1)))
        with conn.transaction():
            conn.execute('''UPDATE veriflow.collection_job_items SET state='queued',
                next_attempt_at=now()+(%s * interval '1 second'),lease_until=NULL,
                error_code='source_unavailable',updated_at=now() WHERE id=%s''',
                (delay,item['id']))
            _refresh_job(conn,item['job_id'])
        return {'job_id':str(item['job_id']),'item_id':str(item['id']),
                'state':'retry_scheduled','error_code':'source_unavailable'}
    except Exception as exc:
        code = exc.code if isinstance(exc,CollectionError) else 'collection_failed'
        with conn.transaction():
            job_state = _fail_item(conn,item['id'],item['job_id'],code)
        return {'job_id':str(item['job_id']),'item_id':str(item['id']),
                'state':'failed','job_state':job_state,'error_code':code}


def batch_finished(conn, batch, success, inserted=0, duplicates=0, error_code=None):
    item_id = batch.get('collection_job_item_id')
    if not item_id:
        return
    item = conn.execute('SELECT job_id,cursor_url FROM veriflow.collection_job_items WHERE id=%s FOR UPDATE',
                        (item_id,)).fetchone()
    if not item:
        return
    if success:
        state = 'queued' if item['cursor_url'] else 'completed'
        conn.execute('''UPDATE veriflow.collection_job_items SET state=%s,inserted=inserted+%s,
            duplicates=duplicates+%s,error_code=NULL,updated_at=now(),
            finished_at=CASE WHEN %s='completed' THEN now() ELSE NULL END WHERE id=%s''',
            (state,inserted,duplicates,state,item_id))
    else:
        conn.execute('''UPDATE veriflow.collection_job_items SET state='failed',error_code=%s,
            updated_at=now(),finished_at=now() WHERE id=%s''',(error_code or 'collection_failed',item_id))
    _refresh_job(conn,item['job_id'])
