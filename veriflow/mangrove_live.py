"""Bounded free Mangrove API; retain only review fields, not JWTs/issuer keys."""
import hashlib
import json
import re
import time
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode,quote,urlsplit
from urllib.request import Request,build_opener
from urllib.error import HTTPError,URLError
from html.parser import HTMLParser
from .libreviews_live import NoRedirect,SourceUnavailable
from .connectors import AccessDenied,CollectionError,RateLimited

SOURCE_ID='mangrove-reviews'
BASE='https://mangrove.reviews'
API='https://api.mangrove.reviews'
# Audited software subjects; discovery still requires actual API reviews.
SOFTWARE={
 'https://bitwarden.com':('Bitwarden','Password managers'),
 'https://github.com':('GitHub','Developer platforms'),
 'https://codeberg.org':('Codeberg','Developer platforms'),
 'https://keybase.io':('Keybase','Communication'),
 'https://mangrove.reviews':('Mangrove','Review platforms'),
}

class VisibleText(HTMLParser):
    def __init__(self):super().__init__();self.skip=0;self.parts=[]
    def handle_starttag(self,t,a):
        if t in ('script','style'):self.skip+=1
    def handle_endtag(self,t):
        if t in ('script','style'):self.skip=max(0,self.skip-1)
    def handle_data(self,d):
        if not self.skip:self.parts.append(d)


def normalized(entry,subject,name):
    p=entry.get('payload');signature=entry.get('signature')
    if not isinstance(p,dict) or not isinstance(signature,str) or not re.fullmatch(r'[A-Za-z0-9_-]{40,200}',signature):raise CollectionError('Malformed native review')
    meta=p.get('metadata') or {}
    if not isinstance(meta,dict):raise CollectionError('Invalid license metadata')
    license_id=meta.get('license',p.get('license','CC-BY-4.0'))
    if license_id!='CC-BY-4.0':raise AccessDenied('This connector accepts only native CC-BY-4.0 reviews')
    if p.get('sub')!=subject or p.get('action'):raise AccessDenied('Wrong software subject or action record')
    opinion=p.get('opinion');rating=p.get('rating');iat=p.get('iat')
    if not isinstance(opinion,str) or not opinion.strip() or len(opinion)>100000:raise CollectionError('Opinion text required')
    if isinstance(rating,bool) or not isinstance(rating,(int,float)) or not 0<=rating<=100:raise CollectionError('Invalid original rating')
    if isinstance(iat,bool) or not isinstance(iat,int) or iat<0:raise CollectionError('Invalid source publication time')
    original=API+'/review/'+quote(signature,safe='')
    return dict(external_id=signature,product_key=subject,software_name=name,review_text=opinion,
        rating=rating,rating_scale=100,published_at=datetime.fromtimestamp(iat,timezone.utc).date().isoformat(),original_url=original,
        license_metadata=dict(license_id='CC-BY-4.0',license_url='https://creativecommons.org/licenses/by/4.0/',
            source_terms_url=BASE+'/terms',public_credit='Original review on Mangrove',attribution_url=original,
            text_modified=False,change_note=None))


class MangroveClient:
    def __init__(self,transport=None,wait=time.sleep,clock=time.monotonic):
        self.transport=transport or build_opener(NoRedirect()).open;self.wait=wait;self.clock=clock
        self.last=None;self.requests=0;self.terms_hash=None
    def read(self,url):
        p=urlsplit(url)
        if p.scheme!='https' or p.username or p.password or p.port is not None:raise AccessDenied()
        if not ((p.netloc=='mangrove.reviews' and p.path=='/terms' and not p.query) or (p.netloc=='api.mangrove.reviews' and p.path=='/reviews')):raise AccessDenied('Fixed source endpoints only')
        if self.last is not None:self.wait(max(0,2-(self.clock()-self.last)))
        self.last=self.clock();self.requests+=1
        if self.requests>30:raise CollectionError('API request limit')
        try:
            with self.transport(Request(url,headers={'User-Agent':'Veriflow/0.1 (bounded permitted research)','Accept':'application/json' if p.netloc=='api.mangrove.reviews' else 'text/html'}),timeout=20) as response:
                raw=response.read(1_000_001)
                if len(raw)>1_000_000:raise CollectionError('Source response too large')
                return raw.decode('utf-8')
        except HTTPError as exc:
            if exc.code==429:
                retry=exc.headers.get('Retry-After','60')
                try:seconds=int(retry)
                except ValueError:
                    try:seconds=int((parsedate_to_datetime(retry)-datetime.now(timezone.utc)).total_seconds())
                    except (ValueError,TypeError):seconds=60
                raise RateLimited(seconds) from None
            if exc.code in (301,302,303,307,308,401,403):raise AccessDenied('Source refused or redirected access') from None
            raise SourceUnavailable() from None
        except (URLError,TimeoutError,OSError,UnicodeDecodeError):raise SourceUnavailable() from None
    def verify_policy(self):
        if self.terms_hash:return self.terms_hash
        raw=self.read(BASE+'/terms');p=VisibleText();p.feed(raw);text=' '.join(p.parts)
        if not all(w in text for w in ('commercially','When no license is specified, CC-BY-4.0 applies.','hyperlink','license')):raise AccessDenied('Source terms need review')
        self.terms_hash=hashlib.sha256(text.encode()).hexdigest();return self.terms_hash
    def page(self,params):
        self.verify_policy()
        value=json.loads(self.read(API+'/reviews?'+urlencode(dict(params,issuers='false',maresi_subjects='false',latest_edits_only='true',opinionated='true'))))
        if not isinstance(value,dict) or not isinstance(value.get('reviews'),list):raise CollectionError('Malformed API response')
        return value['reviews']
    def discover(self,query,limit=5):
        if not 1<=len(query.strip())<=200 or not 1<=limit<=5:raise CollectionError('Invalid discovery request')
        candidates=self.page(dict(q=query.strip(),limit=20,offset=0));found=[];seen=set()
        for r in candidates:
            subject=(r.get('payload') or {}).get('sub')
            if subject not in SOFTWARE or subject in seen:continue
            name,category=SOFTWARE[subject]
            try:normalized(r,subject,name)
            except (AccessDenied,CollectionError,ValueError,OverflowError):continue
            seen.add(subject);found.append(dict(name=name,url=subject,category=category))
            if len(found)>=limit:break
        return found
    def collect(self,subject,expected_name,max_reviews=20,max_pages=5):
        if subject not in SOFTWARE or SOFTWARE[subject][0]!=expected_name:raise AccessDenied('Unreviewed software subject')
        if not 1<=max_reviews<=20 or not 1<=max_pages<=5:raise CollectionError('Invalid collection limits')
        records=[];seen=set();offset=0;pages=0;skipped=0;full=False
        for _ in range(max_pages):
            page=self.page(dict(sub=subject,limit=20,offset=offset));pages+=1;offset+=len(page);full=len(page)==20
            for r in page:
                try:row=normalized(r,subject,expected_name)
                except (AccessDenied,CollectionError,ValueError,OverflowError):skipped+=1;continue
                if row['external_id'] in seen:continue
                seen.add(row['external_id']);records.append(row)
                if len(records)>=max_reviews:break
            if len(records)>=max_reviews or not full:break
        return dict(records=records,pages=pages,truncated=full or len(records)>=max_reviews,skipped=skipped,terms_hash=self.terms_hash)
