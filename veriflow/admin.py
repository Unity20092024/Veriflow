"""Read-only private dashboard. Bind loopback; use an HTTPS reverse proxy in production."""
import base64
import hashlib
import hmac
import html
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from .connectors import CollectionError
from .db import connect
from .exports import EXPORTS, ExportError, review_rows

STYLE = '''body{font:16px system-ui;margin:2rem;background:#111827;color:#e5e7eb}a{color:#93c5fd}
nav{display:flex;gap:1rem;margin:1.5rem 0}table{border-collapse:collapse;width:100%;background:#1f2937}
th,td{padding:.7rem;text-align:left;border-bottom:1px solid #374151;vertical-align:top}
input,select,button{padding:.6rem;margin:.3rem}td{max-width:28rem;overflow-wrap:anywhere;white-space:pre-wrap}
button.primary{font-size:1.2rem;font-weight:700;padding:.9rem 1.6rem;background:#2563eb;color:#fff;border:0;border-radius:.5rem}
small{color:#a1a1aa}h1{font-size:1.8rem}'''


def authorized(header, username, password):
    try:
        decoded = base64.b64decode(header.removeprefix('Basic '), validate=True).decode()
        if not header.startswith('Basic '):
            return False
        # Hash first so arbitrary-length input uses constant-size comparisons.
        return hmac.compare_digest(hashlib.sha256(decoded.encode()).digest(),
                                   hashlib.sha256(f'{username}:{password}'.encode()).digest())
    except (ValueError, UnicodeDecodeError):
        return False


def table(rows):
    if not rows:
        return '<p>No records yet.</p>'
    keys = list(rows[0])
    def cell(key, value):
        escaped = html.escape(str(value) if value is not None else '—')
        if key in ('original_url','license_url','attribution_url','source_terms_url') and str(value).startswith('https://'):
            return f'<a href="{escaped}" rel="noreferrer noopener">{"Original source" if key=="original_url" else "License" if key=="license_url" else "Attribution"}</a>'
        return escaped
    return '<table><thead><tr>' + ''.join('<th>'+html.escape(k.replace('_',' '))+'</th>' for k in keys) + '</tr></thead><tbody>' + ''.join('<tr>'+''.join('<td>'+cell(k,row[k])+'</td>' for k in keys)+'</tr>' for row in rows) + '</tbody></table>'


