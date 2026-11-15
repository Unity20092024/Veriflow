"""Validated private write operations; never create source permissions implicitly."""
import json
from uuid import UUID
from urllib.parse import urlsplit
from psycopg.types.json import Jsonb
from .connectors import CollectionError,AccessDenied
from .worker import authorization


def clean(value,limit=200):
    value=' '.join(str(value or '').split())
    if not value or len(value)>limit:raise CollectionError('Invalid field length')
    return value


def identifier(value):
    try:return str(UUID(str(value)))
    except (ValueError,TypeError,AttributeError):raise CollectionError('Invalid identifier') from None


def category(conn,name):
    name=clean(name,120)
    return conn.execute('''INSERT INTO veriflow.categories(name) VALUES (%s)
        ON CONFLICT(lower(trim(name))) DO UPDATE SET name=veriflow.categories.name RETURNING id''',(name,)).fetchone()['id']


def product(conn,name,vendor,website='',categories=()):
    name,vendor=clean(name),clean(vendor)
    if website:
        p=urlsplit(website)
        if p.scheme!='https' or not p.hostname or p.username or p.password or len(website)>2000:raise CollectionError('Invalid website')
    if len(categories)>20:raise CollectionError('Too many categories')
    row=conn.execute('''INSERT INTO veriflow.products(name,vendor,website) VALUES (%s,%s,%s)
        ON CONFLICT(lower(trim(name)),lower(trim(vendor))) DO UPDATE
        SET website=coalesce(veriflow.products.website,excluded.website) RETURNING id''',(name,vendor,website or None)).fetchone()
    for name in categories:
        cid=category(conn,name)
        conn.execute('INSERT INTO veriflow.product_categories VALUES (%s,%s) ON CONFLICT DO NOTHING',(row['id'],cid))
    return str(row['id'])


def source_settings(conn,ids,operation,seconds):
    ids=sorted(set(ids))
    if not 1<=len(ids)<=100 or operation not in ('pause','resume','schedule'):raise CollectionError('Invalid source selection')
    seconds=int(seconds)
    if not 60<=seconds<=31536000:raise CollectionError('Invalid schedule')
    rows=conn.execute('SELECT * FROM veriflow.sources WHERE id=ANY(%s) ORDER BY id FOR UPDATE',(ids,)).fetchall()
    if len(rows)!=len(ids):raise CollectionError('Unknown source')
    for s in rows:
        if operation=='resume':
            grant=conn.execute('''SELECT 1 FROM veriflow.authorizations WHERE source_id=%s AND method=%s
                AND revoked_at IS NULL AND expires_at>now() LIMIT 1''',(s['id'],s['collection_method'])).fetchone()
            free=s['id']=='lib-reviews' and s['url']=='https://lib.reviews' and s['collection_method']=='permitted_crawl'
            if s['access_status']!='approved' or not grant or (s['collection_method'] not in ('approved_import','apify') and not free):
                raise AccessDenied('Source is not configured and approved')
        conn.execute('''UPDATE veriflow.sources SET schedule_seconds=%s,
            enabled=CASE WHEN %s='pause' THEN false WHEN %s='resume' THEN true ELSE enabled END WHERE id=%s''',
            (max(seconds,s['minimum_interval_seconds']),operation,operation,s['id']))
    conn.execute('''INSERT INTO veriflow.admin_settings(key,value) VALUES ('source_preferences',%s)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=now()''',
        (Jsonb(dict(source_ids=ids,schedule_seconds=seconds)),))


def request_job(conn,kind,payload,request_key,source_id=None,grant_id=None):
    key=identifier(request_key)
    if kind not in ('collection','catalog','export'):raise CollectionError('Unknown job type')
    previous=conn.execute('SELECT id FROM veriflow.admin_jobs WHERE request_key=%s',(key,)).fetchone()
    if previous:return str(previous['id'])
    if len(json.dumps(payload).encode())>5_000_000:raise CollectionError('Job exceeds input limit')
    if kind!='export':
        s=conn.execute('SELECT * FROM veriflow.sources WHERE id=%s FOR SHARE',(source_id,)).fetchone()
        if not s or not s['enabled'] or s['access_status']!='approved' or s['category']=='market_research':raise AccessDenied('Source is not enabled and approved')
        if payload.get('mode') in ('online_discovery','online_collection'):
            from .free_collection import validate_source,validate_payload
            if source_id!='lib-reviews':raise AccessDenied()
            validate_source(conn);validate_payload(kind,payload);grant_id=None
        else:
            grant_id=identifier(grant_id)
            authorization(conn,source_id,grant_id,s['collection_method'])
            if kind=='catalog' and s['collection_method']!='approved_import':raise AccessDenied()
            if kind=='collection' and s['collection_method'] not in ('approved_import','apify'):raise AccessDenied('Connector unavailable')
    row=conn.execute('''INSERT INTO veriflow.admin_jobs(kind,payload,request_key,source_id,authorization_id)
        VALUES (%s,%s,%s,%s,%s) ON CONFLICT(request_key) DO UPDATE SET request_key=excluded.request_key RETURNING id''',
        (kind,Jsonb(payload),key,source_id,grant_id)).fetchone()
    return str(row['id'])


