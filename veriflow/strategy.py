"""Prospective collection priorities; never a permanent review-storage limit."""
import hashlib
import json
import uuid
from dataclasses import asdict

from .connectors import AccessDenied, CollectionError, RateLimited, normalize

MODES = ('breadth_first', 'balanced', 'depth_first')
DEFAULT_TARGETS = {'breadth_first': 5, 'balanced': 10, 'depth_first': 30}
RESEARCH_MIN_TEXT_REVIEWS = 3


def preferences(mode='breadth_first', target=None):
    if mode not in MODES:
        raise CollectionError('Unknown collection strategy')
    if target in (None, ''):
        target = DEFAULT_TARGETS[mode]
    try:
        if isinstance(target, bool) or int(target) != float(target):
            raise ValueError()
        target = int(target)
    except (ValueError, TypeError, OverflowError):
        raise CollectionError('Invalid per-product target') from None
    if not 1 <= target <= 10000:
        raise CollectionError('Per-product target must be between 1 and 10000')
    return mode, target


def review_fingerprint(product_id, review):
    """Exactly the existing ingest identity, including distinct licensed authors."""
    material = ([str(product_id), normalize(review.text), review.published_at]
                if review.text else [str(product_id), review.original_url, review.external_id])
    base = hashlib.sha256(json.dumps(material).encode()).hexdigest()
    fingerprint = base
    if review.license_metadata:
        fingerprint = hashlib.sha256(json.dumps([
            base, review.license_metadata['public_credit'],
            review.license_metadata['attribution_url'],
        ]).encode()).hexdigest()
    return fingerprint, base if review.text else None


def select_unique(records, existing, product_id, allowance):
    """Select a small unique slice, not the first N possibly-duplicate entries."""
    fingerprints = {r['fingerprint'] for r in existing}
    external_ids = {r['external_id'] for r in existing}
    urls = {r['original_url'] for r in existing}
    selected, duplicates = [], 0
    for record in records:
        fingerprint, _ = review_fingerprint(product_id, record)
        if (fingerprint in fingerprints or record.external_id in external_ids
                or record.original_url in urls):
            duplicates += 1
            continue
        if len(selected) >= max(0, allowance):
            continue
        fingerprints.add(fingerprint)
        external_ids.add(record.external_id)
        urls.add(record.original_url)
        row = asdict(record)
        row['review_text'] = row.pop('text')
        selected.append(row)
    return selected, duplicates


def select_page(conn, item, source, grant, records):
    """Revalidate the entire page before selecting a bounded per-product slice."""
    from .worker import CONNECTORS, validate_products
    conn.execute('SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)',
                 ('strategy-job:'+str(item['job_id']),))
    root = conn.execute('SELECT coalesce(canonical_product_id,id) AS id '
                        'FROM veriflow.products WHERE id=%s',
                        (item['product_id'],)).fetchone()['id']
    conn.execute('SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)', (str(root),))
    normalized = CONNECTORS.get(source['collection_method'], source).collect(
        json.dumps(records), 'json', source, grant)
    mappings = validate_products(conn, source, grant, normalized)
    if any(str(pid) != str(item['product_id']) for pid in mappings.values()):
        raise AccessDenied('Collection page crossed its product scope')
    count = conn.execute('SELECT reviews FROM veriflow.product_evidence WHERE product_id=%s',
                         (root,)).fetchone()['reviews']
    # Only one new-strategy item for this identity may await ingestion at a time.
    pending = conn.execute('''SELECT 1 FROM veriflow.collection_job_items i
      JOIN veriflow.products p ON p.id=i.product_id
      WHERE coalesce(p.canonical_product_id,p.id)=%s
        AND i.state='awaiting_ingest' AND i.id<>%s LIMIT 1''', (root,item['id'])).fetchone()
    if pending:
        raise RateLimited(60)
    existing = conn.execute('''SELECT r.external_id,r.original_url,r.fingerprint
      FROM veriflow.reviews r JOIN veriflow.products p ON p.id=r.product_id
      WHERE r.source_id=%s AND coalesce(p.canonical_product_id,p.id)=%s''',
      (source['id'],root)).fetchall()
    job_reserved = conn.execute('''SELECT
      coalesce((SELECT sum(inserted) FROM veriflow.collection_job_items WHERE job_id=%s),0)
      +coalesce((SELECT sum(jsonb_array_length(b.records)) FROM veriflow.import_batches b
        JOIN veriflow.collection_job_items i ON i.id=b.collection_job_item_id
        WHERE i.job_id=%s AND b.status='pending'),0) AS n''',
        (item['job_id'],item['job_id'])).fetchone()['n']
    return select_unique(normalized, existing, item['product_id'],
                         max(0,min(item['target_reviews']-count,500-job_reserved)))


def resolve_discovered_product(conn, name):
    """NFKC/case/space aliases resolve to one root; ambiguity is never guessed."""
    matches = {str(p['root_id']) for p in conn.execute('''SELECT name,
      coalesce(canonical_product_id,id) AS root_id FROM veriflow.products''').fetchall()
      if normalize(p['name']) == normalize(name)}
    if len(matches) > 1:
        raise AccessDenied('Ambiguous existing product identity')
    return next(iter(matches), None)


def task_priority(mode, reviews, category_coverage, task_id):
    """Round-robin poorly covered identities/categories before revisiting depth."""
    weight = reviews if mode == 'breadth_first' else reviews//5 if mode == 'balanced' else -reviews
    return weight, category_coverage, task_id


