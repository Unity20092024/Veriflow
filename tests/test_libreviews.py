import copy
import json
import unittest
from pathlib import Path
from veriflow.libreviews import extract_review
from veriflow.connectors import ApifyDatasetConnector,AccessDenied,CollectionError

HTML=Path('tests/fixtures/libreviews-firefox.html').read_text()


def source_grant():
    return ({'url':'https://lib.reviews','collection_method':'apify','full_text_allowed':True,
             'required_license_id':'CC-BY-SA-4.0','attribution_required':True},
            {'method':'apify','full_text_allowed':True,'license_id':'CC-BY-SA-4.0','terms_url':'https://lib.reviews/terms'})


class LibreviewsFixtureTests(unittest.TestCase):
    def test_offline_extraction_preserves_native_fields_and_required_credit(self):
        row=extract_review(HTML,'fixture-firefox','https://lib.reviews/mozilla-firefox')
        self.assertEqual(row['software_name'],'Mozilla Firefox')
        self.assertEqual(row['published_at'],'2026-01-01')
        self.assertEqual(row['rating'],3)
        self.assertIn('TEST FIXTURE',row['review_text'])
        source,grant=source_grant()
        record=ApifyDatasetConnector().collect(json.dumps([row]),'json',source,grant)[0]
        self.assertEqual(record.license_metadata['public_credit'],'Fixture author')
        self.assertTrue(record.license_metadata['text_modified'])

    def test_missing_or_mismatched_credit_license_or_modification_notice_rejected(self):
        source,grant=source_grant()
        original=extract_review(HTML,'fixture-firefox','https://lib.reviews/mozilla-firefox')
        for field,value in [('public_credit',''),('license_id','CC0'),('license_url','https://attacker.invalid/license'),
                            ('attribution_url','https://attacker.invalid/user/person'),('change_note','')]:
            row=copy.deepcopy(original);row['license_metadata'][field]=value
            with self.assertRaises(CollectionError):ApifyDatasetConnector().collect(json.dumps([row]),'json',source,grant)
        row=copy.deepcopy(original);del row['license_metadata']
        with self.assertRaises(AccessDenied):ApifyDatasetConnector().collect(json.dumps([row]),'json',source,grant)

    def test_ambiguous_html_and_missing_rating_date_or_author_rejected(self):
        for html in [HTML+HTML,HTML.replace('alt="3 stars"',''),HTML.replace('Fixture author',''),
                     HTML.replace('1/1/2026, 9:00:00 AM','unknown date')]:
            with self.assertRaises(CollectionError):extract_review(html,'fixture','https://lib.reviews/mozilla-firefox')
        with self.assertRaises(CollectionError):extract_review(HTML,'fixture','https://lib.reviews/api/reviews')

    def test_review_body_profile_links_cannot_replace_byline_credit(self):
        html=HTML.replace('TEST FIXTURE', '<a href="/user/other-person">Unrelated profile</a> TEST FIXTURE')
        row=extract_review(html,'fixture','https://lib.reviews/mozilla-firefox')
        self.assertEqual(row['license_metadata']['public_credit'],'Fixture author')

    def test_twenty_record_ceiling_applies_to_dataset_import(self):
        source,grant=source_grant();row=extract_review(HTML,'fixture','https://lib.reviews/mozilla-firefox')
        with self.assertRaises(CollectionError):ApifyDatasetConnector().collect(json.dumps([row]*21),'json',source,grant)

    def test_reviewed_actor_target_path_can_select_one_array_url(self):
        from veriflow.apify_pipeline import value_at
        value={'startUrls':[{'url':'https://lib.reviews/mozilla-firefox'}]}
        self.assertEqual(value_at(value,['startUrls','0','url']),'https://lib.reviews/mozilla-firefox')
        for path in [['startUrls','-1','url'],['startUrls','1','url']]:
            with self.assertRaises(CollectionError):value_at(value,path)

    def test_projected_actor_output_keeps_only_required_licensed_credit(self):
        from veriflow.apify_pipeline import normalize_items
        from veriflow.licensing import validate_mapping
        row=extract_review(HTML,'fixture-firefox','https://lib.reviews/mozilla-firefox')
        source,grant=source_grant()
        mapping={'fields':{k:[k] for k in ['external_id','software_name','review_text','rating','rating_scale','published_at','original_url']},
                 'license_fields':{k:['license_metadata',k] for k in ['public_credit','attribution_url']},
                 'license_constants':{k:v for k,v in row['license_metadata'].items() if k not in ('public_credit','attribution_url')}}
        validate_mapping(mapping,source,grant)
        projected=normalize_items([row],{'product_key':'fixture-firefox','field_mapping':mapping})
        result=ApifyDatasetConnector().collect(json.dumps(projected),'json',source,grant)[0]
        self.assertEqual(result.license_metadata,row['license_metadata'])
        mapping['license_fields'].pop('public_credit')
        with self.assertRaises(AccessDenied):validate_mapping(mapping,source,grant)
