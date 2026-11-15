"""Mobile administration screens and validated POST dispatch."""
import csv
import io
import json
from uuid import uuid4
from html import escape as e
from .admin_ops import product,category,identifier,source_settings,request_job,clean
from .connectors import CollectionError


def hidden(name,value):return '<input type="hidden" name="'+name+'" value="'+e(str(value),quote=True)+'">'
def form(action,csrf,body):return '<form method="post"'+(' enctype="multipart/form-data"' if action in ('/actions/import','/actions/catalog') else '')+' action="'+action+'">'+hidden('csrf',csrf)+hidden('request_key',uuid4())+body+'</form>'
def field(name,label,kind='text',value=''):return '<label>'+label+'<input name="'+name+'" type="'+kind+'" value="'+e(str(value),quote=True)+'" required></label>'
def options(rows,key='id',label='name'):return ''.join('<option value="'+e(str(r[key]),quote=True)+'">'+e(str(r[label]))+'</option>' for r in rows)


def screen(conn,path,params,csrf):
    from .admin import table
    q=params.get('q',[''])[0][:200];source=params.get('source',[''])[0][:100]
    if path in ('/','/products'):
        category_id=params.get('category',[''])[0]
        if category_id:category_id=identifier(category_id)
        cats=conn.execute('SELECT * FROM veriflow.categories ORDER BY name').fetchall()
        body='<section class="hero"><div><p class="eyebrow">PRIVATE WORKSPACE</p><h2>Your software intelligence library</h2><p>Discover products, inspect sources and collect existing reviews with recorded permission.</p></div><a class="primary" href="/collect">START COLLECTION</a></section>'
        counts=conn.execute('''SELECT (SELECT count(*) FROM veriflow.products) AS products,
            (SELECT count(*) FROM veriflow.reviews) AS reviews,(SELECT count(*) FROM veriflow.sources WHERE enabled) AS enabled_sources,
            (SELECT count(*) FROM veriflow.admin_jobs WHERE state IN ('queued','running')) AS pending_jobs''').fetchall()
        body+='<section class="stats">'+''.join('<div><strong>'+str(v)+'</strong><span>'+e(k.replace('_',' '))+'</span></div>' for k,v in counts[0].items())+'</section>'
        body+='<form><label>Search products<input name="q" value="'+e(q,quote=True)+'" placeholder="Name or vendor"></label><label>Category<select name="category"><option value="">All categories</option>'+options(cats)+'</select></label><button>Search</button></form>'
        products=conn.execute('''SELECT p.id AS product_id,p.name,p.vendor,p.website,
            (SELECT string_agg(c.name,', ' ORDER BY c.name) FROM veriflow.product_categories pc JOIN veriflow.categories c ON c.id=pc.category_id WHERE pc.product_id=p.id) AS categories,
            (SELECT count(*) FROM veriflow.reviews r WHERE r.product_id=p.id) AS reviews
            FROM veriflow.products p WHERE (p.name ILIKE %s OR p.vendor ILIKE %s)
            AND (%s='' OR EXISTS(SELECT 1 FROM veriflow.product_categories pc WHERE pc.product_id=p.id AND pc.category_id=CAST(NULLIF(%s,'') AS uuid)))
            ORDER BY p.name,p.id LIMIT 100''',('%'+q+'%','%'+q+'%',category_id,category_id)).fetchall()
        body+='<section class="product-grid">'+''.join('<article class="product-card"><h3>'+e(p['name'])+'</h3><p>'+e(p['vendor'])+'</p><p>'+e(p['categories'] or 'Uncategorized')+'</p><p>'+str(p['reviews'])+' collected reviews</p><a href="/reviews?product='+str(p['product_id'])+'">Inspect reviews</a> · <a href="/collect?product='+str(p['product_id'])+'">Collect reviews</a><details><summary>Product reference</summary><code>'+str(p['product_id'])+'</code><p>'+e(p['website'] or '')+'</p></details></article>' for p in products)+'</section><details><summary>Add software manually</summary>'+form('/actions/product',csrf,field('name','Software name')+field('vendor','Vendor')+'<label>Website (HTTPS, optional)<input name="website" type="url"></label><label>Categories (comma separated)<input name="categories"></label><button>Add product</button>')+'</details>'
        return 'Products',body
    if path=='/source-setup':
        sources=conn.execute("SELECT id,name FROM veriflow.sources WHERE category<>'market_research' ORDER BY name").fetchall()
        body='<p>Record actual source permission and permitted storage scope. Actor availability is not evidence of rights. Saving pauses the source; resuming is a separate explicit action.</p>'
        body+=form('/actions/permission',csrf,'<label>Source<select name="source_id">'+options(sources)+'</select></label><label>Method<select name="method"><option value="approved_import">Approved import</option><option value="apify">Apify (requires reviewed binding; paid execution disabled)</option></select></label><label>Permission evidence / contract reference<textarea name="evidence" required></textarea></label>'+field('product_keys','Permitted source product keys (comma separated)')+field('expires_at','Expiry in UTC (2027-01-01T00:00:00+00:00)')+'<label>License ID if required<select name="license_id"><option value="">Source-specific terms</option><option>CC-BY-4.0</option><option>CC-BY-SA-4.0</option></select></label><label>Source terms URL<input name="terms_url" type="url"></label><label class="check"><input type="checkbox" name="reviewed" value="yes" required>I reviewed source rules and actual collection permission</label><label class="check"><input type="checkbox" name="full_text" value="yes">Full-text collection requested</label><label class="check"><input type="checkbox" name="storage_confirmed" value="yes">Evidence explicitly permits full-text storage</label><button>Record permission and keep paused</button>')
        body+='<h3>Associate a known source product</h3>'+form('/actions/mapping',csrf,'<label>Source<select name="source_id">'+options(sources)+'</select></label>'+field('external_key','Source product key')+field('product_id','Existing product ID')+'<button>Associate product</button>')
        body+='<h3>Recorded authorizations</h3>'+table(conn.execute('SELECT id,source_id,method,product_keys,full_text_allowed,expires_at,revoked_at FROM veriflow.authorizations ORDER BY created_at DESC LIMIT 100').fetchall())
        body+=form('/actions/revoke',csrf,field('authorization_id','Authorization ID to revoke')+'<button>Revoke and pause source</button>')
        return 'Source permissions & product mappings',body
    if path=='/categories':
        body=form('/actions/category',csrf,field('name','New category')+'<button>Add category</button>')
        body+=table(conn.execute('''SELECT c.id,c.name,count(pc.product_id) AS products FROM veriflow.categories c
            LEFT JOIN veriflow.product_categories pc ON pc.category_id=c.id GROUP BY c.id ORDER BY c.name''').fetchall())
        body+=form('/actions/assign-category',csrf,field('product_id','Product ID')+field('category','Category name')+'<button>Assign category</button>')
        body+=form('/actions/rename-category',csrf,field('category_id','Category ID')+field('name','New category name')+'<button>Rename category</button>')
        return 'Categories',body
    if path=='/collect':
        sources=conn.execute("SELECT id,name FROM veriflow.sources WHERE enabled AND access_status='approved' AND collection_method IN ('approved_import','apify') ORDER BY name").fetchall()
        grants=conn.execute("SELECT id,source_id AS name FROM veriflow.authorizations WHERE revoked_at IS NULL AND expires_at>now() ORDER BY source_id,id LIMIT 500").fetchall()
        select='<label>Source<select name="source_id">'+options(sources)+'</select></label><label>Recorded authorization<select name="authorization_id">'+options(grants)+'</select></label>'
        free=conn.execute("SELECT enabled,access_status,last_status,next_run_at FROM veriflow.sources WHERE id='lib-reviews'").fetchone()
        body='<section class="hero"><div><h3>Automatic review collection</h3><p>Free direct retrieval from lib.reviews. No CSV upload, Apify token or paid Actor required.</p></div></section>'
        if not free or not free['enabled'] or free['access_status']!='approved':
            body+='<p>Review text is CC BY-SA 4.0 and requires adjacent author credit. <a href="https://lib.reviews/terms" rel="noreferrer">Read source terms</a>.</p>'+form('/actions/free-enable',csrf,'<label class="check"><input type="checkbox" name="license_confirmed" value="yes" required>I accept the source license, attribution and respectful access conditions</label><button>Enable free lib.reviews connector</button>')
        else:
            if free['last_status']=='rate_limited':body+='<p class="notice">Source cooldown until '+e(str(free['next_run_at']))+'. Requests will not bypass Retry-After.</p>'
            body+=form('/actions/discover-online',csrf,field('query','Discover software online','search',params.get('query',['Firefox'])[0])+hidden('limit',5)+'<button>Discover software</button>')
            products=conn.execute("SELECT DISTINCT p.id,p.name FROM veriflow.products p JOIN veriflow.source_products sp ON sp.product_id=p.id WHERE sp.source_id='lib-reviews' ORDER BY p.name LIMIT 500").fetchall()
            cats=conn.execute("SELECT DISTINCT c.id,c.name FROM veriflow.categories c JOIN veriflow.product_categories pc ON pc.category_id=c.id JOIN veriflow.source_products sp ON sp.product_id=pc.product_id WHERE sp.source_id='lib-reviews' ORDER BY c.name").fetchall()
            product_options=options(products)
            selected=params.get('product',[''])[0]
            if selected:product_options=product_options.replace('value="'+e(selected,quote=True)+'"','selected value="'+e(selected,quote=True)+'"')
            body+=form('/actions/start-online',csrf,'<label>Product<select name="product_id"><option value="">Select a product</option>'+product_options+'</select></label><label>Or category<select name="category_id"><option value="">Select a category</option>'+options(cats)+'</select></label>'+field('max_reviews','Maximum reviews this job (1–20)','number',20)+'<button class="primary">START COLLECTION</button>')
            body+='<p>Select exactly one product or category. The worker fetches existing reviews and preserves source URLs, licenses and attribution. Category jobs cover up to five mapped products and twenty reviews total.</p>'
        body+='<h3>Approved imports and other configured sources</h3><p>Import processing remains available separately. Paid Actor submission remains disabled.</p>'
        if not sources:body+='<p class="notice">No sources are enabled and approved. Source registration alone does not permit collection.</p>'
        body+=form('/actions/start',csrf,select+'<button>Process queued imports</button>')
        body+='<details><summary>Queue a permitted review import</summary>'+form('/actions/import',csrf,select+'<label>Format<select name="format"><option>json</option><option>jsonl</option><option>csv</option></select></label><label>Approved exported records (maximum 5 MB / 1,000 records)<textarea name="records" rows="9"></textarea></label><label>Or select an approved export file<input type="file" name="records_file" accept=".csv,.json,.jsonl"></label><button>Queue import</button>')+'</details>'
        body+='<details><summary>Discover products from an approved catalog</summary><p>Catalog records need external_key, name, vendor, optional website and categories. Existing mappings are never guessed or silently reassigned.</p>'+form('/actions/catalog',csrf,select+'<label>Catalog JSON array<textarea name="records" rows="8"></textarea></label><label>Or select catalog JSON<input type="file" name="records_file" accept=".json"></label><button>Discover products &amp; categories</button>')+'</details>'
        body+='<p><a href="/jobs">View persistent jobs</a> · <a href="/collection">Provider jobs and costs</a></p>'
        return 'Start collection',body
    if path=='/jobs':
        state=params.get('state',[''])[0]
        body='<form><label>State<select name="state"><option value="">All states</option>'+''.join('<option>'+s+'</option>' for s in ('queued','running','succeeded','blocked','failed','cancelled'))+'</select></label><button>Filter</button></form>'
        rows=conn.execute('''SELECT id AS job_id,kind,source_id,state,attempts,error_code,result,created_at,finished_at,artifact_name
            FROM veriflow.admin_jobs WHERE (%s='' OR state=%s) ORDER BY created_at DESC,id LIMIT 100''',(state,state)).fetchall()
        body+=table(rows)+form('/actions/cancel',csrf,field('job_id','Queued job ID')+'<button>Cancel queued request</button>')
        body+='<p>Cancel affects only a queued request. Pause the source to stop pending ingestion; provider runs are monitored separately.</p>'
        return 'Background jobs',body
    if path=='/settings':
        rows=conn.execute('SELECT id,name,enabled,access_status,schedule_seconds FROM veriflow.sources ORDER BY name').fetchall()
        selected=conn.execute("SELECT value FROM veriflow.admin_settings WHERE key='source_preferences'").fetchone()
        saved=selected['value'] if selected else {}
        boxes=''.join('<label class="check"><input type="checkbox" name="sources" value="'+e(r['id'],quote=True)+'"'+(' checked' if r['id'] in saved.get('source_ids',[]) else '')+'>'+e(r['name'])+'</label>' for r in rows)
        body='<p><a href="/source-setup">Configure source permissions and product mappings</a></p><p>Bulk changes preserve recorded access and full-text permissions. Resume only works for already configured, approved sources.</p>'
        body+=form('/actions/sources',csrf,boxes+'<label>Action<select name="operation"><option value="schedule">Save schedule</option><option value="pause">Pause selected sources</option><option value="resume">Resume approved sources</option></select></label>'+field('seconds','Schedule in seconds','number',saved.get('schedule_seconds',86400))+'<button>Save selected sources</button>')+table(rows)
        return 'Bulk sources & saved settings',body
    if path=='/coverage':
        body='<h3>Coverage by source</h3>'+table(conn.execute('''SELECT s.name,s.enabled,s.access_status,s.collection_method,s.last_status,s.last_run_at,s.failures,
            (SELECT count(*) FROM veriflow.import_batches b WHERE b.source_id=s.id AND b.status='pending') AS queued_imports,
            (SELECT count(*) FROM veriflow.source_products m WHERE m.source_id=s.id) AS mapped_products,
            (SELECT count(*) FROM veriflow.reviews r WHERE r.source_id=s.id) AS reviews,
            (SELECT count(*) FROM veriflow.authorizations a WHERE a.source_id=s.id AND a.revoked_at IS NULL AND a.expires_at>now()) AS valid_authorizations
            FROM veriflow.sources s ORDER BY s.name''').fetchall())
        body+='<h3>Coverage by product</h3>'+table(conn.execute('''SELECT p.name,
            (SELECT count(*) FROM veriflow.source_products m WHERE m.product_id=p.id) AS source_mappings,
            (SELECT count(DISTINCT source_id) FROM veriflow.reviews r WHERE r.product_id=p.id) AS sources_with_reviews,
            (SELECT count(*) FROM veriflow.reviews r WHERE r.product_id=p.id) AS reviews FROM veriflow.products p ORDER BY p.name LIMIT 100''').fetchall())
        return 'Source coverage',body
    if path=='/exports':
        body='<p>Exports run in the background, preserve provenance and required licensing, and expire after seven days. Spreadsheet cells are protected against formula execution. Text is omitted when current permission is unavailable.</p>'
        body+=form('/actions/export',csrf,'<label>Format<select name="format">'+''.join('<option>'+f+'</option>' for f in ('csv','xlsx','json','jsonl','zip'))+'</select></label><label>Product name or review search<input name="q"></label><label>Source ID (optional)<input name="source"></label><label>Product ID (optional)<input name="product"></label>'+field('limit','Maximum records (up to 100,000)','number','10000')+'<button>Create private export</button>')
        body+=table(conn.execute("SELECT id AS job_id,state,error_code,result,artifact_name,artifact_expires_at FROM veriflow.admin_jobs WHERE kind='export' ORDER BY created_at DESC LIMIT 100").fetchall())
        return 'Private exports',body
    if path.startswith('/reviews/'):
        rid=identifier(path.rsplit('/',1)[1])
        row=conn.execute('''SELECT r.*,p.name AS product,s.name AS source,l.license_id,l.license_url,l.public_credit,l.attribution_url,l.text_modified,l.change_note
            FROM veriflow.reviews r JOIN veriflow.products p ON p.id=r.product_id JOIN veriflow.sources s ON s.id=r.source_id
            LEFT JOIN veriflow.review_licenses l ON l.review_id=r.id WHERE r.id=%s''',(rid,)).fetchone()
        if not row:return 'Review not found','<p>No matching review.</p>'
        credit=''
        if row.get('public_credit'):
            credit='<p>Credit: <a href="'+e(str(row['attribution_url']),quote=True)+'" rel="noreferrer noopener">'+e(row['public_credit'])+'</a> · <a href="'+e(str(row['license_url']),quote=True)+'" rel="noreferrer noopener">'+e(str(row['license_id']))+'</a></p>'
        body='<article class="product-card"><h3>'+e(row['product'])+'</h3><p>'+e(row['source'])+' · '+e(str(row['rating']))+'/'+e(str(row['rating_scale']))+' · '+e(str(row['published_at']))+'</p><div style="white-space:pre-wrap">'+e(row['review_text'] or 'No permitted review text stored.')+'</div>'+credit+'<p><a href="'+e(row['original_url'],quote=True)+'" rel="noreferrer noopener">Original review</a></p></article>'
        body+='<details><summary>Collection provenance</summary>'+table([{k:v for k,v in row.items() if k!='review_text'}])+'</details><h3>Potential duplicate records</h3>'
        body+=table(conn.execute('''SELECT r.id AS review_id,s.name AS source,r.original_url,r.published_at FROM veriflow.reviews r
            JOIN veriflow.sources s ON s.id=r.source_id WHERE r.duplicate_group=%s AND r.id<>%s ORDER BY r.id LIMIT 100''',(row['duplicate_group'],rid)).fetchall())
        return 'Review inspection',body
    return None


