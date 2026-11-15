"""One explicit page per call; no database, queue, scheduler or product selection.

Derived from ff62e18's Mangrove normalization/API contract. The existing worker
owns authorization, software identity, breadth selection, quotas and persistence.
Only Python's standard library is required. Disabled by default.
"""
import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

SOURCE_ID = 'mangrove-reviews'
TERMS_URL = 'https://mangrove.reviews/terms'
API_URL = 'https://api.mangrove.reviews/reviews'


class ConnectorError(Exception):
    """Safe error code only; never include response bodies or raw exceptions."""
    def __init__(self, code, retry_after_seconds=None):
        super().__init__(code)
        self.code = code
        self.retry_after_seconds = retry_after_seconds


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def terms_digest(html):
    """Same visible-text digest as ff62e18; no network access."""
    parser = _VisibleText()
    parser.feed(html)
    text = ' '.join(parser.parts)
    return hashlib.sha256(text.encode()).hexdigest(), text


@dataclass(frozen=True)
class SoftwareProduct:
    """An existing worker-verified software mapping, never a discovery claim."""
    subject: str
    name: str

    def __post_init__(self):
        try:
            parsed = urlsplit(self.subject)
            valid = (parsed.scheme == 'https' and parsed.hostname and
                     not parsed.username and not parsed.password and
                     not parsed.fragment and parsed.port in (None, 443))
        except (TypeError, ValueError):
            valid = False
        if not valid or not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 200:
            raise ConnectorError('invalid_software_mapping')


def normalize_review(entry, product):
    """Allowlisted content/provenance only; no JWTs, keys, aliases or images."""
    if not isinstance(entry, dict) or not isinstance(entry.get('payload'), dict):
        raise ConnectorError('malformed_review')
    payload = entry['payload']
    signature = entry.get('signature')
    if not isinstance(signature, str) or not re.fullmatch(r'[A-Za-z0-9_-]{40,200}', signature):
        raise ConnectorError('invalid_native_id')
    metadata = payload.get('metadata')
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ConnectorError('invalid_license_metadata')
    explicit = [obj['license'] for obj in (metadata, payload) if 'license' in obj]
    if any(value != 'CC-BY-4.0' for value in explicit):
        raise ConnectorError('unsupported_license')
    # Default CC-BY-4.0 is permitted only after reviewed source terms pass.
    if payload.get('sub') != product.subject or payload.get('action'):
        raise ConnectorError('wrong_subject_or_action')
    text, rating, published = payload.get('opinion'), payload.get('rating'), payload.get('iat')
    if not isinstance(text, str) or not text.strip() or len(text) > 100000:
        raise ConnectorError('invalid_review_text')
    if isinstance(rating, bool) or not isinstance(rating, (float, int)) or not 0 <= rating <= 100 or not math.isfinite(rating):
        raise ConnectorError('invalid_native_rating')
    if isinstance(published, bool) or not isinstance(published, int) or published < 0:
        raise ConnectorError('invalid_publication_date')
    try:
        date = datetime.fromtimestamp(published, timezone.utc).date().isoformat()
    except (ValueError, OverflowError, OSError):
        raise ConnectorError('invalid_publication_date') from None
    original = 'https://api.mangrove.reviews/review/' + signature
    return dict(external_id=signature, product_key=product.subject,
                software_name=product.name, review_text=text, rating=rating,
                rating_scale=100, published_at=date, original_url=original,
                license_metadata=dict(license_id='CC-BY-4.0',
                    license_url='https://creativecommons.org/licenses/by/4.0/',
                    source_terms_url=TERMS_URL, public_credit='Original review on Mangrove',
                    attribution_url=original, text_modified=False, change_note=None))


