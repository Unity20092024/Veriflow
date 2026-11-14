"""Read-only private dashboard. Bind loopback; use an HTTPS reverse proxy in production."""
import base64
import hashlib
import hmac
import html
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from .db import connect

STYLE = '''body{font:16px system-ui;margin:2rem;background:#111827;color:#e5e7eb}a{color:#93c5fd}
nav{display:flex;gap:1rem;margin:1.5rem 0}table{border-collapse:collapse;width:100%;background:#1f2937}
th,td{padding:.7rem;text-align:left;border-bottom:1px solid #374151;vertical-align:top}
input,select,button{padding:.6rem;margin:.3rem}td{max-width:28rem;overflow-wrap:anywhere;white-space:pre-wrap}
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
        if key == 'original_url' and str(value).startswith('https://'):
            return f'<a href="{escaped}" rel="noreferrer noopener">Original source</a>'
        return escaped
    return '<table><thead><tr>' + ''.join('<th>'+html.escape(k.replace('_',' '))+'</th>' for k in keys) + '</tr></thead><tbody>' + ''.join('<tr>'+''.join('<td>'+cell(k,row[k])+'</td>' for k in keys)+'</tr>' for row in rows) + '</tbody></table>'


def page(conn, path, params):
    q = params.get('q', [''])[0][:200]
    source = params.get('source', [''])[0][:100]
    try:
        offset = max(0,min(100000,int(params.get('offset',['0'])[0])))
    except ValueError:
        offset = 0
    controls = ''
    if path == '/':
        title = 'Products'
        controls = '<form><input name="q" placeholder="Search products" value="'+html.escape(q,quote=True)+'"><button>Search</button></form>'
        rows = conn.execute('''SELECT p.id,p.name,p.vendor,count(r.id) AS reviews
            FROM veriflow.products p LEFT JOIN veriflow.reviews r ON r.product_id=p.id
            WHERE p.name ILIKE %s GROUP BY p.id ORDER BY p.name,p.id LIMIT 50 OFFSET %s''', ('%'+q+'%',offset)).fetchall()
    elif path == '/reviews':
        title = 'Collected reviews'
        options = ''.join('<option value="'+html.escape(s['id'])+'"'+(' selected' if source==s['id'] else '')+'>'+html.escape(s['name'])+'</option>' for s in conn.execute("SELECT id,name FROM veriflow.sources WHERE category<>'market_research' ORDER BY name"))
        controls = '<form><input name="q" placeholder="Product or review text" value="'+html.escape(q,quote=True)+'"><select name="source"><option value="">All sources</option>'+options+'</select><button>Filter</button></form>'
        rows = conn.execute('''SELECT p.name AS product,s.name AS source,r.review_text,r.rating,r.rating_scale,
            r.published_at,r.original_url,r.collected_at,r.duplicate_group
            FROM veriflow.reviews r JOIN veriflow.products p ON p.id=r.product_id
            JOIN veriflow.sources s ON s.id=r.source_id
            WHERE (p.name ILIKE %s OR r.review_text ILIKE %s) AND (%s='' OR r.source_id=%s)
            ORDER BY r.collected_at DESC,r.id LIMIT 50 OFFSET %s''', ('%'+q+'%','%'+q+'%',source,source,offset)).fetchall()
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
        title = 'Collection counts and Apify jobs'
        counts = conn.execute("SELECT s.name,count(r.id) AS reviews FROM veriflow.sources s LEFT JOIN veriflow.reviews r ON r.source_id=s.id GROUP BY s.id ORDER BY s.name").fetchall()
        costs = conn.execute("""SELECT count(*) AS jobs,count(*) FILTER (WHERE state='failed') AS failed_jobs,
            count(*) FILTER (WHERE state IN ('starting','start_unknown')) AS uncertain_starts,
            coalesce(sum(reserved_usd) FILTER (WHERE confirmed_billed_usd IS NULL),0) AS unconfirmed_reservations_usd,
            sum(reported_usage_usd) AS reported_usage_usd,sum(confirmed_billed_usd) AS confirmed_billed_usd
            FROM veriflow.apify_jobs""").fetchall()
        controls = '<h3>Reviews by source</h3>'+table(counts)+'<h3>Apify usage and cost</h3>'+table(costs)+'<p>Reservations are spending allowances. Reported usage is not an invoice-confirmed total. Uncertain starts retain their allowance and are never restarted automatically.</p>'
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
            rows.append(dict(source=item['name'],actor=candidate.get('actor'),
                fields=candidate.get('declared_dataset_fields'),pricing_model=candidate.get('pricing',{}).get('pricingModel'),
                estimated_cost_usd=candidate.get('estimated_actor_event_cost_usd'),
                actor_status=item['catalog_status'],direct_api=item['direct_api']['status'],
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
    next_url = path+'?'+urlencode(dict(q=q,source=source,offset=offset+50))
    prev_url = path+'?'+urlencode(dict(q=q,source=source,offset=max(0,offset-50)))
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Veriflow · {title}</title><style>{STYLE}</style><h1>Veriflow · Private collection engine</h1>
    <nav><a href="/">Products</a><a href="/reviews">Reviews</a><a href="/sources">Sources</a>
    <a href="/errors">Runs &amp; errors</a><a href="/trends">Google Trends</a><a href="/integrations">Integrations</a><a href="/collection">Collection &amp; cost</a><a href="/capabilities">Source audit</a></nav>
    <h2>{title}</h2>{controls}{table(rows)}<p><a href="{html.escape(prev_url)}">Previous</a> · <a href="{html.escape(next_url)}">Next</a></p>
    <small>Private administrative access · 50 records per page</small></html>'''


def serve(port=8080):
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
                with connect() as conn:
                    body = page(conn,request.path,parse_qs(request.query))
                status = 200 if body else 404
                body = (body or 'Not found').encode()
            except Exception:
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

        def log_message(self, *_):
            pass  # Never log search strings, Authorization headers, or review text.
    ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()
