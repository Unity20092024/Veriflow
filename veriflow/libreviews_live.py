"""Free, bounded HTTPS retrieval from lib.reviews public pages only."""
import hashlib
import re
import time
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit,urljoin,urlencode,unquote,parse_qs
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
from urllib.robotparser import RobotFileParser
from .connectors import CollectionError,AccessDenied,RateLimited,canonical_url
from .libreviews import extract_review

BASE='https://lib.reviews'
SOURCE_ID='lib-reviews'
USER_AGENT='Veriflow/0.1 (+private permitted software review research)'

class SourceUnavailable(CollectionError):
    code='free_source_unavailable'

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def public_url(value):
    value=canonical_url(urljoin(BASE+'/',value))
    p=urlsplit(value);path=unquote(p.path)
    if p.hostname!='lib.reviews' or p.netloc!='lib.reviews':raise AccessDenied('Wrong source origin')
    if path=='/actions/search':
        q=parse_qs(p.query)
        if set(q)!={'query'} or len(q['query'])!=1 or not 1<=len(q['query'][0])<=200:raise AccessDenied('Invalid search')
    else:
        if p.query:raise AccessDenied('Unexpected source query')
        static=path in ('/terms','/robots.txt')
        review=bool(re.fullmatch(r'/review/[0-9a-fA-F-]{36}',path))
        product=bool(re.fullmatch(r'/[\w.%-]+(?:/before/[0-9TZ:.+-]+)?',path))
        reserved=path.split('/')[1] in ('api','actions','signin','signout','register','user','static','feed','terms','robots.txt')
        if not static and not review and (not product or reserved):raise AccessDenied('Public product/review paths only')
    return value


class PublicPages(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack=[];self.reviews=[];self.next_page=None;self.products=[];self.title=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs);classes=set(a.get('class','').split())
        parents=set().union(*(s[1] for s in self.stack)) if self.stack else set()
        if tag=='h3' and 'search-match-heading' in classes:self.products.append(dict(name='',url='',description=''))
        if tag=='a':
            href=a.get('href','')
            if 'search-match-heading' in parents and self.products:self.products[-1]['url']=public_url(href)
            if 'feed-review' in parents and re.fullmatch(r'/review/[0-9a-fA-F-]{36}',href):self.reviews.append(public_url(href))
            if 'pagination-footer' in parents and '/before/' in href:self.next_page=public_url(href)
        if tag not in {'br','img','input','meta','link','hr'}:self.stack.append((tag,classes))
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==tag:del self.stack[i:];break
    def handle_data(self,data):
        if any(s[0] in ('script','style') for s in self.stack):return
        classes=set().union(*(s[1] for s in self.stack)) if self.stack else set()
        if any(s[0]=='h1' for s in self.stack):self.title.append(data)
        if self.products and 'search-match-heading' in classes:self.products[-1]['name']+=data
        if self.products and 'search-result-description' in classes:self.products[-1]['description']+=data


def software_category(description):
    text=description.casefold()
    if re.search(r'\b(web )?browser\b',text) and 'extension' not in text:return 'Web browsers'
    if 'extension' in text or 'add-on' in text:return 'Browser extensions'
    if re.search(r'\b(editor|development|compiler|programming)\b',text):return 'Developer tools'
    if re.search(r'\b(software|computer program|web application|mobile application|desktop application|mobile app|email client|chat client|operating system)\b',text):return 'Software'
    return None


