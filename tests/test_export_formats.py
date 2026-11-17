import io
import json
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from veriflow.exports import write_rows,xlsx,filters,safe_cell
from veriflow.connectors import CollectionError
from veriflow.admin import csrf_token,valid_csrf

class ExportFormatTests(unittest.TestCase):
    def test_json_and_jsonl_preserve_full_text_and_provenance(self):
        row=dict(review_text='Actual fixture wording\nΩ',original_url='https://example.invalid/review/1',public_credit='Required fixture credit')
        for fmt in ('json','jsonl'):
            out=io.StringIO();self.assertEqual(write_rows(out,iter([row]),fmt),1)
            parsed=json.loads(out.getvalue());self.assertEqual(parsed[0] if fmt=='json' else parsed,row)

    def test_csv_protects_formulas_and_excel_uses_inline_text(self):
        text='  =HYPERLINK("https://example.invalid")'
        self.assertTrue(safe_cell(text).startswith("'"))
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'reviews.xlsx';self.assertEqual(xlsx(path,iter([dict(review_text=text)])),1)
            with zipfile.ZipFile(path) as z:
                for name in z.namelist():ET.fromstring(z.read(name))
                xml=z.read('xl/worksheets/sheet1.xml')
                self.assertNotIn(b'<f>',xml)
                self.assertIn(b'inlineStr',xml)

    def test_export_filter_limits_and_invalid_formats_fail_closed(self):
        for value in ({'format':'html'},{'limit':100001},{'product':'not-a-uuid'},{'extra':'field'}):
            with self.assertRaises((CollectionError,ValueError)):filters(value)

    def test_csrf_tampering_expiry_and_different_operator_secret(self):
        from unittest.mock import patch
        token=csrf_token('fixture-secret')
        self.assertTrue(valid_csrf(token,'fixture-secret'))
        self.assertFalse(valid_csrf(token,'other-secret'))
        self.assertFalse(valid_csrf('invalid','fixture-secret'))
        with patch('veriflow.admin.time.time',return_value=10**12):self.assertFalse(valid_csrf(token,'fixture-secret'))
