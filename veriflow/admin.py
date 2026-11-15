"""Authenticated private administration; loopback by default, CSRF on writes."""
import base64
import hashlib
import hmac
import html
import os
import time
import json
from datetime import datetime,timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from .db import connect

STYLE = '''body{font:16px system-ui;margin:2rem;background:#111827;color:#e5e7eb}a{color:#93c5fd}
nav{display:flex;gap:1rem;margin:1.5rem 0}table{border-collapse:collapse;width:100%;background:#1f2937}
th,td{padding:.7rem;text-align:left;border-bottom:1px solid #374151;vertical-align:top}
input,select,button{padding:.6rem;margin:.3rem}td{max-width:28rem;overflow-wrap:anywhere;white-space:pre-wrap}
small{color:#a1a1aa}h1{font-size:1.8rem}'''

STYLE += '\n*{box-sizing:border-box}body{margin:0 auto;padding:1rem;max-width:1500px;line-height:1.5}nav{flex-wrap:wrap;gap:.55rem;padding:.8rem 0}nav a,.primary,button{display:inline-block;min-height:44px;padding:.65rem 1rem;border-radius:.65rem}nav a{background:#1f2937;text-decoration:none}.primary,button{background:#2563eb;color:white;border:0;font-weight:700;cursor:pointer}.hero{display:flex;align-items:center;justify-content:space-between;gap:1rem;padding:1.5rem;background:#172554;border:1px solid #334155;border-radius:1rem;margin:1rem 0}.hero h2{margin:.2rem 0}.eyebrow{font-size:.75rem;letter-spacing:.15em;color:#93c5fd}form{display:flex;align-items:end;flex-wrap:wrap;gap:.8rem;padding:1rem;margin:1rem 0;background:#1f2937;border-radius:.8rem}label{display:flex;flex-direction:column;gap:.25rem;flex:1;min-width:180px}input,select,textarea{width:100%;font:inherit;background:#0f172a;color:#f8fafc;border:1px solid #64748b;border-radius:.4rem;margin:0;padding:.7rem;min-height:44px}textarea{min-width:100%;resize:vertical}.check{flex-direction:row;align-items:center}.check input{width:22px;min-height:22px}.table-scroll{overflow:auto;border-radius:.7rem;margin:1rem 0}table{min-width:600px}th{white-space:nowrap}details{padding:.8rem;background:#182337;border-radius:.7rem;margin:1rem 0}summary{cursor:pointer;min-height:44px;font-weight:700}.notice{border-left:4px solid #fbbf24;padding:1rem;background:#292524}@media(max-width:640px){body{padding:.75rem}.hero{flex-direction:column;align-items:stretch}.hero .primary{text-align:center}h1{font-size:1.3rem}form{padding:.8rem}form label,form button{width:100%;flex-basis:100%;min-width:0}nav{gap:.35rem}nav a{padding:.5rem .65rem;font-size:.9rem}td{max-width:20rem}input,textarea,select{font-size:16px}}\n'


STYLE += ".stats{display:grid;grid-template-columns:repeat(4,1fr);gap:.7rem;margin:1rem 0}.stats div{background:#1f2937;border-radius:.7rem;padding:1rem}.stats strong,.stats span{display:block}.stats strong{font-size:1.6rem}.stats span{text-transform:capitalize;color:#cbd5e1}.product-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1rem}.product-card{background:#1f2937;padding:1rem;border:1px solid #334155;border-radius:.8rem}.product-card h3{font-size:1.2rem;margin-top:0}.product-card code{overflow-wrap:anywhere}.nav-more{margin:0;padding:0 .65rem}.nav-more summary{padding:.5rem}.nav-more a{margin:.3rem}@media(max-width:640px){.stats{grid-template-columns:repeat(2,1fr)}.product-grid{grid-template-columns:1fr}}"


def csrf_token(secret):
    stamp=str(int(time.time()))
    return stamp+'.'+hmac.new(secret.encode(),stamp.encode(),hashlib.sha256).hexdigest()


def valid_csrf(token,secret):
    try:
        stamp,signature=token.split('.',1)
        age=time.time()-int(stamp)
        return 0<=age<=3600 and hmac.compare_digest(signature,hmac.new(secret.encode(),stamp.encode(),hashlib.sha256).hexdigest())
    except (ValueError,AttributeError):return False


