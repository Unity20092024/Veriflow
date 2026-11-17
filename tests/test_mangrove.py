import io
import json
import unittest
from urllib.parse import urlsplit,parse_qs
from veriflow.mangrove_live import MangroveClient,normalized
from veriflow.connectors import AccessDenied

TERMS='Share commercially under a license. When no license is specified, CC-BY-4.0 applies. Attribution through hyperlink to the review.'
def entry(signature='A'*86,license_id=None,subject='https://bitwarden.com'):
    metadata={} if license_id is None else {'license':license_id}
    return dict(signature=signature,kid='DO NOT RETAIN',jwt='DO NOT RETAIN',payload=dict(sub=subject,iat=1767225600,rating=75,opinion='TEST FIXTURE ONLY software review',metadata=metadata))

class MangroveTests(unittest.TestCase):
    def test_normalization_preserves_native_rating_and_omits_identity_keys(self):
        r=normalized(entry(),'https://bitwarden.com','Bitwarden')
        self.assertEqual(r['rating'],75);self.assertEqual(r['rating_scale'],100)
        self.assertNotIn('DO NOT RETAIN',json.dumps(r))
        self.assertEqual(r['license_metadata']['license_id'],'CC-BY-4.0')
        self.assertTrue(r['original_url'].startswith('https://api.mangrove.reviews/review/'))
        with self.assertRaises(AccessDenied):normalized(entry(license_id='CC-BY-SA-4.0'),'https://bitwarden.com','Bitwarden')
        with self.assertRaises(AccessDenied):normalized(entry(subject='https://other.invalid'),'https://bitwarden.com','Bitwarden')

    def client(self,first,second=()):
        self.offsets=[]
        def transport(request,timeout):
            if request.full_url.endswith('/terms'):return io.BytesIO(TERMS.encode())
            self.assertEqual(request.get_header('Accept'),'application/json')
            query=parse_qs(urlsplit(request.full_url).query);offset=int(query['offset'][0]);self.offsets.append(offset)
            rows=first if offset==0 else second
            return io.BytesIO(json.dumps({'reviews':list(rows)}).encode())
        return MangroveClient(transport=transport,wait=lambda seconds:None)

    def test_pagination_skips_incompatible_license_and_preserves_scope(self):
        bad=[entry(str(i).zfill(86),license_id='CC-BY-SA-4.0') for i in range(20)]
        c=self.client(bad,[entry()]);result=c.collect('https://bitwarden.com','Bitwarden')
        self.assertEqual(self.offsets,[0,20]);self.assertEqual(result['pages'],2)
        self.assertEqual(result['skipped'],20);self.assertEqual(len(result['records']),1)

    def test_online_discovery_requires_real_eligible_software_record(self):
        c=self.client([entry(),entry('B'*86,subject='geo:1,2'),entry('C'*86,license_id='CC-BY-SA-4.0',subject='https://github.com')])
        self.assertEqual(c.discover('password manager'),[dict(name='Bitwarden',url='https://bitwarden.com',category='Password managers')])
        with self.assertRaises(AccessDenied):c.read('https://other.invalid/reviews')
