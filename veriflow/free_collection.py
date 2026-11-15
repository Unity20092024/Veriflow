"""Connect the one reviewed free source to persistent discovery/collection jobs."""
import json
from pathlib import Path
from psycopg.types.json import Jsonb
from .connectors import AccessDenied,CollectionError,RateLimited
from .admin_ops import product,category,identifier
from .libreviews_live import LibreReviewsClient,SOURCE_ID,BASE,public_url


def install_source(conn,enable=False,source_id=SOURCE_ID):
    spec=next(s for s in json.loads((Path(__file__).resolve().parents[1]/'data/free-sources.json').read_text()) if s['id']==source_id)
    conn.execute('''INSERT INTO veriflow.sources
        (id,name,url,category,collection_method,access_status,enabled,full_text_allowed,provenance,policy_notes,required_license_id,attribution_required)
        VALUES (%s,%s,%s,%s,%s,'pending_authorization',false,false,%s,%s,%s,true) ON CONFLICT(id) DO NOTHING''',
        (spec['id'],spec['name'],spec['url'],spec['category'],spec['collection_method'],spec['provenance'],spec['policy_notes'],spec['required_license_id']))
    source=conn.execute('SELECT * FROM veriflow.sources WHERE id=%s FOR SHARE',(source_id,)).fetchone()
    if source['url']!=spec['url'] or source['collection_method']!=spec['collection_method'] or source['required_license_id']!=spec['required_license_id'] or not source['attribution_required']:raise AccessDenied('Existing source configuration conflicts')
    if enable:
        conn.execute("UPDATE veriflow.sources SET enabled=true,access_status='approved',full_text_allowed=true WHERE id=%s",(source_id,))
    return source


def validate_source(conn):
    s=conn.execute('SELECT * FROM veriflow.sources WHERE id=%s FOR SHARE',(SOURCE_ID,)).fetchone()
    if not s or s['url']!=BASE or s['collection_method']!='permitted_crawl' or not s['enabled'] or s['access_status']!='approved' or not s['full_text_allowed'] or s['required_license_id']!='CC-BY-SA-4.0' or not s['attribution_required']:raise AccessDenied('Enable the reviewed free source first')
    if s['last_status']=='rate_limited':
        remaining=conn.execute('SELECT greatest(0,extract(epoch FROM %s::timestamptz-now())) AS seconds',(s['next_run_at'],)).fetchone()['seconds']
        if remaining>0:raise RateLimited(int(remaining)+1)
    return s


def validate_payload(kind,payload):
    mode=payload.get('mode')
    if kind=='catalog' and mode=='online_discovery':
        if set(payload)-{'mode','query','limit'} or not isinstance(payload.get('query'),str) or not 1<=len(payload['query'].strip())<=200 or not 1<=int(payload.get('limit',5))<=5:raise CollectionError('Invalid discovery request')
    elif kind=='collection' and mode=='online_collection':
        if set(payload)-{'mode','product_id','category_id','max_reviews'} or not 1<=int(payload.get('max_reviews',20))<=20:raise CollectionError('Invalid collection limit')
        if bool(payload.get('product_id'))==bool(payload.get('category_id')):raise CollectionError('Select one product or category')
        identifier(payload.get('product_id') or payload.get('category_id'))
    else:raise CollectionError('Unsupported online operation')


def grant_for(conn,url,terms_hash):
    url=public_url(url)
    previous=conn.execute('''SELECT * FROM veriflow.authorizations WHERE source_id=%s AND method='permitted_crawl'
        AND %s=ANY(product_keys) ORDER BY created_at DESC,id DESC LIMIT 1 FOR SHARE''',(SOURCE_ID,url)).fetchone()
    if previous:
        if previous['revoked_at'] is not None or not previous['full_text_allowed'] or previous['license_id']!='CC-BY-SA-4.0' or previous['terms_url']!=BASE+'/terms':raise AccessDenied('Existing product authorization restricts collection')
        valid=conn.execute('SELECT %s::timestamptz>now() AS valid',(previous['expires_at'],)).fetchone()['valid']
        if valid:return previous['id']
    return conn.execute('''INSERT INTO veriflow.authorizations
        (source_id,method,evidence,product_keys,full_text_allowed,approved_by,expires_at,license_id,terms_url)
        VALUES (%s,'permitted_crawl',%s,%s,true,'reviewed public-source license',now()+interval '7 days','CC-BY-SA-4.0',%s) RETURNING id''',
        (SOURCE_ID,'Published mining/reuse permission and CC BY-SA 4.0; terms SHA256 '+terms_hash,[url],BASE+'/terms')).fetchone()['id']