def render(title,content):
    links=[('/','Products'),('/collect','START COLLECTION'),('/jobs','Jobs'),('/reviews','Reviews'),('/coverage','Coverage'),('/categories','Categories'),('/settings','Sources & settings'),('/exports','Exports'),('/collection','Provider costs'),('/errors','Errors'),('/trends','Trends'),('/integrations','Integrations')]
    banner='<p class="notice">LOCAL FIXTURE PREVIEW — no live collection</p>' if os.environ.get('VERIFLOW_DEMO')=='true' else ''
    if os.environ.get('VERIFLOW_ENV_LABEL'):banner='<p class="notice">'+html.escape(os.environ['VERIFLOW_ENV_LABEL'])+'</p>'
    nav=''.join('<a href="'+url+'">'+label+'</a>' for url,label in links[:8])+'<details class="nav-more"><summary>More</summary>'+''.join('<a href="'+url+'">'+label+'</a>' for url,label in links[8:])+'</details>'
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Veriflow · '+html.escape(title)+'</title><style>'+STYLE+'</style><header><h1>Veriflow · Private collection engine</h1><nav>'+nav+'</nav></header><main>'+banner+'<h2>'+html.escape(title)+'</h2>'+content+'</main><footer>Private administration · Paid collection disabled unless separately authorized</footer></html>'


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
    def cell(key, value,row=None):
        escaped = html.escape(str(value) if value is not None else '—')
        if key=='review_text' and row and row.get('public_credit'):
            credit=html.escape(str(row['public_credit']))
            url=str(row.get('attribution_url') or '')
            byline=('<a href="'+html.escape(url,quote=True)+'" rel="noreferrer noopener">'+credit+'</a>') if url.startswith('https://') else credit
            return escaped+'<p><small>Credit: '+byline+' · '+html.escape(str(row.get('license_id') or ''))+'</small></p>'
        if key in ('review_id','product_id') and value:
            from urllib.parse import quote
            return '<a href="'+('/reviews/' if key=='review_id' else '/reviews?product=')+quote(str(value),safe='')+'">'+escaped+'</a>'
        if key=='artifact_name' and value:
            from .admin_ops import identifier
            try:return '<a href="/downloads/'+identifier(str(value).split('.')[0])+'">Download</a>'
            except Exception:return escaped
        if key in ('original_url','license_url','attribution_url') and str(value).startswith('https://'):
            return f'<a href="{escaped}" rel="noreferrer noopener">{"Original source" if key=="original_url" else "License" if key=="license_url" else "Attribution"}</a>'
        return escaped
    return '<div class="table-scroll"><table><thead><tr>' + ''.join('<th>'+html.escape(k.replace('_',' '))+'</th>' for k in keys) + '</tr></thead><tbody>' + ''.join('<tr>'+''.join('<td>'+cell(k,row[k],row)+'</td>' for k in keys)+'</tr>' for row in rows) + '</tbody></table></div>'


