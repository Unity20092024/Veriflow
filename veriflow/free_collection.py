"""Adapt the reviewed upstream free collector to the existing persistent queue.

Parser/client: Unity20092024/Veriflow feature/step-1-private-collection.
This activation is deliberately narrower than upstream's discovery UI:
Firefox only, two operator-requested jobs, one review per job, no recurrence.
"""
from .connectors import AccessDenied
from .libreviews_live import BASE, SOURCE_ID, LibreReviewsClient

PRODUCT_URL = BASE + '/mozilla-firefox'
PRODUCT_NAME = 'Mozilla Firefox'
PRODUCT_CATEGORY = 'Web browsers'
MAX_TEST_JOBS = 2


def validate_scope(source, grant, mapping):
    if (source['id'] != SOURCE_ID or source['url'] != BASE
            or source['collection_method'] != 'permitted_crawl'
            or not source['enabled'] or source['access_status'] != 'approved'
            or source.get('required_license_id') != 'CC-BY-SA-4.0'
            or not source.get('attribution_required') or not source['full_text_allowed']
            or grant['method'] != 'permitted_crawl' or not grant['full_text_allowed']
            or grant.get('license_id') != 'CC-BY-SA-4.0'
            or grant.get('terms_url') != BASE + '/terms'
            or list(grant['product_keys']) != [PRODUCT_URL]
            or mapping['external_key'] != PRODUCT_URL
            or mapping['expected_name'] != PRODUCT_NAME):
        raise AccessDenied('Only the approved attributed Firefox test is enabled')


def reserve_test_job(conn, target):
    """Serialize admissions so two simultaneous requests cannot exceed approval."""
    source = conn.execute('SELECT * FROM veriflow.sources WHERE id=%s FOR UPDATE',
                          (SOURCE_ID,)).fetchone()
    from .worker import authorization
    grant = authorization(conn, SOURCE_ID, target['authorization_id'], 'permitted_crawl')
    validate_scope(source, grant, target)
    count = conn.execute('''SELECT count(*) AS count FROM veriflow.collection_job_items
        WHERE source_id=%s''', (SOURCE_ID,)).fetchone()['count']
    if count >= MAX_TEST_JOBS:
        raise AccessDenied('The two approved free test runs have been used; further collection needs approval')


def fetch_test_page(source, grant, mapping, cursor_url, client=None):
    validate_scope(source, grant, mapping)
    if cursor_url != PRODUCT_URL:
        raise AccessDenied('Firefox pilot does not follow additional pages')
    client = client or LibreReviewsClient()
    result = client.collect(PRODUCT_URL, PRODUCT_NAME, max_reviews=1, max_pages=1)
    # No recurring or follow-up page: one bounded durable request only.
    return {'records': result['records'], 'next_url': None, 'page_url': PRODUCT_URL}


