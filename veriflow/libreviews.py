"""Offline HTML adapter prototype. No HTTP client or Actor execution here."""
import re
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit,urljoin
from .connectors import CollectionError,canonical_url


class ReviewHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack=[];self.parts={};self.ids=[];self.rating=None;self.credit_url=None

    def handle_starttag(self,tag,attrs):
        a=dict(attrs);classes=set(a.get('class','').split())
        role=None
        if tag=='h1':role='product'
        if 'review-text' in classes:role='text'
        if 'review-title' in classes:role='title'
        if a.get('id')=='preview-review-byline-date':role='date'
        if 'feed-review' in classes:
            identifier=a.get('id','').removeprefix('review-')
            if not re.fullmatch(r'[0-9a-fA-F-]{36}',identifier):raise CollectionError('Missing review UUID')
            self.ids.append(identifier)
        if tag=='a' and a.get('href','').startswith('/user/'):
            # Only credit links within the review byline are eligible.
            if any('review-byline' in item[3] for item in self.stack):
                role='credit';self.credit_url=urljoin('https://lib.reviews',a['href'])
        if tag=='img' and a.get('alt') and any('review-rating' in item[3] for item in self.stack):
            match=re.fullmatch(r'([1-5]) stars?',a['alt'])
            if match:self.rating=int(match.group(1))
        inherited=next((item[1] for item in reversed(self.stack) if item[1]),None)
        in_review='feed-review' in classes or any(item[2] for item in self.stack)
        if tag=='br' and (role or inherited)=='text':self.parts.setdefault('text',[]).append('\n')
        if tag not in {'img','br','meta','link','input','hr'}:
            self.stack.append((tag,role or inherited,in_review,classes))

    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==tag:
                role=self.stack[i][1]
                del self.stack[i:]
                if tag in {'p','div'} and role=='text':self.parts.setdefault('text',[]).append('\n')
                break

    def handle_data(self,data):
        if any(item[0] in {'script','style'} for item in self.stack):return
        if self.stack and self.stack[-1][1]:self.parts.setdefault(self.stack[-1][1],[]).append(data)


def extract_review(html,product_key,page_url):
    url=canonical_url(page_url)
    if urlsplit(url).hostname!='lib.reviews' or urlsplit(url).path.startswith('/api/'):
        raise CollectionError('Only a reviewed public lib.reviews page is eligible')
    if len(html.encode())>1_000_000:raise CollectionError('Bounded HTML fixture required')
    parser=ReviewHTML();parser.feed(html)
    if len(parser.ids)!=1 or parser.rating is None:raise CollectionError('Expected one explicit rated review')
    text=lambda key:''.join(parser.parts.get(key,[])).strip()
    name=re.sub(r'^Review:\s*','',text('product')).strip()
    if not name or not text('text') or not text('credit') or not parser.credit_url:raise CollectionError('Missing review or required credit')
    try:published=datetime.strptime(text('date'),'%m/%d/%Y, %I:%M:%S %p').date().isoformat()
    except ValueError:raise CollectionError('Unsupported native publication date') from None
    return dict(external_id=parser.ids[0],product_key=product_key,software_name=name,
        review_text=('Title: '+text('title')+'\n\n' if text('title') else '')+text('text'),
        rating=parser.rating,rating_scale=5,published_at=published,
        original_url='https://lib.reviews/review/'+parser.ids[0],
        license_metadata=dict(license_id='CC-BY-SA-4.0',license_url='https://creativecommons.org/licenses/by-sa/4.0/',
            source_terms_url='https://lib.reviews/terms',public_credit=text('credit'),attribution_url=parser.credit_url,
            text_modified=True,change_note='HTML converted to plaintext; title labeled; source wording retained.'))
