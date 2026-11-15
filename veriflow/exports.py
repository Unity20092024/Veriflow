"""Private streaming exports with attribution and spreadsheet formula protection."""
import csv
import io
import json
import os
import stat
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape
from .connectors import CollectionError
from .admin_ops import identifier

FORMATS={'csv','xlsx','json','jsonl','zip'}
FIELDS=['review_id','product_id','run_id','authorization_id','actor_run_id','actor_build_id','dataset_id','product','vendor','source','review_text','rating','rating_scale','published_at','original_url',
        'collected_at','external_id','license_id','license_url','public_credit','attribution_url','text_modified','change_note','duplicate_group']


def filters(value):
    if not isinstance(value,dict) or set(value)-{'q','source','product','limit','format'}:raise CollectionError('Invalid export filters')
    result=dict(q=str(value.get('q',''))[:200],source=str(value.get('source',''))[:100],product=str(value.get('product','')),limit=int(value.get('limit',10000)),format=value.get('format','csv'))
    if result['product']:result['product']=identifier(result['product'])
    if not 1<=result['limit']<=100000 or result['format'] not in FORMATS:raise CollectionError('Export limit/format invalid')
    return result


def artifact_dir():
    path=Path(os.environ.get('VERIFLOW_ARTIFACT_DIR',str(Path.home()/'.local/share/veriflow/exports'))).absolute()
    repo=Path(__file__).resolve().parents[1]
    if path.is_symlink() or path.resolve().is_relative_to(repo):raise CollectionError('Private export storage must be outside source')
    path.mkdir(mode=0o700,parents=True,exist_ok=True)
    info=path.stat()
    if info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)&0o077:raise CollectionError('Export directory must be owner-only')
    return path


def rows(conn,options):
    f=filters(options)
    # Named server cursor bounds memory. Dataset is a transaction snapshot.
    with conn.cursor(name='veriflow_export') as cursor:
        cursor.execute('''SELECT r.id AS review_id,r.product_id,r.run_id,r.authorization_id,j.actor_run_id,j.build_id AS actor_build_id,j.dataset_id,p.name AS product,p.vendor,s.name AS source,
            CASE WHEN s.full_text_allowed AND a.full_text_allowed AND a.revoked_at IS NULL AND a.expires_at>now()
              THEN r.review_text ELSE NULL END AS review_text,r.rating,r.rating_scale,r.published_at,r.original_url,
            r.collected_at,r.external_id,l.license_id,l.license_url,l.public_credit,l.attribution_url,l.text_modified,l.change_note,r.duplicate_group
            FROM veriflow.reviews r JOIN veriflow.products p ON p.id=r.product_id
            JOIN veriflow.sources s ON s.id=r.source_id JOIN veriflow.authorizations a ON a.id=r.authorization_id
            LEFT JOIN veriflow.review_licenses l ON l.review_id=r.id
            LEFT JOIN veriflow.collection_runs cr ON cr.id=r.run_id
            LEFT JOIN veriflow.apify_jobs j ON j.id=cr.provider_job_id
            WHERE (p.name ILIKE %s OR r.review_text ILIKE %s) AND (%s='' OR r.source_id=%s)
            AND (%s='' OR r.product_id=CAST(NULLIF(%s,'') AS uuid)) ORDER BY r.id LIMIT %s''',
            ('%'+f['q']+'%','%'+f['q']+'%',f['source'],f['source'],f['product'],f['product'],f['limit']))
        while True:
            batch=cursor.fetchmany(500)
            if not batch:break
            for row in batch:yield {k:str(v) if v is not None and not isinstance(v,(str,float,int,bool)) else v for k,v in row.items()}


def safe_cell(value):
    s='' if value is None else str(value)
    return "'"+s if s.startswith(('\t','\r','\n')) or s.lstrip().startswith(('=','+','-','@','\t','\r','\n')) else s


def write_rows(stream,records,fmt):
    count=0
    if fmt=='csv':
        writer=csv.writer(stream);writer.writerow(FIELDS)
        for r in records:writer.writerow([safe_cell(r.get(k)) for k in FIELDS]);count+=1
    elif fmt=='jsonl':
        for r in records:stream.write(json.dumps(r,ensure_ascii=False)+'\n');count+=1
    elif fmt=='json':
        stream.write('[')
        for r in records:
            if count:stream.write(',\n')
            stream.write(json.dumps(r,ensure_ascii=False));count+=1
        stream.write(']\n')
    else:raise CollectionError('Unsupported writer')
    return count


def xlsx(path,records):
    # Inline strings prevent formulas; no third-party spreadsheet dependency.
    count=0
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Reviews" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        with z.open('xl/worksheets/sheet1.xml','w') as sheet:
            sheet.write(b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>')
            def row(values):
                sheet.write(b'<row>')
                for v in values:
                    s='' if v is None else str(v)
                    # Excel max text length; original full text remains in JSON/JSONL/ZIP.
                    if len(s)>32767:raise CollectionError('Excel cell limit exceeded; use JSONL')
                    s=''.join(c for c in s if c in '\t\r\n' or ord(c)>=32)
                    sheet.write(('<c t="inlineStr"><is><t xml:space="preserve">'+escape(s)+'</t></is></c>').encode())
                sheet.write(b'</row>')
            row(FIELDS)
            for r in records:row(r.get(k) for k in FIELDS);count+=1
            sheet.write(b'</sheetData></worksheet>')
    return count


def build_export(conn,job_id,options):
    job_id=identifier(job_id);f=filters(options);root=artifact_dir()
    final=root/(job_id+'.'+f['format']);temporary=root/(job_id+'.partial')
    temporary.unlink(missing_ok=True)
    fd=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    try:
        if f['format']=='xlsx':count=xlsx(temporary,rows(conn,f))
        elif f['format']=='zip':
            # One streaming source read; JSONL avoids ZIP member paths from input.
            with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as z:
                with z.open('reviews.jsonl','w') as member:
                    with io.TextIOWrapper(member,encoding='utf-8') as text:count=write_rows(text,rows(conn,f),'jsonl')
                z.writestr('README.txt','Private review export. Preserve source URLs, required credit, license links and change notes.\nText is omitted where current full-text authorization is unavailable. No public redistribution permission is implied.\n')
                z.writestr('manifest.json',json.dumps(dict(records=count,format='jsonl',filters=f)))
        else:
            with temporary.open('w',encoding='utf-8',newline='') as out:count=write_rows(out,rows(conn,f),f['format'])
        os.replace(temporary,final)
    finally:
        temporary.unlink(missing_ok=True)
    return dict(artifact_name=final.name,records=count,format=f['format'])


def purge_expired(conn):
    root=artifact_dir()
    expired=conn.execute('''SELECT id,artifact_name FROM veriflow.admin_jobs WHERE kind='export'
        AND artifact_name IS NOT NULL AND artifact_expires_at<=now() LIMIT 100 FOR UPDATE SKIP LOCKED''').fetchall()
    for job in expired:
        # Never accept directory components from a database filename.
        name=job['artifact_name']
        if Path(name).name!=name:raise CollectionError('Invalid artifact path')
        (root/name).unlink(missing_ok=True)
        conn.execute('UPDATE veriflow.admin_jobs SET artifact_name=NULL WHERE id=%s',(job['id'],))
    return len(expired)
