"""Export genuine permitted stored reviews, and verify all output row counts."""
import csv
import io
import json
import os
from pathlib import Path
import zipfile
from xml.etree import ElementTree as ET

from veriflow.db import connect
from veriflow.exports import EXPORTS, review_rows
from veriflow.bounded_collection import progress


def main():
    output = Path('generated-artifacts/review-exports')
    output.mkdir(parents=True, exist_ok=True)
    os.chmod(output, 0o700)
    with connect() as conn:
        rows = review_rows(conn)
        status = progress(conn)
    for row in rows:
        if row['source_id']=='lib-reviews' and row['review_text']:
            required = ('license_id','license_url','public_credit','attribution_url',
                        'source_terms_url','original_url','change_note')
            if not all(row.get(key) for key in required):
                raise ValueError('Licensed export is missing required attribution')
    files = []
    for extension, (_, name, render) in EXPORTS.items():
        content = render(rows)
        path = output/name
        path.write_bytes(content)
        os.chmod(path, 0o600)
        if extension == 'csv':
            count = len(list(csv.DictReader(io.StringIO(content.decode('utf-8-sig')))))
        elif extension == 'json':
            count = len(json.loads(content))
        elif extension == 'jsonl':
            count = len([json.loads(line) for line in content.splitlines()])
        else:
            with zipfile.ZipFile(io.BytesIO(content)) as book:
                if book.testzip() is not None:
                    raise ValueError('Corrupt workbook')
                sheet = ET.fromstring(book.read('xl/worksheets/sheet1.xml'))
                count = len(sheet.findall('.//{*}row'))-1
        if count != len(rows):
            raise ValueError('Export row count differs from genuine stored records')
        files.append({'path': str(path), 'records': count, 'bytes': len(content)})
    report = {'records': len(rows), 'formats_verified': files, 'batch': status,
              'attribution_verified': True, 'synthetic_live_records': False}
    (output/'collection-report.json').write_text(json.dumps(report, default=str, indent=2))
    with zipfile.ZipFile(output.parent/'veriflow-collected-reviews.zip',
                         'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.iterdir()):
            archive.write(path, path.name)
        archive.write('docs/veriflow/approved-free-batch.md', 'collection-scope-and-license.md')
    print(json.dumps(report, default=str))


if __name__ == '__main__':
    main()