def dispatch(conn,path,data):
    value=lambda k: data.get(k,[''])[0]
    if path=='/actions/free-enable':
        from .free_collection import install_source
        from .connectors import AccessDenied
        if value('license_confirmed')!='yes':raise AccessDenied()
        install_source(conn,enable=True);return '/collect'
    if path=='/actions/discover-online':
        request_job(conn,'catalog',dict(mode='online_discovery',query=value('query'),limit=int(value('limit') or 5)),value('request_key'),'lib-reviews');return '/jobs'
    if path=='/actions/start-online':
        payload=dict(mode='online_collection',product_id=value('product_id'),category_id=value('category_id'),max_reviews=int(value('max_reviews') or 20))
        request_job(conn,'collection',payload,value('request_key'),'lib-reviews');return '/jobs'
    if path=='/actions/revoke':
        aid=identifier(value('authorization_id'))
        grant=conn.execute('SELECT source_id FROM veriflow.authorizations WHERE id=%s',(aid,)).fetchone()
        if not grant:raise CollectionError('Unknown authorization')
        conn.execute('SELECT id FROM veriflow.sources WHERE id=%s FOR UPDATE',(grant['source_id'],))
        conn.execute('UPDATE veriflow.authorizations SET revoked_at=now() WHERE id=%s',(aid,))
        conn.execute('UPDATE veriflow.sources SET enabled=false WHERE id=%s',(grant['source_id'],));return '/source-setup'
    if path=='/actions/permission':
        from .admin_ops import record_permission
        record_permission(conn,value('source_id'),value('method'),value('evidence'),value('product_keys').split(','),value('expires_at'),value('full_text')=='yes',value('reviewed')=='yes',value('storage_confirmed')=='yes',value('license_id'),value('terms_url'));return '/settings'
    if path=='/actions/mapping':
        pid=identifier(value('product_id'));key=clean(value('external_key'),200)
        p=conn.execute('SELECT name FROM veriflow.products WHERE id=%s',(pid,)).fetchone()
        if not p:raise CollectionError('Unknown product')
        existing=conn.execute('SELECT product_id FROM veriflow.source_products WHERE source_id=%s AND external_key=%s FOR UPDATE',(value('source_id'),key)).fetchone()
        if existing and str(existing['product_id'])!=pid:raise CollectionError('Conflicting mapping; manual reconciliation required')
        conn.execute('INSERT INTO veriflow.source_products(source_id,external_key,product_id,expected_name) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING',(value('source_id'),key,pid,p['name']));return '/products'
    if path=='/actions/product':
        product(conn,value('name'),value('vendor'),value('website'),[c.strip() for c in value('categories').split(',') if c.strip()]);return '/products'
    if path=='/actions/category':category(conn,value('name'));return '/categories'
    if path=='/actions/assign-category':
        conn.execute('INSERT INTO veriflow.product_categories VALUES (%s,%s) ON CONFLICT DO NOTHING',(identifier(value('product_id')),category(conn,value('category'))));return '/categories'
    if path=='/actions/rename-category':
        conn.execute('UPDATE veriflow.categories SET name=%s WHERE id=%s',(clean(value('name'),120),identifier(value('category_id'))));return '/categories'
    if path=='/actions/sources':source_settings(conn,data.get('sources',[]),value('operation'),value('seconds'));return '/settings'
    if path=='/actions/cancel':
        conn.execute("UPDATE veriflow.admin_jobs SET state='cancelled',payload='{}',finished_at=now() WHERE id=%s AND state='queued'",(identifier(value('job_id')),));return '/jobs'
    if path=='/actions/export':
        from .exports import filters
        request_job(conn,'export',filters({k:value(k) for k in ('q','source','product','limit','format')}),value('request_key'));return '/exports'
    if path in ('/actions/start','/actions/catalog'):
        payload={'records':json.loads(value('records') or value('records_file'))} if path.endswith('catalog') else {}
        request_job(conn,'catalog' if path.endswith('catalog') else 'collection',payload,value('request_key'),value('source_id'),value('authorization_id'));return '/jobs'
    if path=='/actions/import':
        from .worker import enqueue
        payload=value('records') or value('records_file');fmt=value('format')
        if fmt=='jsonl':payload=json.dumps([json.loads(line) for line in payload.splitlines() if line.strip()]);fmt='json'
        enqueue(conn,value('source_id'),identifier(value('authorization_id')),payload,fmt);return '/collect'
    raise CollectionError('Unknown action')