def page(conn, path, params, csrf_token=''):
    q = params.get('q', [''])[0][:200]
    source = params.get('source', [''])[0][:100]
    product = params.get('product', [''])[0][:100]
    if product:
        import uuid
        try:
            product = str(uuid.UUID(product))
        except (ValueError, TypeError, AttributeError):
            product = ''
    try:
        offset = max(0,min(100000,int(params.get('offset',['0'])[0])))
    except ValueError:
        offset = 0
    controls = ''
    if path == '/':
        title = 'Products'
        controls = '<form><input name="q" placeholder="Search products" value="'+html.escape(q,quote=True)+'"><button>Search</button></form>'
        rows = conn.execute('''SELECT p.id,p.name,p.vendor,
            (SELECT string_agg(c.name,', ' ORDER BY c.name) FROM veriflow.product_categories pc
             JOIN veriflow.categories c ON c.id=pc.category_id WHERE pc.product_id=p.id) AS categories,
            count(r.id) AS reviews
            FROM veriflow.products p LEFT JOIN veriflow.reviews r ON r.product_id=p.id
            WHERE p.name ILIKE %s GROUP BY p.id ORDER BY p.name,p.id LIMIT 50 OFFSET %s''', ('%'+q+'%',offset)).fetchall()
    elif path == '/coverage':
        from .coverage import render
        title = 'Product coverage and research evidence'
        controls, rows = render(conn,params,csrf_token)
    elif path == '/reviews':
        title = 'Collected reviews'
        options = ''.join('<option value="'+html.escape(s['id'])+'"'+(' selected' if source==s['id'] else '')+'>'+html.escape(s['name'])+'</option>' for s in conn.execute("SELECT id,name FROM veriflow.sources WHERE category<>'market_research' ORDER BY name"))
        product_options = ''.join(
            '<option value="'+html.escape(str(p['id']))+'"'
            +(' selected' if product==str(p['id']) else '')+'>'
            +html.escape(p['name'])+'</option>'
            for p in conn.execute('SELECT id,name FROM veriflow.products ORDER BY name LIMIT 500')
        )
        from urllib.parse import urlencode
        filters = html.escape(urlencode({'q':q,'source':source,'product':product}), quote=True)
        downloads = ' · '.join('<a href="/exports/reviews.'+fmt+'?'+filters+'">'+label+'</a>'
                               for fmt,label in (('csv','CSV'),('xlsx','Excel'),('json','JSON'),('jsonl','JSONL')))
        controls = '<form><input name="q" placeholder="Product or review text" value="'+html.escape(q,quote=True)+'"><select name="source"><option value="">All sources</option>'+options+'</select><select name="product"><option value="">All products</option>'+product_options+'</select><button>Filter</button></form><p>Export current filters (up to 10,000 rows): '+downloads+'</p>'
        rows = conn.execute('''SELECT p.name AS product,
            (SELECT string_agg(c.name,', ' ORDER BY c.name) FROM veriflow.product_categories pc
             JOIN veriflow.categories c ON c.id=pc.category_id WHERE pc.product_id=p.id) AS categories,
            s.name AS source,r.review_text,l.public_credit,l.license_id,l.license_url,l.attribution_url,
            l.source_terms_url,l.text_modified,l.change_note,r.rating,r.rating_scale,
            r.published_at,r.original_url,r.collected_at,r.duplicate_group
            FROM veriflow.reviews r JOIN veriflow.products p ON p.id=r.product_id
            JOIN veriflow.sources s ON s.id=r.source_id
            LEFT JOIN veriflow.review_licenses l ON l.review_id=r.id
            WHERE (p.name ILIKE %s OR r.review_text ILIKE %s) AND (%s='' OR r.source_id=%s)
              AND (%s::uuid IS NULL OR r.product_id=%s)
            ORDER BY r.collected_at DESC,r.id LIMIT 50 OFFSET %s''',
            ('%'+q+'%','%'+q+'%',source,source,product or None,product or None,offset)).fetchall()
    elif path == '/sources':
        title = 'Source registry and status'
        rows = conn.execute('''SELECT name,category,collection_method,access_status,enabled,full_text_allowed,
            schedule_seconds,last_status,last_run_at,next_run_at,failures FROM veriflow.sources
            ORDER BY name LIMIT 50 OFFSET %s''', (offset,)).fetchall()
    elif path == '/errors':
        title = 'Collection runs and errors'
        rows = conn.execute('''SELECT s.name AS source,r.status,r.error_code,r.inserted,r.duplicates,
            r.started_at,r.finished_at FROM veriflow.collection_runs r JOIN veriflow.sources s ON s.id=r.source_id
            ORDER BY r.started_at DESC,r.id LIMIT 50 OFFSET %s''', (offset,)).fetchall()
    elif path == '/collection':
        title = 'Start collection and job status'
        counts = conn.execute("SELECT s.name,count(r.id) AS reviews FROM veriflow.sources s LEFT JOIN veriflow.reviews r ON r.source_id=s.id GROUP BY s.id ORDER BY s.name").fetchall()
        costs = conn.execute("""SELECT count(*) AS jobs,count(*) FILTER (WHERE state='failed') AS failed_jobs,
            count(*) FILTER (WHERE state IN ('starting','start_unknown')) AS uncertain_starts,
            coalesce(sum(reserved_usd) FILTER (WHERE confirmed_billed_usd IS NULL),0) AS unconfirmed_reservations_usd,
            sum(reported_usage_usd) AS reported_usage_usd,sum(confirmed_billed_usd) AS confirmed_billed_usd
            FROM veriflow.apify_jobs""").fetchall()
        from .pilot import summary
        limits=summary()
        from .jobs import VALID_CATEGORIES
        categories = ''.join('<option value="'+html.escape(value)+'">'+html.escape(value.replace('_',' ').title())+'</option>'
                            for value in sorted(VALID_CATEGORIES) if value != 'market_research')
        products = ''.join('<option value="'+html.escape(str(p['id']))+'">'+html.escape(p['name'])+'</option>'
                           for p in conn.execute('SELECT id,name FROM veriflow.products ORDER BY name LIMIT 500'))
        collection_jobs = conn.execute('''SELECT id,scope,category,product_id,strategy,target_reviews,state,requested_sources,
            completed_sources,pages_fetched,reviews_retrieved,inserted,duplicates,error_code,created_at
            FROM veriflow.collection_jobs ORDER BY created_at DESC,id LIMIT 50 OFFSET %s''',(offset,)).fetchall()
        from .bounded_collection import progress
        free_batch = progress(conn)
        batch_products = conn.execute('''SELECT p.name AS product,p.category,
            (SELECT count(*) FROM veriflow.reviews r JOIN veriflow.free_batches b
             ON b.authorization_id=r.authorization_id
             WHERE b.id=p.batch_id AND r.product_id=p.product_id) AS new_unique_reviews,
            (SELECT count(*) FROM veriflow.free_batch_tasks t WHERE t.batch_id=p.batch_id
             AND t.data->>'product_url'=p.url AND t.state IN ('pending','importing')) AS pending_tasks,
            (SELECT count(*) FROM veriflow.free_batch_tasks t WHERE t.batch_id=p.batch_id
             AND t.data->>'product_url'=p.url AND t.state='failed') AS errors
            FROM veriflow.free_batch_products p ORDER BY p.name''').fetchall()
        batch_errors = conn.execute('''SELECT kind,url,state,error_code FROM veriflow.free_batch_tasks
            WHERE error_code IS NOT NULL ORDER BY id DESC LIMIT 30''').fetchall()
        batch_controls = ('<h3>Approved free multi-product batch</h3>'
            '<p>lib.reviews only. 500 new unique reviews · 100 products · 1,500 HTTP attempts · '
            '10 listing pages/product · minimum 3 seconds · original 48-hour expiry. Paid budget: $0. '
            'Counters and checkpoints survive restart. This page refreshes every 15 seconds.</p>'
            +table([{'metric': key.replace('_',' '), 'value': value}
                    for key,value in (free_batch or {}).items()])
            +'<h4>Discovered software products</h4>'+table(batch_products)
            +'<h4>Batch errors and skipped tasks</h4>'+table(batch_errors)
            +'<meta http-equiv="refresh" content="15">')
        controls = (
            '<form method="post" action="/collection/start">'
            +'<input type="hidden" name="csrf" value="'+html.escape(csrf_token,quote=True)+'">'
            +'<label>Collection scope <select name="scope" required>'
            +'<option value="all_eligible">All eligible sources</option>'
            +'<option value="category">Category</option><option value="product">Product</option></select></label>'
            +'<label>Source category <select name="category"><option value="">Select category</option>'+categories+'</select></label>'
            +'<label>Software category <select name="software_category_id"><option value="">All software categories</option>'
            +''.join('<option value="'+html.escape(str(c['id']))+'">'+html.escape(c['name'])+'</option>'
                     for c in conn.execute('SELECT id,name FROM veriflow.categories ORDER BY name'))
            +'</select></label>'
            +'<label>Product <select name="product_id"><option value="">Select product</option>'+products+'</select></label>'
            +'<label>Strategy <select name="strategy"><option value="breadth_first">Breadth First — default</option>'
            +'<option value="balanced">Balanced</option><option value="depth_first">Depth First</option></select></label>'
            +'<label>Per-product evidence target <input name="target_reviews" type="number" min="1" max="10000" '
            +'placeholder="Default: 5 / 10 / 30"></label>'
            +'<button class="primary" type="submit">START COLLECTION</button></form>'
            +'<p>Prospective jobs only: Breadth First targets 5 total unique reviews/product and favors '
            +'empty products and underrepresented software categories. Balanced defaults to 10; Depth First '
            +'to 30. Targets are adjustable priorities, never permanent storage caps. New jobs retain '
            +'500-new-review, 1,500-page-attempt, 10-page/item and 48-hour ceilings; source limits can be lower. '
            +'Discovery remains restricted to explicitly approved source scopes. Starting a job does not '
            +'renew, change or restart the completed lib.reviews batch.</p>'
            +'<p>Only approved, enabled permitted-crawl and authorized-API sources with valid grants are queued. Paid Apify runs remain disabled.</p>'
            +batch_controls
            +'<h3>Persistent collection jobs</h3>'+table(collection_jobs)
            +'<h3>Reviews by source</h3>'+table(counts)
            +'<h3>Apify usage and cost</h3>'+table(costs)
            +'<p>First-test ceiling: $'+html.escape(limits['max_total_usd'])+' total and '
            +str(limits['max_review_records'])+' review records. Paid execution: '
            +('enabled' if limits['paid_runs_enabled'] else 'disabled')
            +'. Reservations are spending allowances. Reported usage is not an invoice-confirmed total. '
            +'Uncertain starts retain their allowance and are never restarted automatically.</p>'
        )
        rows = conn.execute("""SELECT j.id,s.name AS source,j.state,j.actor_id,j.actor_run_id,j.dataset_id,
            j.retrieved,j.inserted,j.duplicates,j.reserved_usd,j.reported_usage_usd,j.confirmed_billed_usd,
            j.error_code,j.created_at FROM veriflow.apify_jobs j JOIN veriflow.sources s ON s.id=j.source_id
            ORDER BY j.created_at DESC,j.id LIMIT 50 OFFSET %s""",(offset,)).fetchall()
    elif path == '/capabilities':
        title = 'Source capability audit'
        import json
        from pathlib import Path
        audit=json.loads((Path(__file__).resolve().parents[1]/'data/source-capabilities.json').read_text())
        controls='<p>Catalog availability does not authorize collection. Price estimates use listed event prices and explicit assumptions; actual plans and additional usage can differ.</p>'
        rows=[]
        for item in audit[offset:offset+50]:
            candidate=item.get('apify_candidate') or {}
            direct_api=item.get('direct_api') or {}
            rows.append(dict(source=item['name'],actor=candidate.get('actor'),
                fields=candidate.get('declared_dataset_fields'),pricing_model=candidate.get('pricing',{}).get('pricingModel'),
                estimated_cost_usd=candidate.get('estimated_actor_event_cost_usd'),
                actor_status=item['catalog_status'],direct_api=direct_api.get('status'),
                api_adapter=direct_api.get('runtime_adapter'),
                api_runtime=direct_api.get('runtime_status'),
                permission=item['collection_permission']))
    elif path == '/integrations':
        title = 'Integration status'
        controls = '<p>Discovered capabilities require contract review. Ready means an approved action completed and its result was saved.</p>'
        rows = conn.execute('''SELECT provider,status,capabilities,last_discovered_at,last_success_at,error_code
            FROM veriflow.integration_status ORDER BY provider LIMIT 50 OFFSET %s''', (offset,)).fetchall()
    elif path == '/trends':
        title = 'Google Trends research'
        controls = '<p>Market research is stored separately from reviews. Collection requires a connected, reviewed Composio action and source approval. See Integrations for verified status.</p>'
        rows = conn.execute('''SELECT query,geography,time_range,tool_slug,tool_version,
            original_url,data,collected_at FROM veriflow.trends_research
            ORDER BY collected_at DESC,id LIMIT 50 OFFSET %s''', (offset,)).fetchall()
    else:
        return None
    from urllib.parse import urlencode
    next_url = path+'?'+urlencode(dict(q=q,source=source,product=product,offset=offset+50))
    prev_url = path+'?'+urlencode(dict(q=q,source=source,product=product,offset=max(0,offset-50)))
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Veriflow · {title}</title><style>{STYLE}</style><h1>Veriflow · Private collection engine</h1>
    <nav><a href="/">Products</a><a href="/coverage">Product coverage</a><a href="/reviews">Reviews</a><a href="/sources">Sources</a>
    <a href="/errors">Runs &amp; errors</a><a href="/trends">Google Trends</a><a href="/integrations">Integrations</a><a href="/collection">Collection &amp; cost</a><a href="/capabilities">Source audit</a></nav>
    <h2>{title}</h2>{controls}{table(rows)}<p><a href="{html.escape(prev_url)}">Previous</a> · <a href="{html.escape(next_url)}">Next</a></p>
    <small>Private administrative access · 50 records per page</small></html>'''


def serve(port=8080,host='127.0.0.1'):
    from .config import load_environment
    load_environment()
    username, password = os.environ.get('ADMIN_USERNAME',''), os.environ.get('ADMIN_PASSWORD','')
    if not username or ':' in username or len(password) < 24:
        raise ValueError('Set ADMIN_USERNAME and ADMIN_PASSWORD (24+ characters)')
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if not authorized(self.headers.get('Authorization',''),username,password):
                self.send_response(401)
                self.send_header('WWW-Authenticate','Basic realm="Veriflow private admin"')
                self.send_header('Cache-Control','no-store')
                self.end_headers()
                return
            try:
                request = urlsplit(self.path)
                if request.path.startswith('/exports/reviews.'):
                    extension = request.path.rsplit('.',1)[-1]
                    if extension not in EXPORTS:
                        self.send_error(404)
                        return
                    params = parse_qs(request.query)
                    values = {key:params.get(key,[''])[0] for key in ('source','product','q')}
                    try:
                        limit = int(params.get('limit',['10000'])[0])
                        offset = int(params.get('offset',['0'])[0])
                    except ValueError:
                        raise ExportError('invalid_export_range') from None
                    with connect() as conn:
                        rows = review_rows(conn,values['source'],values['product'],values['q'],limit,offset)
                    content_type,filename,render = EXPORTS[extension]
                    body = render(rows)
                    self.send_response(200)
                    self.send_header('Content-Type',content_type)
                    self.send_header('Content-Length',str(len(body)))
                    self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
                    self.send_header('Cache-Control','no-store')
                    self.send_header('X-Content-Type-Options','nosniff')
                    self.end_headers()
                    self.wfile.write(body)
                    return
                csrf = hmac.new(f'{username}:{password}'.encode(),
                                b'veriflow-collection-start',hashlib.sha256).hexdigest()
                with connect() as conn:
                    body = page(conn,request.path,parse_qs(request.query),csrf)
                status = 200 if body else 404
                body = (body or 'Not found').encode()
            except ExportError as exc:
                self.send_error(413 if str(exc)=='export_too_large' else 400)
                return
            except Exception as exc:
                print({'component':'admin','error_type':type(exc).__name__,
                       'sqlstate':getattr(exc,'sqlstate',None)},flush=True)
                status, body = 503, b'Database unavailable. Check private server configuration.'
            self.send_response(status)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('X-Frame-Options','DENY')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if not authorized(self.headers.get('Authorization',''),username,password):
                self.send_response(401)
                self.send_header('WWW-Authenticate','Basic realm="Veriflow private admin"')
                self.send_header('Cache-Control','no-store')
                self.end_headers()
                return
            request = urlsplit(self.path)
            origin = urlsplit(self.headers.get('Origin',''))
            host = urlsplit('//'+self.headers.get('Host','')).hostname
            if (request.path not in ('/collection/start','/research/queue','/products/identity') or origin.scheme not in ('http','https')
                    or not host or origin.hostname != host):
                self.send_error(403)
                return
            if self.headers.get_content_type() != 'application/x-www-form-urlencoded':
                self.send_error(415)
                return
            try:
                length = int(self.headers.get('Content-Length','0'))
            except ValueError:
                self.send_error(400)
                return
            if not 0 < length <= 4096:
                self.send_error(413)
                return
            try:
                values = parse_qs(self.rfile.read(length).decode('utf-8'),
                                  keep_blank_values=True,strict_parsing=True)
                allowed = {'csrf','scope','category','product_id','strategy','target_reviews','software_category_id'}
                if request.path == '/research/queue':
                    allowed = {'csrf','product_id'}
                elif request.path == '/products/identity':
                    allowed = {'csrf','product_id','canonical_id'}
                if set(values)-allowed or any(len(v)!=1 for v in values.values()):
                    self.send_error(400)
                    return
                csrf = values.get('csrf',[''])[0]
                expected = hmac.new(f'{username}:{password}'.encode(),
                                    b'veriflow-collection-start',hashlib.sha256).hexdigest()
                if not hmac.compare_digest(csrf,expected):
                    self.send_error(403)
                    return
                scope = values.get('scope',[''])[0]
                category = values.get('category',[''])[0] or None
                product_id = values.get('product_id',[''])[0] or None
                from .jobs import start_job
                with connect() as conn:
                    if request.path == '/research/queue':
                        from .strategy import queue_research
                        queue_research(conn,product_id)
                    elif request.path == '/products/identity':
                        from .strategy import link_identity
                        link_identity(conn,product_id,values.get('canonical_id',[''])[0])
                    else:
                        start_job(conn,scope,category,product_id,
                                  strategy=values.get('strategy',['breadth_first'])[0],
                                  target_reviews=values.get('target_reviews',[''])[0],
                                  software_category_id=values.get('software_category_id',[''])[0] or None)
                self.send_response(303)
                self.send_header('Location','/collection' if request.path=='/collection/start' else '/coverage')
                self.send_header('Cache-Control','no-store')
                self.end_headers()
            except CollectionError:
                self.send_error(400,'Invalid or unavailable collection selection')
            except (UnicodeDecodeError,ValueError):
                self.send_error(400)
            except Exception:
                self.send_response(503)
                self.send_header('Cache-Control','no-store')
                self.end_headers()

        def log_message(self, *_):
            pass  # Never log search strings, Authorization headers, or review text.
    ThreadingHTTPServer((host,port),Handler).serve_forever()
