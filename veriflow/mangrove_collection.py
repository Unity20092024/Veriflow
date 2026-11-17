"""Adapter for the reviewed Mangrove CC-BY-4.0 software-review collection."""
import json
from .mangrove_live import SOURCE_ID,BASE,MangroveClient,SOFTWARE
from .free_collection import validate_payload as common_payload
from .admin_ops import product,category
from .connectors import AccessDenied,RateLimited,CollectionError
from .worker import enqueue,run_one


def validate_payload(kind,payload):
    common_payload(kind,dict(payload,mode={'mangrove_discovery':'online_discovery','mangrove_collection':'online_collection'}.get(payload.get('mode'),'')))


def validate_source(conn):
    s=conn.execute('SELECT * FROM veriflow.sources WHERE id=%s FOR SHARE',(SOURCE_ID,)).fetchone()
    if not s or s['url']!=BASE or s['collection_method']!='authorized_api' or not s['enabled'] or s['access_status']!='approved' or not s['full_text_allowed'] or s['required_license_id']!='CC-BY-4.0' or not s['attribution_required']:raise AccessDenied('Enable the reviewed Mangrove source first')
    if s['last_status']=='rate_limited':
        seconds=conn.execute('SELECT greatest(0,extract(epoch FROM %s::timestamptz-now())) AS seconds',(s['next_run_at'],)).fetchone()['seconds']
        if seconds>0:raise RateLimited(int(seconds)+1)
    return s


def grant_for(conn,subject,terms_hash):
    if subject not in SOFTWARE:raise AccessDenied()
    old=conn.execute("SELECT *,expires_at>now() AS valid FROM veriflow.authorizations WHERE source_id=%s AND %s=ANY(product_keys) ORDER BY created_at DESC,id DESC LIMIT 1 FOR SHARE",(SOURCE_ID,subject)).fetchone()
    if old:
        if old['method']!='authorized_api' or old['revoked_at'] or not old['full_text_allowed'] or old['license_id']!='CC-BY-4.0' or old['terms_url']!=BASE+'/terms':raise AccessDenied('Existing scope/permission restricts collection')
        if old['valid']:return old['id']
    return conn.execute("""INSERT INTO veriflow.authorizations(source_id,method,evidence,product_keys,full_text_allowed,approved_by,expires_at,license_id,terms_url)
        VALUES (%s,'authorized_api',%s,%s,true,'reviewed public-source license',now()+interval '7 days','CC-BY-4.0',%s) RETURNING id""",
        (SOURCE_ID,'Published dataset/API reuse and per-review CC-BY-4.0; terms SHA256 '+terms_hash,[subject],BASE+'/terms')).fetchone()['id']


def discover(conn,payload,client=None):
    validate_payload('catalog',payload);validate_source(conn);client=client or MangroveClient();h=client.verify_policy();found=[]
    for r in client.discover(payload['query'],int(payload.get('limit',5))):
        existing=conn.execute('SELECT product_id,expected_name FROM veriflow.source_products WHERE source_id=%s AND external_key=%s FOR UPDATE',(SOURCE_ID,r['url'])).fetchone()
        if existing:
            if existing['expected_name']!=r['name']:raise AccessDenied('Conflicting source-product mapping')
            pid=str(existing['product_id'])
        else:
            pid=product(conn,r['name'],'Not stated by source',categories=[r['category']])
            conn.execute('INSERT INTO veriflow.source_products(source_id,external_key,product_id,expected_name) VALUES (%s,%s,%s,%s)',(SOURCE_ID,r['url'],pid,r['name']))
        cid=category(conn,r['category']);conn.execute('INSERT INTO veriflow.product_categories VALUES (%s,%s) ON CONFLICT DO NOTHING',(pid,cid))
        grant_for(conn,r['url'],h);found.append(dict(product_id=pid,name=r['name'],source_url=r['url'],category=r['category']))
    conn.execute("UPDATE veriflow.sources SET last_status='discovered',last_run_at=now(),failures=0 WHERE id=%s",(SOURCE_ID,))
    return dict(status='discovered',products=found,product_count=len(found),requests=client.requests,terms_hash=h)


def collect(conn,payload,client=None):
    validate_payload('collection',payload);validate_source(conn)
    pid=payload.get('product_id','');cid=payload.get('category_id','')
    mappings=conn.execute("""SELECT external_key,expected_name FROM veriflow.source_products sp WHERE source_id=%s
        AND (%s='' OR product_id=CAST(NULLIF(%s,'') AS uuid))
        AND (%s='' OR EXISTS(SELECT 1 FROM veriflow.product_categories pc WHERE pc.product_id=sp.product_id AND pc.category_id=CAST(NULLIF(%s,'') AS uuid))) ORDER BY external_key LIMIT 6""",(SOURCE_ID,pid,pid,cid,cid)).fetchall()
    if not 1<=len(mappings)<=5:raise AccessDenied('Choose one to five mapped software products')
    client=client or MangroveClient();h=client.verify_policy();retrieved=inserted=duplicates=pages=skipped=0
    maximum=int(payload.get('max_reviews',20));truncated=False
    for m in mappings:
        if retrieved>=maximum:truncated=True;break
        aid=grant_for(conn,m['external_key'],h);data=client.collect(m['external_key'],m['expected_name'],maximum-retrieved)
        pages+=data['pages'];skipped+=data.get('skipped',0);truncated=truncated or data['truncated']
        if not data['records']:continue
        retrieved+=len(data['records']);enqueue(conn,SOURCE_ID,aid,json.dumps(data['records']),'json')
        conn.execute('UPDATE veriflow.sources SET next_run_at=now() WHERE id=%s',(SOURCE_ID,))
        result=run_one(conn,source_id=SOURCE_ID,grant_id=aid)
        if not result or result['status']!='success':raise CollectionError()
        inserted+=result['inserted'];duplicates+=result['duplicates']
    return dict(status='retrieved',source=SOURCE_ID,retrieved=retrieved,inserted=inserted,duplicates=duplicates,pages=pages,skipped=skipped,truncated=truncated,requests=client.requests,terms_hash=h)
