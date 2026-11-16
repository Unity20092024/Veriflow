import csv
import io
import json
import unittest
import zipfile
from xml.etree import ElementTree
import uuid

from veriflow.admin import page
from veriflow.exports import HEADERS, render_csv, render_json, render_xlsx, review_rows, ExportError


def sample_row():
    return {key:None for key in HEADERS} | {
        'review_id':'fixture-id',
        'source':'Fixture source',
        'product':'Fixture product',
        'review_text':'=not-a-formula',
        'original_url':'https://reviews.example/fixture',
        'public_credit':'Fixture reviewer',
    }


class ExportTests(unittest.TestCase):
    def test_json_includes_attribution_fields(self):
        rows=[sample_row()]
        decoded=json.loads(render_json(rows))
        self.assertEqual(decoded[0]['public_credit'],'Fixture reviewer')
        self.assertEqual(decoded[0]['review_text'],'=not-a-formula')

    def test_csv_neutralizes_spreadsheet_formulas(self):
        content=render_csv([sample_row()]).decode('utf-8-sig')
        rows=list(csv.DictReader(io.StringIO(content)))
        self.assertEqual(rows[0]['review_text'],"'=not-a-formula")
        self.assertEqual(rows[0]['public_credit'],'Fixture reviewer')
        self.assertIn('attribution_url',rows[0])

    def test_xlsx_is_a_valid_inline_string_workbook(self):
        content=render_xlsx([sample_row()])
        with zipfile.ZipFile(io.BytesIO(content)) as workbook:
            self.assertIn('xl/worksheets/sheet1.xml',workbook.namelist())
            sheet=workbook.read('xl/worksheets/sheet1.xml').decode()
        self.assertIn('Fixture reviewer',sheet)
        self.assertIn('t="inlineStr"',sheet)
        self.assertNotIn('<f>',sheet)

    def test_xlsx_rejects_values_over_excel_cell_limit(self):
        row=sample_row()
        row['review_text']='x'*32768
        with self.assertRaises(ExportError):
            render_xlsx([row])

    def test_export_queries_require_valid_ranges(self):
        with self.assertRaises(ExportError):
            review_rows(None,limit=10001)
        with self.assertRaises(ExportError):
            review_rows(None,product='not-a-uuid')

    def test_export_query_hides_text_without_current_permission(self):
        class Cursor:
            def __iter__(self):
                return iter([sample_row()])
        class Connection:
            def execute(self,sql,params):
                self.sql,self.params=sql,params
                return Cursor()
        conn=Connection()
        review_rows(conn,source='source-id',query='search')
        self.assertIn('a.revoked_at IS NULL',conn.sql)
        self.assertIn('a.expires_at>now()',conn.sql)
        self.assertIn('CASE WHEN s.full_text_allowed AND a.full_text_allowed',conn.sql)
        self.assertNotIn('search',conn.sql)
        self.assertIn('%search%',conn.params)

    def test_xlsx_sheet_xml_is_well_formed(self):
        content=render_xlsx([sample_row()])
        with zipfile.ZipFile(io.BytesIO(content)) as workbook:
            ElementTree.fromstring(workbook.read('xl/worksheets/sheet1.xml'))

    def test_dashboard_export_links_and_review_query_share_all_filters(self):
        product_id = str(uuid.UUID('00000000-0000-4000-8000-000000000123'))

        class EmptyResult:
            def fetchall(self):
                return []

            def __iter__(self):
                return iter([])

        class Connection:
            def __init__(self):
                self.review_query = None

            def execute(self, sql, params=()):
                if 'FROM veriflow.reviews r JOIN veriflow.products p' in sql:
                    self.review_query = (sql, params)
                return EmptyResult()

        conn = Connection()
        html = page(conn, '/reviews', {
            'q': ['match this'],
            'source': ['google-play'],
            'product': [product_id],
        })
        self.assertIn('/exports/reviews.csv?q=match+this&amp;source=google-play&amp;product='+product_id, html)
        self.assertIn('/exports/reviews.xlsx?q=match+this&amp;source=google-play&amp;product='+product_id, html)
        self.assertIn('/exports/reviews.json?q=match+this&amp;source=google-play&amp;product='+product_id, html)
        self.assertIn('/exports/reviews.jsonl?q=match+this&amp;source=google-play&amp;product='+product_id, html)
        self.assertEqual(conn.review_query[1][-3:-1], (product_id, product_id))
        self.assertIn('r.product_id=%s', conn.review_query[0])


if __name__ == '__main__':
    unittest.main()
