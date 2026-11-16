"""Bounded, robots-aware JSON-LD review extraction for authorized crawl sources."""
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from html.parser import HTMLParser
from urllib.robotparser import RobotFileParser

from .connectors import AccessDenied, CollectionError, RateLimited, SourceUnavailable, canonical_url
from .licensing import LICENSES, validate_license

USER_AGENT = 'VeriflowReviewCollector/1.0'
MAX_PAGE_BYTES = 2_000_000
MAX_ROBOTS_BYTES = 256_000
MAX_REVIEWS_PER_PAGE = 100


class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, host):
        self.host = host

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = canonical_url(newurl)
        if urllib.parse.urlsplit(url).hostname != self.host:
            raise AccessDenied('Cross-source redirect denied')
        return super().redirect_request(req, fp, code, msg, headers, url)


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.scripts = []
        self.next_href = None
        self._in_jsonld = False
        self._chunks = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag.lower() == 'script' and 'ld+json' in attrs.get('type', '').lower():
            self._in_jsonld = True
            self._chunks = []
        if tag.lower() == 'link' and 'next' in attrs.get('rel', '').lower().split():
            self.next_href = attrs.get('href')

    def handle_data(self, data):
        if self._in_jsonld:
            self._chunks.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == 'script' and self._in_jsonld:
            self.scripts.append(''.join(self._chunks))
            self._in_jsonld = False
            self._chunks = []


def _read_url(url, source_host, max_bytes, allow_not_found=False):
    opener = urllib.request.build_opener(_SameHostRedirect(source_host))
    request = urllib.request.Request(
        url, headers={'User-Agent': USER_AGENT, 'Accept': 'text/html,application/xhtml+xml'}
    )
    try:
        with opener.open(request, timeout=10) as response:
            final_url = canonical_url(response.geturl())
            if urllib.parse.urlsplit(final_url).hostname != source_host:
                raise AccessDenied('Cross-source redirect denied')
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise CollectionError('Source response exceeds the size limit')
            return response.status, response.headers, final_url, body
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and allow_not_found:
            return 404, exc.headers, url, b''
        if exc.code == 429:
            try:
                delay = int(exc.headers.get('Retry-After', '60'))
            except (TypeError, ValueError):
                delay = 60
            raise RateLimited(delay) from None
        if exc.code == 408 or 500 <= exc.code <= 599:
            raise SourceUnavailable('Source temporarily unavailable') from None
        raise CollectionError('Source request failed') from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise SourceUnavailable('Source temporarily unavailable') from None


def _robots_allowed(url, host):
    robots_url = f'https://{host}/robots.txt'
    try:
        status, _, _, body = _read_url(robots_url, host, MAX_ROBOTS_BYTES, allow_not_found=True)
    except SourceUnavailable:
        raise
    except CollectionError:
        raise AccessDenied('Unable to verify source robots policy') from None
    if status == 404:
        return True
    parser = RobotFileParser(robots_url)
    parser.parse(body.decode('utf-8', 'replace').splitlines())
    return parser.can_fetch(USER_AGENT, url)


def _review_nodes(value):
    if isinstance(value, list):
        for child in value:
            yield from _review_nodes(child)
    elif isinstance(value, dict):
        kind = value.get('@type', [])
        kinds = [kind] if isinstance(kind, str) else kind
        if isinstance(kinds, list) and any(
            str(k).lower().split('/')[-1].split('#')[-1] == 'review' for k in kinds
        ):
            yield value
        for key, child in value.items():
            if key not in ('author', 'reviewAuthor'):
                yield from _review_nodes(child)


def _as_text(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def _published_date(value):
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.replace('Z', '+00:00').split('T', 1)[0]).isoformat()
    except ValueError:
        return None


def _same_source_url(value, host, fallback):
    if not isinstance(value, str):
        return fallback
    try:
        url = canonical_url(urllib.parse.urljoin(fallback, value))
    except (ValueError, CollectionError):
        return fallback
    return url if urllib.parse.urlsplit(url).hostname == host else fallback