def page(conn, path, params,csrf=''):
    from .admin_ui import screen
    custom=screen(conn,path,params,csrf)
    if custom:return render(*custom)
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
        rows = conn.execute('''SELECT r.id AS review_id,p.name AS product,s.name AS source,r.review_text,l.public_credit,l.license_id,l.license_url,l.attribution_url,l.text_modified,r.rating,r.rating_scale,
            r.published_at,r.original_url,r.collected_at,r.duplicate_group
            FROM veriflow.reviews r JOIN veriflow.products p ON p.id=r.product_id
            JOIN veriflow.sources s ON s.id=r.source_id
            LEFT JOIN veriflow.review_licenses l ON l.review_id=r.id
            WHERE (p.name ILIKE %s OR r.review_text ILIKE %s) AND (%s='' OR r.source_id=%s)
            AND (%s='' OR r.product_id=CAST(NULLIF(%s,'') AS uuid))
            ORDER BY r.collected_at DESC,r.id LIMIT 50 OFFSET %s''', ('%'+q+'%','%'+q+'%',source,source,params.get('product',[''])[0],params.get('product',[''])[0],offset)).fetchall()
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
        from .pilot import summary
        limits=summary()
        controls = '<p>First-test ceiling: $'+html.escape(limits['max_total_usd'])+' total and '+str(limits['max_review_records'])+' review records. Paid execution: '+('enabled' if limits['paid_runs_enabled'] else 'disabled')+'.</p><h3>Reviews by source</h3>'+table(counts)+'<h3>Apify usage and cost</h3>'+table(costs)+'<p>Reservations are spending allowances. Reported usage is not an invoice-confirmed total. Uncertain starts retain their allowance and are never restarted automatically.</p>'
        rows = conn.execute("""SELECT j.id,s.name AS source,j.state,j.actor_id,j.actor_run_id,j.dataset_id,
            j.retrieved,j.inserted,j.duplicates,j.reserved_usd,j.reported_usage_usd,j.confirmed_billed_usd,
            j.error_code,j.poll_failures,j.next_poll_at,j.updated_at,j.created_at FROM veriflow.apify_jobs j JOIN veriflow.sources s ON s.id=j.source_id
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
    return render(title,controls+table(rows)+'<p><a href="'+html.escape(prev_url)+'">Previous</a> · <a href="'+html.escape(next_url)+'">Next</a></p>')


def serve(port=None,host='127.0.0.1'):
    from .config import load_environment
    load_environment()
    port=int(os.environ.get('PORT','8080')) if port is None else port
    if host not in ('127.0.0.1','0.0.0.0') or not 1<=port<=65535:
        raise ValueError('Invalid dashboard bind address')
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
                if request.path.startswith('/downloads/'):
                    return self.download(request.path)
                with connect() as conn:
                    body = page(conn,request.path,parse_qs(request.query),csrf_token(password))
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

        def do_POST(self):
            if not authorized(self.headers.get('Authorization',''),username,password):
                self.send_response(401);self.send_header('Cache-Control','no-store');self.end_headers();return
            try:
                length=int(self.headers.get('Content-Length','0'))
                ctype=self.headers.get('Content-Type','')
                if not 0<length<=5_000_000 or ctype.split(';')[0] not in ('application/x-www-form-urlencoded','multipart/form-data'):
                    self.send_response(413);self.end_headers();return
                raw=self.rfile.read(length)
                if ctype.startswith('multipart/form-data'):
                    from email.parser import BytesParser
                    from email.policy import default
                    message=BytesParser(policy=default).parsebytes(b'Content-Type: '+ctype.encode('ascii')+b'\r\nMIME-Version: 1.0\r\n\r\n'+raw)
                    parts=list(message.iter_parts())
                    if len(parts)>50:raise ValueError()
                    data={}
                    for part in parts:
                        key=part.get_param('name',header='content-disposition')
                        if not key or len(key)>100 or part.is_multipart():raise ValueError()
                        data.setdefault(key,[]).append(part.get_payload(decode=True).decode('utf-8-sig'))
                else:
                    data=parse_qs(raw.decode('utf-8'),keep_blank_values=True,max_num_fields=1000)
                if not valid_csrf(data.get('csrf',[''])[0],password):
                    self.send_response(403);self.end_headers();return
                from .admin_ui import dispatch
                with connect() as conn:location=dispatch(conn,urlsplit(self.path).path,data)
                self.send_response(303);self.send_header('Location',location);self.send_header('Cache-Control','no-store');self.end_headers()
            except Exception:
                self.send_response(400);self.send_header('Content-Type','text/plain; charset=utf-8');self.send_header('Cache-Control','no-store');self.end_headers()
                self.wfile.write(b'Request rejected. Check required fields, source approval and configured limits. No changes were saved.')

        def download(self,path):
            from .admin_ops import identifier
            from .exports import artifact_dir
            import shutil
            try:
                job_id=identifier(path.rsplit('/',1)[1])
                with connect() as conn:
                    row=conn.execute("SELECT artifact_name FROM veriflow.admin_jobs WHERE id=%s AND kind='export' AND state='succeeded' AND artifact_expires_at>now()",(job_id,)).fetchone()
                if not row:raise ValueError()
                root=artifact_dir();file=root/row['artifact_name']
                if file.is_symlink() or file.resolve().parent!=root.resolve():raise ValueError()
                with file.open('rb') as stream:
                    self.send_response(200);self.send_header('Content-Type','application/octet-stream')
                    self.send_header('Content-Disposition','attachment; filename="'+file.name+'"')
                    self.send_header('Content-Length',str(os.fstat(stream.fileno()).st_size));self.send_header('Cache-Control','no-store')
                    self.send_header('X-Content-Type-Options','nosniff');self.end_headers();shutil.copyfileobj(stream,self.wfile,64*1024)
            except Exception:
                self.send_response(404);self.send_header('Cache-Control','no-store');self.end_headers()

        def log_message(self, *_):
            pass  # Never log search strings, Authorization headers, or review text.
    ThreadingHTTPServer((host,port),Handler).serve_forever()
