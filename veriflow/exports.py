"""Authenticated review exports with conservative text-permission checks."""
import csv
import io
import json
import math
import uuid
import zipfile
from datetime import date, datetime
from decimal import Decimal
from xml.sax.saxutils import escape

MAX_ROWS = 10_000
MAX_EXPORT_BYTES = 20_000_000
HEADERS = (
    'review_id','source_id','source','product_id','product','external_id',
    'review_text','rating','rating_scale','published_at','original_url',
    'collected_at','duplicate_group','license_id','license_url',
    'source_terms_url','public_credit','attribution_url','text_modified','change_note',
    'categories',
)


class ExportError(ValueError):
    pass


def review_rows(conn, source='', product='', query='', limit=MAX_ROWS, offset=0):
    source = str(source or '')[:100]
    query = str(query or '')[:200]
    try:
        limit = int(limit)
        offset = int(offset)
    except (TypeError, ValueError):
        raise ExportError('invalid_export_range') from None
    if not 1 <= limit <= MAX_ROWS or not 0 <= offset <= 500_000:
        raise ExportError('invalid_export_range')
    if product:
        try:
            product = str(uuid.UUID(str(product)))
        except (ValueError, TypeError, AttributeError):
            raise ExportError('invalid_product_filter') from None
    else:
        product = None
    rows = conn.execute('''SELECT r.id AS review_id,s.id AS source_id,s.name AS source,
        p.id AS product_id,p.name AS product,r.external_id,
        CASE WHEN s.full_text_allowed AND a.full_text_allowed AND a.revoked_at IS NULL
          AND (a.expires_at>now() OR (
            s.id='lib-reviews' AND l.license_id='CC-BY-SA-4.0'
            AND EXISTS (SELECT 1 FROM veriflow.free_batches fb WHERE fb.authorization_id=a.id)))
          AND (s.required_license_id IS NULL OR l.license_id=s.required_license_id)
          THEN r.review_text ELSE NULL END AS review_text,
        r.rating,r.rating_scale,r.published_at,r.original_url,r.collected_at,
        r.duplicate_group,l.license_id,l.license_url,l.source_terms_url,
        l.public_credit,l.attribution_url,l.text_modified,l.change_note,
        (SELECT string_agg(c.name,', ' ORDER BY c.name) FROM veriflow.product_categories pc
         JOIN veriflow.categories c ON c.id=pc.category_id WHERE pc.product_id=p.id) AS categories
      FROM veriflow.reviews r
      JOIN veriflow.sources s ON s.id=r.source_id
      JOIN veriflow.products p ON p.id=r.product_id
      JOIN veriflow.authorizations a ON a.id=r.authorization_id
      LEFT JOIN veriflow.review_licenses l ON l.review_id=r.id
      WHERE (%s='' OR r.source_id=%s)
        AND (%s::uuid IS NULL OR r.product_id=%s)
        AND (%s='' OR p.name ILIKE %s OR r.review_text ILIKE %s)
      ORDER BY r.collected_at DESC,r.id
      LIMIT %s OFFSET %s''',
      (source,source,product,product,query,'%'+query+'%','%'+query+'%',limit,offset))
    result = []
    size = 0
    for row in rows:
        normalized = {key:_json_value(row.get(key)) for key in HEADERS}
        size += sum(len(str(value).encode('utf-8')) for value in normalized.values() if value is not None)
        if size > MAX_EXPORT_BYTES:
            raise ExportError('export_too_large')
        result.append(normalized)
    return result


def _json_value(value):
    if isinstance(value, (datetime,date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def render_json(rows):
    return json.dumps(rows,ensure_ascii=False,separators=(',',':')).encode('utf-8')


def render_jsonl(rows):
    return ''.join(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n'
                   for row in rows).encode('utf-8')


def render_csv(rows):
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output,fieldnames=HEADERS,extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        safe = {}
        for key in HEADERS:
            value = row.get(key)
            if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')):
                value = "'"+value
            safe[key] = value
        writer.writerow(safe)
    return output.getvalue().encode('utf-8-sig')


def _column_name(index):
    result = ''
    while index:
        index, remainder = divmod(index-1,26)
        result = chr(65+remainder)+result
    return result


def _xml_text(value):
    return ''.join(ch for ch in str(value)
                   if ch in '\t\n\r' or 0x20 <= ord(ch) <= 0xD7FF
                   or 0xE000 <= ord(ch) <= 0xFFFD
                   or 0x10000 <= ord(ch) <= 0x10FFFF)


def _xlsx_cell(reference, value):
    if value is None:
        value = ''
    if isinstance(value,bool):
        return f'<c r="{reference}" t="b"><v>{1 if value else 0}</v></c>'
    if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value):
        return f'<c r="{reference}"><v>{value}</v></c>'
    text = _xml_text(value)
    if len(text) > 32767:
        raise ExportError('xlsx_cell_limit')
    text = escape(text)
    preserve = ' xml:space="preserve"' if text[:1].isspace() or text[-1:].isspace() else ''
    return f'<c r="{reference}" t="inlineStr"><is><t{preserve}>{text}</t></is></c>'


def render_xlsx(rows):
    sheet_rows = ['<row r="1">'+''.join(
        _xlsx_cell(_column_name(i)+'1',header) for i,header in enumerate(HEADERS,1)
    )+'</row>']
    for row_number,row in enumerate(rows,2):
        cells = ''.join(_xlsx_cell(_column_name(i)+str(row_number),row.get(header))
                        for i,header in enumerate(HEADERS,1))
        sheet_rows.append(f'<row r="{row_number}">{cells}</row>')
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<sheetData>'+''.join(sheet_rows)+'</sheetData></worksheet>')
    files = {
        '[Content_Types].xml':(
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>'
        ),
        '_rels/.rels':(
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>'
        ),
        'xl/workbook.xml':(
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Reviews" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        'xl/_rels/workbook.xml.rels':(
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '</Relationships>'
        ),
        'xl/worksheets/sheet1.xml':sheet,
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as workbook:
        for path,content in files.items():
            workbook.writestr(path,content)
    return output.getvalue()


EXPORTS = {
    'jsonl':('application/x-ndjson; charset=utf-8','reviews.jsonl',render_jsonl),
    'csv':('text/csv; charset=utf-8','reviews.csv',render_csv),
    'json':('application/json; charset=utf-8','reviews.json',render_json),
    'xlsx':('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','reviews.xlsx',render_xlsx),
}
