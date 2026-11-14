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
    elif path == '/trends':
        title = 'Google Trends research'
        controls = '<p>Market research is stored separately from reviews. Live collection awaits Composio capability discovery and source approval.</p>'
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
    <a href="/errors">Runs &amp; errors</a><a href="/trends">Google Trends</a></nav>
    <h2>{title}</h2>{controls}{table(rows)}<p><a href="{html.escape(prev_url)}">Previous</a> · <a href="{html.escape(next_url)}">Next</a></p>
    <small>Private administrative access · 50 records per page</small></html>'''


def serve(port=8080):
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