def discover_catalog(conn,source_id,grant_id,rows):
    if not isinstance(rows,list) or not 1<=len(rows)<=1000:raise CollectionError('Catalog limit is 1000 records per batch')
    source=conn.execute('SELECT * FROM veriflow.sources WHERE id=%s FOR SHARE',(source_id,)).fetchone()
    if not source or not source['enabled'] or source['access_status']!='approved' or source['collection_method']!='approved_import':raise AccessDenied()
    grant=authorization(conn,source_id,grant_id,'approved_import')
    count=0
    for r in rows:
        if not isinstance(r,dict) or set(r)-{'external_key','name','vendor','website','categories'}:raise CollectionError('Unexpected catalog fields')
        key=clean(r.get('external_key'),200)
        if key not in grant['product_keys']:raise AccessDenied('Product outside approved catalog scope')
        cats=r.get('categories',[])
        if not isinstance(cats,list):raise CollectionError('Categories must be a list')
        # A known source key cannot silently move to another software product.
        mapping=conn.execute('''SELECT sp.product_id,p.name,p.vendor FROM veriflow.source_products sp
            JOIN veriflow.products p ON p.id=sp.product_id WHERE source_id=%s AND external_key=%s FOR UPDATE OF sp''',(source_id,key)).fetchone()
        name,vendor=clean(r.get('name')),clean(r.get('vendor'))
        if mapping and (mapping['name'].casefold()!=name.casefold() or mapping['vendor'].casefold()!=vendor.casefold()):raise AccessDenied('Existing product association conflicts')
        pid=product(conn,name,vendor,r.get('website',''),cats)
        conn.execute('''INSERT INTO veriflow.source_products(source_id,external_key,product_id,expected_name)
            VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING''',(source_id,key,pid,name))
        count+=1
    return dict(products_processed=count)


def record_permission(conn,source_id,method,evidence,product_keys,expires_at,full_text,reviewed,storage_confirmed,license_id='',terms_url=''):
    from datetime import datetime,timezone,timedelta
    if not reviewed or not evidence or len(evidence.strip())<20:raise AccessDenied('Recorded evidence and explicit source-rule review required')
    if method not in ('approved_import','apify'):raise AccessDenied('Unsupported collection method')
    if full_text and not storage_confirmed:raise AccessDenied('Full-text storage permission required')
    keys=sorted({clean(k,200) for k in product_keys})
    if not 1<=len(keys)<=1000:raise CollectionError('Invalid product scope')
    expiry=datetime.fromisoformat(expires_at.replace('Z','+00:00'))
    if expiry.tzinfo is None or not datetime.now(timezone.utc)<expiry<=datetime.now(timezone.utc)+timedelta(days=366):raise CollectionError('Use a future UTC expiry within one year')
    source=conn.execute('SELECT * FROM veriflow.sources WHERE id=%s FOR UPDATE',(source_id,)).fetchone()
    if not source or source['category']=='market_research':raise AccessDenied()
    if source['required_license_id'] and license_id!=source['required_license_id']:raise AccessDenied('Required source license must match')
    if license_id and license_id not in ('CC-BY-4.0','CC-BY-SA-4.0'):raise CollectionError('Unsupported license identifier')
    if terms_url:
        p=urlsplit(terms_url);host=urlsplit(source['url']).hostname
        if p.scheme!='https' or not p.hostname or (p.hostname!=host and not p.hostname.endswith('.'+host)) or p.username or p.password:raise AccessDenied('Terms must reference the source')
    if license_id and not terms_url:raise AccessDenied('Licensed sources require a terms reference')
    conn.execute('''INSERT INTO veriflow.authorizations(source_id,method,evidence,product_keys,full_text_allowed,approved_by,expires_at,license_id,terms_url)
        VALUES (%s,%s,%s,%s,%s,'private administrator',%s,%s,%s)''',(source_id,method,evidence[:10000],keys,full_text,expiry,license_id or None,terms_url or None))
    # Deliberately pause; recording evidence is separate from resuming collection.
    conn.execute("UPDATE veriflow.sources SET collection_method=%s,access_status='approved',enabled=false,full_text_allowed=%s WHERE id=%s",(method,full_text,source_id))