def activate_firefox(conn, client=None):
    """Explicit operator action; never called from the worker or server startup.

    Reuses upstream install_source/grant_for/discover policy, limited to the
    exact test approved by the administrator. Existing grants are not renewed.
    """
    client = client or LibreReviewsClient()
    terms_hash = client.verify_policy()
    candidates = client.discover('Firefox', limit=5)
    if not any(p['url'] == PRODUCT_URL and p['name'] == PRODUCT_NAME
               and p['category'] == PRODUCT_CATEGORY for p in candidates):
        raise AccessDenied('Live source metadata did not identify the approved Firefox product')
    with conn.transaction():
        conn.execute('''INSERT INTO veriflow.sources
            (id,name,url,category,collection_method,access_status,enabled,full_text_allowed,
             provenance,policy_notes,required_license_id,attribution_required)
            VALUES (%s,'lib.reviews',%s,'software_review_directory','permitted_crawl',
             'pending_authorization',false,false,'Reviewed free source terms',
             'Firefox-only pilot: two requested runs, one review each; no recurrence. CC BY-SA 4.0.',
             'CC-BY-SA-4.0',true) ON CONFLICT(id) DO NOTHING''', (SOURCE_ID, BASE))
        source = conn.execute('SELECT * FROM veriflow.sources WHERE id=%s FOR UPDATE',
                              (SOURCE_ID,)).fetchone()
        if (source['url'] != BASE or source['collection_method'] != 'permitted_crawl'
                or source.get('required_license_id') != 'CC-BY-SA-4.0'
                or not source.get('attribution_required')):
            raise AccessDenied('Existing source configuration conflicts')
        mapping = conn.execute('''SELECT * FROM veriflow.source_products
            WHERE source_id=%s AND external_key=%s FOR UPDATE''',
            (SOURCE_ID, PRODUCT_URL)).fetchone()
        if mapping:
            if mapping['expected_name'] != PRODUCT_NAME:
                raise AccessDenied('Existing product mapping conflicts')
            product_id = mapping['product_id']
        else:
            products = conn.execute('''SELECT id FROM veriflow.products
                WHERE lower(trim(name))=lower(%s)''', (PRODUCT_NAME,)).fetchall()
            if len(products) > 1:
                raise AccessDenied('Ambiguous existing product')
            product_id = products[0]['id'] if products else conn.execute('''INSERT INTO
                veriflow.products(name,vendor) VALUES (%s,'Not stated by source') RETURNING id''',
                (PRODUCT_NAME,)).fetchone()['id']
            conn.execute('''INSERT INTO veriflow.source_products
                (source_id,external_key,product_id,expected_name) VALUES (%s,%s,%s,%s)''',
                (SOURCE_ID, PRODUCT_URL, product_id, PRODUCT_NAME))
        category_id = conn.execute('''INSERT INTO veriflow.categories(name) VALUES (%s)
            ON CONFLICT(lower(trim(name))) DO UPDATE SET name=veriflow.categories.name RETURNING id''',
            (PRODUCT_CATEGORY,)).fetchone()['id']
        conn.execute('INSERT INTO veriflow.product_categories VALUES (%s,%s) ON CONFLICT DO NOTHING',
                     (product_id, category_id))
        previous = conn.execute('''SELECT * FROM veriflow.authorizations WHERE source_id=%s
            AND method='permitted_crawl' ORDER BY created_at DESC,id DESC LIMIT 1 FOR SHARE''',
            (SOURCE_ID,)).fetchone()
        if previous:
            valid = conn.execute('SELECT %s::timestamptz>now() AS valid',
                                 (previous['expires_at'],)).fetchone()['valid']
            if previous['revoked_at'] is not None or not valid:
                raise AccessDenied('Existing authorization is revoked or expired; do not renew automatically')
            grant = previous
        else:
            grant = conn.execute('''INSERT INTO veriflow.authorizations
                (source_id,method,evidence,product_keys,full_text_allowed,approved_by,
                 expires_at,license_id,terms_url)
                VALUES (%s,'permitted_crawl',%s,%s,true,'Single administrator approved bounded Firefox test',
                 now()+interval '7 days','CC-BY-SA-4.0',%s) RETURNING *''',
                (SOURCE_ID, 'Published mining/reuse permission; terms SHA256 '+terms_hash
                 +'; maximum two requested runs, one review each; no recurring schedule',
                 [PRODUCT_URL], BASE+'/terms')).fetchone()
        source = dict(source, enabled=True, access_status='approved', full_text_allowed=True)
        validate_scope(source, grant, {'external_key': PRODUCT_URL, 'expected_name': PRODUCT_NAME})
        conn.execute("""UPDATE veriflow.sources SET enabled=true,access_status='approved',
            full_text_allowed=true WHERE id=%s""", (SOURCE_ID,))
    return {'source': SOURCE_ID, 'product_id': str(product_id),
            'category': PRODUCT_CATEGORY, 'max_reviews_per_job': 1,
            'max_jobs': MAX_TEST_JOBS, 'terms_hash': terms_hash}