def _author_fields(review, host):
    author = review.get('author')
    if isinstance(author, dict):
        name = _as_text(author.get('name'))
        profile = author.get('url') or author.get('@id')
    else:
        name = _as_text(author)
        profile = None
    if not name or not isinstance(profile, str):
        raise AccessDenied('Required public attribution is missing')
    try:
        profile = canonical_url(urllib.parse.urljoin('https://' + host, profile))
    except (ValueError, CollectionError):
        raise AccessDenied('Required public attribution is invalid') from None
    if urllib.parse.urlsplit(profile).hostname != host:
        raise AccessDenied('Required public attribution is outside the source')
    return name, profile


def _rating(review):
    rating = review.get('reviewRating')
    if not isinstance(rating, dict):
        return None, None
    try:
        value = float(rating.get('ratingValue'))
        scale = float(rating.get('bestRating') or rating.get('ratingScale'))
    except (TypeError, ValueError):
        return None, None
    if not 0 <= value <= scale or not 0 < scale <= 100:
        return None, None
    return value, scale


def extract_page(source, grant, product_mapping, cursor_url=None):
    """Fetch one page only; caller persists the returned next_url before continuing."""
    method = source.get('collection_method')
    grant_method = grant.get('method')
    if method != 'permitted_crawl' or grant_method != 'permitted_crawl':
        raise AccessDenied()
    source_host = urllib.parse.urlsplit(source['url']).hostname
    start_url = product_mapping.get('external_key')
    url = canonical_url(cursor_url or start_url)
    if urllib.parse.urlsplit(url).hostname != source_host:
        raise AccessDenied('Product page is outside the approved source')
    if not _robots_allowed(url, source_host):
        raise AccessDenied('Source robots policy disallows this page')
    status, headers, final_url, body = _read_url(url, source_host, MAX_PAGE_BYTES)
    content_type = headers.get('Content-Type', '').lower()
    if status != 200 or ('html' not in content_type and 'xhtml' not in content_type):
        raise CollectionError('Expected a source HTML page')
    parser = _PageParser()
    parser.feed(body.decode('utf-8', 'replace'))
    documents = []
    for script in parser.scripts:
        try:
            documents.append(json.loads(script))
        except (ValueError, TypeError):
            continue
    next_url = None
    if parser.next_href:
        candidate = canonical_url(urllib.parse.urljoin(final_url, parser.next_href))
        if urllib.parse.urlsplit(candidate).hostname == source_host and candidate != final_url:
            next_url = candidate

    rows = []
    seen = set()
    needs_license = bool(source.get('required_license_id'))
    for document in documents:
        for review in _review_nodes(document):
            published = _published_date(review.get('datePublished'))
            if not published:
                continue
            page_url = _same_source_url(review.get('url') or review.get('@id'), source_host, final_url)
            text = _as_text(review.get('reviewBody'))
            rating, scale = _rating(review)
            external = review.get('identifier') or review.get('@id') or review.get('url')
            if isinstance(external, dict):
                external = external.get('value') or external.get('@id')
            if not isinstance(external, (str, int)) or isinstance(external, bool) or not str(external).strip():
                basis = json.dumps([product_mapping['external_key'], page_url, published, text], ensure_ascii=False)
                external = hashlib.sha256(basis.encode()).hexdigest()
            external = str(external).strip()
            if external in seen:
                continue
            seen.add(external)
            license_metadata = None
            if needs_license:
                public_credit, attribution_url = _author_fields(review, source_host)
                license_id = source['required_license_id']
                license_metadata = validate_license({
                    'license_id': license_id,
                    'license_url': LICENSES.get(license_id),
                    'source_terms_url': grant.get('terms_url'),
                    'public_credit': public_credit,
                    'attribution_url': attribution_url,
                    'text_modified': False,
                    'change_note': None,
                }, source, grant)
            rows.append({
                'external_id': external,
                'product_key': product_mapping['external_key'],
                'software_name': product_mapping['expected_name'],
                'published_at': published,
                'original_url': page_url,
                'review_text': text if source.get('full_text_allowed') and grant.get('full_text_allowed') else None,
                'rating': rating,
                'rating_scale': scale,
                'license_metadata': license_metadata,
            })
            if len(rows) >= MAX_REVIEWS_PER_PAGE:
                break
        if len(rows) >= MAX_REVIEWS_PER_PAGE:
            break
    return {'records': rows, 'next_url': next_url, 'page_url': final_url}