def bounded_task(conn, batch_id, mode, target):
    """Only newly strategy-tagged batches use this; legacy batches never enter."""
    rows = conn.execute('''SELECT t.*,coalesce(e.reviews,0) AS evidence_count,p.category,
      coalesce((SELECT count(DISTINCT bp.product_id) FROM veriflow.free_batch_products bp
        JOIN veriflow.products product ON product.id=bp.product_id
        JOIN veriflow.product_evidence pe ON pe.product_id=coalesce(product.canonical_product_id,product.id)
        WHERE bp.batch_id=t.batch_id AND bp.category=p.category AND pe.reviews>0),0) AS category_coverage
      FROM veriflow.free_batch_tasks t LEFT JOIN veriflow.free_batch_products p
        ON p.batch_id=t.batch_id AND p.url=t.data->>'product_url'
      LEFT JOIN veriflow.products product ON product.id=p.product_id
      LEFT JOIN veriflow.product_evidence e ON e.product_id=coalesce(product.canonical_product_id,product.id)
      WHERE t.batch_id=%s AND t.state='pending' ORDER BY t.id''', (batch_id,)).fetchall()
    eligible = []
    for row in rows:
        if row['kind'] != 'discover' and row['evidence_count'] >= target:
            conn.execute("UPDATE veriflow.free_batch_tasks SET state='done' WHERE id=%s",
                         (row['id'],))
        else:
            eligible.append(row)
    return min(eligible, key=lambda row: (
        0 if row['kind']=='discover' else 1,
        *task_priority(mode,row['evidence_count'],row['category_coverage'],row['id']),
    ), default=None)


def link_identity(conn, alias_id, canonical_id):
    """Owner-confirmed, non-destructive identity correction. Reviews stay put."""
    try:
        alias_id, canonical_id = str(uuid.UUID(alias_id)), str(uuid.UUID(canonical_id))
    except (ValueError, TypeError, AttributeError):
        raise CollectionError('Invalid product identity') from None
    if alias_id == canonical_id:
        raise CollectionError('Choose two different products')
    conn.execute('SELECT pg_advisory_xact_lock(17651222)')
    rows = conn.execute('SELECT id,canonical_product_id FROM veriflow.products '
                        'WHERE id IN (%s,%s) ORDER BY id FOR UPDATE',
                        (alias_id,canonical_id)).fetchall()
    if len(rows) != 2 or any(r['canonical_product_id'] for r in rows):
        raise CollectionError('Link only canonical products; alias chains are not allowed')
    active = conn.execute('''SELECT 1 FROM veriflow.collection_job_items
      WHERE product_id IN (%s,%s) AND state IN ('queued','fetching','awaiting_ingest')
      UNION ALL SELECT 1 FROM veriflow.free_batch_products p
      JOIN veriflow.free_batches b ON b.id=p.batch_id
      WHERE p.product_id IN (%s,%s) AND b.state='running' LIMIT 1''',
      (alias_id,canonical_id,alias_id,canonical_id)).fetchone()
    if active:
        raise CollectionError('Do not change product identities during active collection')
    conn.execute('UPDATE veriflow.products SET canonical_product_id=%s '
                 'WHERE id=%s OR canonical_product_id=%s',
                 (canonical_id,alias_id,alias_id))
    conn.execute('''UPDATE veriflow.products SET research_requested_at=coalesce(
      research_requested_at,(SELECT min(research_requested_at) FROM veriflow.products
                             WHERE canonical_product_id=%s)) WHERE id=%s''',
      (canonical_id,canonical_id))


def queue_research(conn, product_id):
    try:
        product_id = str(uuid.UUID(product_id))
    except (ValueError, TypeError, AttributeError):
        raise CollectionError('Invalid research product') from None
    evidence = conn.execute('SELECT reviews FROM veriflow.product_evidence '
                            'WHERE product_id=%s', (product_id,)).fetchone()
    if not evidence or evidence['reviews'] < 1:
        raise AccessDenied('Collected evidence is required for research')
    conn.execute('UPDATE veriflow.products SET research_requested_at=now() WHERE id=%s',
                 (product_id,))


# NULL strategy takes the original FIFO order. New modes rotate using actual
# software-category coverage, never the source registry's broad source types.
CLAIM_ORDER = '''CASE WHEN j.strategy IS NULL THEN i.next_attempt_at END,
  CASE WHEN j.strategy='breadth_first' THEN coalesce(e.reviews,0)
       WHEN j.strategy='balanced' THEN coalesce(e.reviews,0)/5
       WHEN j.strategy='depth_first' THEN -coalesce(e.reviews,0) END,
  CASE WHEN j.strategy IS NOT NULL THEN coalesce(category_coverage.covered,0) END,
  CASE WHEN j.strategy IS NOT NULL THEN i.pages_fetched END,
  CASE WHEN j.strategy IS NOT NULL THEN coalesce(e.independent_sources,0) END,
  i.next_attempt_at,i.created_at,i.id'''

CLAIM_JOINS = '''JOIN veriflow.products product ON product.id=i.product_id
  LEFT JOIN veriflow.product_evidence e
    ON e.product_id=coalesce(product.canonical_product_id,product.id)
  LEFT JOIN LATERAL (
    SELECT min(coverage.covered) AS covered FROM veriflow.product_categories pc
    JOIN veriflow.products member ON member.id=pc.product_id
    JOIN LATERAL (
      SELECT count(DISTINCT pe.product_id) AS covered FROM veriflow.product_categories peers
      JOIN veriflow.products pp ON pp.id=peers.product_id
      JOIN veriflow.product_evidence pe ON pe.product_id=coalesce(pp.canonical_product_id,pp.id)
      WHERE peers.category_id=pc.category_id AND pe.reviews>0
    ) coverage ON true
    WHERE coalesce(member.canonical_product_id,member.id)=coalesce(product.canonical_product_id,product.id)
  ) category_coverage ON true'''
