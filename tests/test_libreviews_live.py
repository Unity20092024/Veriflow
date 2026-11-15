import io
import unittest
from urllib.error import HTTPError
from veriflow.libreviews_live import LibreReviewsClient,BASE,public_url
from veriflow.connectors import AccessDenied,RateLimited,CollectionError

ONE='11111111-1111-4111-8111-111111111111'
TWO='22222222-2222-4222-8222-222222222222'
TERMS='<p>data mining and re-used content</p><li>https://creativecommons.org/licenses/by-sa/4.0/ username next to contributions</li>'

def listing(ids,next_page=None):
    return '<h1>Fixture Browser</h1>'+''.join('<div class="feed-review"><a href="/review/'+rid+'">Permanent link</a></div>' for rid in ids)+('<div class="pagination-footer"><a href="'+next_page+'">Older reviews</a></div>' if next_page else '')

def review(rid):
    return '<h1>Review: Fixture Browser</h1><div class="review"><div class="review-rating"><img alt="4 stars"></div><div class="review-title">Fixture title</div><div class="review-text">TEST FIXTURE ONLY '+rid+'</div><div class="review-byline"><a href="/user/fixture-credit">Fixture credit</a><span id="preview-review-byline-date">01/01/2026, 1:00:00 PM</span></div></div>'

class ClientTests(unittest.TestCase):
    def client(self,documents,errors=None):
        calls=[]
        def get(req,timeout):
            calls.append(req.full_url)
            path=req.full_url.removeprefix(BASE)
            if errors and path in errors:raise errors[path]
            return io.BytesIO(data[path].encode())
        self.calls=calls
        data={'/robots.txt':'User-agent: *\nDisallow: /api/','/terms':TERMS,**documents}
        return LibreReviewsClient(transport=get,wait=lambda seconds:None)

    def test_pagination_native_permalinks_attribution_and_duplicate_links(self):
        older='/fixture-browser/before/2026-01-01T00:00:00Z'
        c=self.client({'/fixture-browser':listing([ONE],older),older:listing([ONE,TWO]),'/review/'+ONE:review(ONE),'/review/'+TWO:review(TWO)})
        result=c.collect(BASE+'/fixture-browser','Fixture Browser')
        self.assertEqual(result['pages'],2)
        self.assertEqual(len(result['records']),2)
        self.assertEqual(self.calls.count(BASE+'/review/'+ONE),1)
        r=result['records'][0]
        self.assertEqual(r['external_id'],ONE)
        self.assertEqual(r['license_metadata']['public_credit'],'Fixture credit')
        self.assertEqual(r['rating'],4)
        self.assertEqual(r['published_at'],'2026-01-01')

    def test_search_discovers_real_subject_metadata_not_review_excerpts(self):
        html='<h3 class="search-match-heading"><a href="/fixture-browser">Fixture Browser</a></h3><div class="search-result-description">free and open source web browser</div><h3 class="search-match-heading"><a href="/bakery">Bakery</a></h3><div class="search-result-description">bread shop</div><h3><a href="/misleading">Browser word in a review</a></h3>'
        c=self.client({'/actions/search?query=browser':html})
        found=c.discover('browser')
        self.assertEqual(len(found),1);self.assertEqual(found[0]['category'],'Web browsers')

    def test_external_redirect_api_and_cross_product_pagination_rejected(self):
        for url in ('https://evil.invalid/product','http://lib.reviews/product','https://lib.reviews/api/data','https://lib.reviews/user/person'):
            with self.assertRaises((CollectionError,ValueError)):public_url(url)
        error=HTTPError(BASE+'/fixture-browser',302,'redirect',{'Location':'https://127.0.0.1/private'},None)
        c=self.client({},errors={'/fixture-browser':error})
        with self.assertRaises(AccessDenied):c.collect(BASE+'/fixture-browser','Fixture Browser')
        c=self.client({'/fixture-browser':listing([],'/other-product/before/2026-01-01T00:00:00Z')})
        with self.assertRaises(AccessDenied):c.collect(BASE+'/fixture-browser','Fixture Browser')

    def test_robot_and_terms_changes_fail_closed(self):
        c=self.client({'/robots.txt':'User-agent: *\nDisallow: /'})
        with self.assertRaises(AccessDenied):c.collect(BASE+'/fixture-browser','Fixture Browser')
        c=self.client({'/terms':'Terms no longer establish the reviewed permission'})
        with self.assertRaises(AccessDenied):c.discover('browser')

    def test_rate_limit_and_record_bound_no_hidden_retries(self):
        error=HTTPError(BASE+'/fixture-browser',429,'limited',{'Retry-After':'900'},None)
        c=self.client({},errors={'/fixture-browser':error})
        with self.assertRaises(RateLimited) as caught:c.collect(BASE+'/fixture-browser','Fixture Browser')
        self.assertEqual(caught.exception.retry_after,900)
        self.assertEqual(self.calls.count(BASE+'/fixture-browser'),1)
        c=self.client({'/fixture-browser':listing([ONE,TWO]),'/review/'+ONE:review(ONE)})
        self.assertEqual(len(c.collect(BASE+'/fixture-browser','Fixture Browser',max_reviews=1)['records']),1)
        self.assertNotIn(BASE+'/review/'+TWO,self.calls)