class MangrovePageConnector:
    def __init__(self, *, reviewed_terms_sha256, enabled=False, max_requests=8,
                 transport=None, wait=time.sleep, clock=time.monotonic):
        if not isinstance(reviewed_terms_sha256, str) or not re.fullmatch(r'[a-f0-9]{64}', reviewed_terms_sha256):
            raise ConnectorError('reviewed_terms_digest_required')
        if type(max_requests) is not int or not 2 <= max_requests <= 30:
            raise ConnectorError('invalid_request_budget')
        self.enabled = enabled is True
        self.reviewed_terms_sha256 = reviewed_terms_sha256
        self.max_requests = max_requests
        self.transport = transport or build_opener(_NoRedirect()).open
        self.wait, self.clock = wait, clock
        self.requests = 0
        self.last_request = None

    def _check(self, authorize, product):
        if not self.enabled:
            raise ConnectorError('connector_disabled')
        if not callable(authorize):
            raise ConnectorError('worker_authorization_required')
        try:
            allowed = authorize(SOURCE_ID, product)
        except Exception:
            raise ConnectorError('worker_authorization_unavailable') from None
        if allowed is not True:
            raise ConnectorError('worker_authorization_required')

    def _read(self, url):
        # Call sites construct only these two endpoints; no externally supplied URL.
        if url != TERMS_URL and not url.startswith(API_URL + '?'):
            raise ConnectorError('invalid_source_endpoint')
        if self.requests >= self.max_requests:
            raise ConnectorError('request_budget_exhausted')
        if self.last_request is not None:
            self.wait(max(0, 2 - (self.clock() - self.last_request)))
        self.last_request = self.clock()
        self.requests += 1
        request = Request(url, headers={
            'User-Agent': 'Veriflow/0.1 (bounded permitted research)',
            'Accept': 'text/html' if url == TERMS_URL else 'application/json'})
        try:
            with self.transport(request, timeout=20) as response:
                raw = response.read(1000001)
                if len(raw) > 1000000:
                    raise ConnectorError('source_response_too_large')
                return raw.decode('utf-8')
        except HTTPError as error:
            if error.code == 429:
                retry = error.headers.get('Retry-After', '60')
                try:
                    delay = int(retry)
                except (ValueError, TypeError):
                    try:
                        delay = int((parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds())
                    except (ValueError, TypeError, OverflowError):
                        delay = 60
                raise ConnectorError('source_rate_limited', max(1, min(delay, 86400))) from None
            code = 'source_access_denied' if error.code in (301, 302, 303, 307, 308, 401, 403) else 'source_unavailable'
            raise ConnectorError(code) from None
        except (URLError, TimeoutError, OSError, UnicodeDecodeError):
            raise ConnectorError('source_unavailable') from None

    def fetch_page(self, product, *, authorize, offset=0, page_size=1):
        """One source page; worker decides whether/when to visit another product.

        Default one candidate per product supports Breadth First. Cursor and
        returned rows are persisted only by the existing worker, never here.
        """
        if not isinstance(product, SoftwareProduct):
            raise ConnectorError('invalid_software_mapping')
        if type(offset) is not int or not 0 <= offset <= 1000000 or type(page_size) is not int or not 1 <= page_size <= 20:
            raise ConnectorError('invalid_page_limits')
        self._check(authorize, product)
        before = self.requests
        digest, text = terms_digest(self._read(TERMS_URL))
        witnesses = ('commercially', 'When no license is specified, CC-BY-4.0 applies.', 'hyperlink', 'license')
        if digest != self.reviewed_terms_sha256 or not all(w in text for w in witnesses):
            raise ConnectorError('source_terms_need_review')
        self._check(authorize, product)
        url = API_URL + '?' + urlencode(dict(sub=product.subject, limit=page_size,
            offset=offset, issuers='false', maresi_subjects='false',
            latest_edits_only='true', opinionated='true'))
        try:
            data = json.loads(self._read(url))
        except (ValueError, RecursionError):
            raise ConnectorError('invalid_source_json') from None
        if not isinstance(data, dict) or not isinstance(data.get('reviews'), list) or len(data['reviews']) > page_size:
            raise ConnectorError('invalid_source_page')
        records, seen, skipped = [], set(), {}
        for entry in data['reviews']:
            try:
                record = normalize_review(entry, product)
            except ConnectorError as error:
                skipped[error.code] = skipped.get(error.code, 0) + 1
                continue
            if record['external_id'] in seen:
                skipped['duplicate_native_id'] = skipped.get('duplicate_native_id', 0) + 1
                continue
            seen.add(record['external_id'])
            records.append(record)
        self._check(authorize, product)
        count = len(data['reviews'])
        return dict(source_id=SOURCE_ID, product_key=product.subject, records=records,
                    candidates_received=count, skipped=skipped,
                    next_offset=offset + count if count == page_size else None,
                    more_possible=count == page_size, terms_hash=digest,
                    requests_used=self.requests - before, requests_total=self.requests)