class LibreReviewsClient:
    def __init__(self,transport=None,wait=time.sleep,clock=time.monotonic,interval=2):
        self.transport=transport or build_opener(NoRedirect()).open
        self.wait,self.clock,self.interval=wait,clock,max(2,interval)
        self.last=None;self.robots=None;self.terms_hash=None;self.requests=0
    def _read(self,url):
        url=public_url(url)
        for redirect in range(3):
            if self.robots and not self.robots.can_fetch(USER_AGENT,url):raise AccessDenied('Robots rules disallow this path')
            if self.last is not None:self.wait(max(0,self.interval-(self.clock()-self.last)))
            self.last=self.clock();self.requests+=1
            if self.requests>50:raise CollectionError('Source request bound reached')
            try:
                req=Request(url,headers={'User-Agent':USER_AGENT,'Accept':'text/html,text/plain','Accept-Language':'en'})
                with self.transport(req,timeout=20) as response:
                    raw=response.read(1_000_001)
                    if len(raw)>1_000_000:raise CollectionError('Source page exceeds limit')
                    return raw.decode('utf-8')
            except HTTPError as exc:
                if exc.code in (301,302,303,307,308) and redirect<2:
                    url=public_url(urljoin(url,exc.headers.get('Location','')));continue
                if exc.code==429:
                    retry=exc.headers.get('Retry-After','60')
                    try:delay=int(retry)
                    except ValueError:
                        try:delay=int((parsedate_to_datetime(retry)-datetime.now(timezone.utc)).total_seconds())
                        except (ValueError,TypeError):delay=60
                    raise RateLimited(delay) from None
                if exc.code in (401,403):raise AccessDenied('Source refused access') from None
                raise SourceUnavailable() from None
            except (URLError,TimeoutError,OSError,UnicodeDecodeError):raise SourceUnavailable() from None
        raise AccessDenied('Redirect limit reached')
    def verify_policy(self):
        if self.terms_hash:return self.terms_hash
        rules=self._read(BASE+'/robots.txt')
        self.robots=RobotFileParser();self.robots.parse(rules.splitlines())
        delay=self.robots.crawl_delay(USER_AGENT) or self.robots.crawl_delay('*') or 0
        self.interval=max(self.interval,delay)
        terms=self._read(BASE+'/terms')
        witnesses=('data mining','re-used','username next to','https://creativecommons.org/licenses/by-sa/4.0/')
        if not all(text in terms for text in witnesses):raise AccessDenied('Source terms need renewed review')
        # Hash static permission/licensing paragraphs rather than session HTML.
        paragraphs=re.findall(r'<(?:p|li)>.*?</(?:p|li)>',terms,flags=re.S)
        rights='\n'.join(p for p in paragraphs if 'data mining' in p or 'username next to' in p)
        self.terms_hash=hashlib.sha256(rights.encode()).hexdigest()
        return self.terms_hash
    def get(self,url):
        self.verify_policy();return self._read(url)
    def discover(self,query,limit=5):
        if not 1<=len(query.strip())<=200 or not 1<=limit<=10:raise CollectionError('Invalid discovery limits')
        p=PublicPages();p.feed(self.get(BASE+'/actions/search?'+urlencode({'query':query.strip()})))
        result=[];seen=set()
        for item in p.products:
            group=software_category(item['description'])
            if not group or not item['url'] or item['url'] in seen:continue
            # Accept only actual product slugs, never review/login paths.
            if len(urlsplit(item['url']).path.strip('/').split('/'))!=1:raise AccessDenied()
            seen.add(item['url']);result.append(dict(name=item['name'].strip(),url=item['url'],category=group))
            if len(result)>=limit:break
        return result
    def collect(self,product_url,expected_name,max_reviews=20,max_pages=5):
        product_url=public_url(product_url)
        slug=urlsplit(product_url).path
        if len(slug.strip('/').split('/'))!=1:raise AccessDenied('A product page is required')
        if not 1<=max_reviews<=20 or not 1<=max_pages<=5:raise CollectionError('Invalid collection limits')
        records=[];seen_reviews=set();visited=set();page=product_url
        for _ in range(max_pages):
            if page in visited:raise CollectionError('Pagination cycle')
            visited.add(page)
            listing=PublicPages();listing.feed(self.get(page))
            title=' '.join(''.join(listing.title).split())
            if title.casefold()!=expected_name.casefold():raise AccessDenied('Source product changed')
            for url in listing.reviews:
                if url in seen_reviews:continue
                seen_reviews.add(url)
                review=extract_review(self.get(url),product_url,url)
                if review['original_url']!=url or review['software_name'].casefold()!=expected_name.casefold():raise AccessDenied('Review belongs to another product')
                records.append(review)
                if len(records)>=max_reviews:break
            if len(records)>=max_reviews or not listing.next_page:break
            next_page=listing.next_page
            if not urlsplit(next_page).path.startswith(slug+'/before/'):raise AccessDenied('Cross-product pagination')
            page=next_page
        return dict(records=records,pages=len(visited),truncated=(len(records)>=max_reviews and (bool(listing.next_page) or any(u not in seen_reviews for u in listing.reviews))) or (bool(listing.next_page) and len(visited)>=max_pages),terms_hash=self.terms_hash)