def discover(conn,payload,client=None):
    validate_payload('catalog',payload);validate_source(conn)
    client=client or LibreReviewsClient();hash_=client.verify_policy()
    candidates=client.discover(payload['query'],int(payload.get('limit',5)))
    found=[]
    for entry in candidates:
        existing=conn.execute('''SELECT sp.product_id,sp.expected_name FROM veriflow.source_products sp
            WHERE sp.source_id=%s AND sp.external_key=%s FOR UPDATE''',(SOURCE_ID,entry['url'])).fetchone()
        if existing:
            if existing['expected_name'].casefold()!=entry['name'].casefold():raise AccessDenied('Existing source mapping differs')
            pid=str(existing['product_id'])
        else:
            pid=product(conn,entry['name'],'Not stated by source',categories=[entry['category']])
            conn.execute('INSERT INTO veriflow.source_products(source_id,external_key,product_id,expected_name) VALUES (%s,%s,%s,%s)',(SOURCE_ID,entry['url'],pid,entry['name']))
        cid=category(conn,entry['category'])
        conn.execute('INSERT INTO veriflow.product_categories VALUES (%s,%s) ON CONFLICT DO NOTHING',(pid,cid))
        grant_for(conn,entry['url'],hash_)
        found.append(dict(product_id=pid,name=entry['name'],source_url=entry['url'],category=entry['category']))
    conn.execute("UPDATE veriflow.sources SET last_status='discovered',last_run_at=now(),failures=0 WHERE id=%s",(SOURCE_ID,))
    return dict(status='discovered',products=found,product_count=len(found),requests=client.requests,terms_hash=hash_)


def collect(conn,payload,client=None):
    from .worker import enqueue,run_one
    validate_payload('collection',payload);validate_source(conn)
    args=(payload.get('product_id',''),payload.get('product_id',''),payload.get('category_id',''),payload.get('category_id',''),SOURCE_ID)
    mappings=conn.execute('''SELECT DISTINCT sp.external_key,sp.expected_name,sp.product_id
        FROM veriflow.source_products sp WHERE (%s='' OR sp.product_id=CAST(NULLIF(%s,'') AS uuid))
        AND (%s='' OR EXISTS(SELECT 1 FROM veriflow.product_categories pc WHERE pc.product_id=sp.product_id AND pc.category_id=CAST(NULLIF(%s,'') AS uuid)))
        AND sp.source_id=%s ORDER BY sp.external_key LIMIT 6''',args).fetchall()
    if not mappings:raise AccessDenied('Discover an eligible software product first')
    if len(mappings)>5:raise CollectionError('Select at most five mapped products')
    client=client or LibreReviewsClient();hash_=client.verify_policy()
    count=inserted=duplicates=pages=0;truncated=False;maximum=int(payload.get('max_reviews',20))
    for mapping in mappings:
        if count>=maximum:truncated=True;break
        aid=grant_for(conn,mapping['external_key'],hash_)
        data=client.collect(mapping['external_key'],mapping['expected_name'],maximum-count)
        pages+=data['pages'];truncated=truncated or data['truncated']
        if not data['records']:continue
        count+=len(data['records'])
        enqueue(conn,SOURCE_ID,aid,json.dumps(data['records']),'json')
        conn.execute('UPDATE veriflow.sources SET next_run_at=now() WHERE id=%s',(SOURCE_ID,))
        result=run_one(conn,source_id=SOURCE_ID,grant_id=aid)
        if not result or result['status']!='success':raise CollectionError('Validated retrieval failed ingestion')
        inserted+=result['inserted'];duplicates+=result['duplicates']
    return dict(status='retrieved',retrieved=count,inserted=inserted,duplicates=duplicates,pages=pages,
                requests=client.requests,truncated=truncated,terms_hash=hash_,source=SOURCE_ID)
