"""Reused, bounded Mangrove API client and native review normalizer.

Mangrove is not enabled by this module. The existing source authorization,
product mapping, worker limits, and record-level license checks remain required.
"""
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, build_opener

from .connectors import AccessDenied, ApprovedImportConnector, CollectionError, RateLimited
from .libreviews_live import NoRedirect, SourceUnavailable

SOURCE_ID = 'mangrove-reviews'
BASE = 'https://mangrove.reviews'
API = 'https://api.mangrove.reviews'
SOFTWARE = {
    'https://bitwarden.com': ('Bitwarden', 'Password managers'),
    'https://github.com': ('GitHub', 'Developer platforms'),
    'https://codeberg.org': ('Codeberg', 'Developer platforms'),
    'https://keybase.io': ('Keybase', 'Communication'),
    'https://mangrove.reviews': ('Mangrove', 'Review platforms'),
}

# Safe defaults only. An administrator must separately approve the source,
# full-text retention, a product mapping, and a non-expired authorization.
SOURCE_DEFINITION = {
    'id': SOURCE_ID,
    'name': 'Mangrove Reviews (CC BY 4.0 collection)',
    'url': BASE,
    'category': 'review_aggregation',
    'collection_method': 'authorized_api',
    'access_status': 'pending_authorization',
    'enabled': False,
    'full_text_allowed': False,
    'required_license_id': 'CC-BY-4.0',
    'attribution_required': True,
    'minimum_interval_seconds': 3,
    'schedule_seconds': 86400,
    'policy_notes': (
        'Documented public API only. Retain only native CC-BY-4.0 records '
        'with source attribution; reject incompatible per-review licenses. '
        'Fixed audited software subjects; no issuer keys, JWTs, images, or '
        'private identity fields.'
    ),
}


class VisibleText(HTMLParser):
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


def normalized(entry, subject, name):
    payload = entry.get('payload')
    signature = entry.get('signature')
    if not isinstance(payload, dict) or not isinstance(signature, str) \
            or not re.fullmatch(r'[A-Za-z0-9_-]{40,200}', signature):
        raise CollectionError('Malformed native review')
    metadata = payload.get('metadata') or {}
    if not isinstance(metadata, dict):
        raise CollectionError('Invalid license metadata')
    license_id = metadata.get('license', payload.get('license', 'CC-BY-4.0'))
    if license_id != 'CC-BY-4.0':
        raise AccessDenied('This connector accepts only native CC-BY-4.0 reviews')
    if payload.get('sub') != subject or payload.get('action'):
        raise AccessDenied('Wrong software subject or action record')
    opinion = payload.get('opinion')
    rating = payload.get('rating')
    published = payload.get('iat')
    if not isinstance(opinion, str) or not opinion.strip() or len(opinion) > 100000:
        raise CollectionError('Opinion text required')
    if isinstance(rating, bool) or not isinstance(rating, (int, float)) or not 0 <= rating <= 100:
        raise CollectionError('Invalid original rating')
    if isinstance(published, bool) or not isinstance(published, int) or published < 0:
        raise CollectionError('Invalid source publication time')
    original_url = API + '/review/' + quote(signature, safe='')
    return {
        'external_id': signature,
        'product_key': subject,
        'software_name': name,
        'review_text': opinion,
        'rating': rating,
        'rating_scale': 100,
        'published_at': datetime.fromtimestamp(published, timezone.utc).date().isoformat(),
        'original_url': original_url,
        'license_metadata': {
            'license_id': 'CC-BY-4.0',
            'license_url': 'https://creativecommons.org/licenses/by/4.0/',
            'source_terms_url': BASE + '/terms',
            'public_credit': 'Original review on Mangrove',
            'attribution_url': original_url,
            'text_modified': False,
            'change_note': None,
        },
    }


class MangroveClient:
    """Bounded fixed-endpoint API client from the reviewed upstream connector."""
    def __init__(self, transport=None, wait=time.sleep, clock=time.monotonic):
        self.transport = transport or build_opener(NoRedirect()).open
        self.wait = wait
        self.clock = clock
        self.last = None
        self.requests = 0
        self.terms_hash = None

    def read(self, url):
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port is not None:
            raise AccessDenied()
        allowed = (
            parsed.netloc == 'mangrove.reviews' and parsed.path == '/terms' and not parsed.query
        ) or (
            parsed.netloc == 'api.mangrove.reviews' and parsed.path == '/reviews'
        )
        if not allowed:
            raise AccessDenied('Fixed source endpoints only')
        if self.last is not None:
            self.wait(max(0, 2 - (self.clock() - self.last)))
        self.last = self.clock()
        self.requests += 1
        if self.requests > 30:
            raise CollectionError('API request limit')
        try:
            with self.transport(Request(url, headers={
                'User-Agent': 'Veriflow/0.1 (bounded permitted research)',
                'Accept': 'application/json' if parsed.netloc == 'api.mangrove.reviews' else 'text/html',
            }), timeout=20) as response:
                raw = response.read(1_000_001)
                if len(raw) > 1_000_000:
                    raise CollectionError('Source response too large')
                return raw.decode('utf-8')
        except HTTPError as exc:
            if exc.code == 429:
                retry = exc.headers.get('Retry-After', '60')
                try:
                    seconds = int(retry)
                except (ValueError, TypeError):
                    try:
                        seconds = int((parsedate_to_datetime(retry) -
                                       datetime.now(timezone.utc)).total_seconds())
                    except (ValueError, TypeError):
                        seconds = 60
                raise RateLimited(seconds) from None
            if exc.code in (301, 302, 303, 307, 308, 401, 403):
                raise AccessDenied('Source refused or redirected access') from None
            raise SourceUnavailable() from None
        except (URLError, TimeoutError, OSError, UnicodeDecodeError):
            raise SourceUnavailable() from None

    def verify_policy(self):
        if self.terms_hash:
            return self.terms_hash
        raw = self.read(BASE + '/terms')
        parser = VisibleText()
        parser.feed(raw)
        text = ' '.join(parser.parts)
        required = (
            'commercially',
            'When no license is specified, CC-BY-4.0 applies.',
            'hyperlink',
            'license',
        )
        if not all(term.casefold() in text.casefold() for term in required):
            raise AccessDenied('Source terms need review')
        self.terms_hash = hashlib.sha256(text.encode()).hexdigest()
        return self.terms_hash

    def page(self, params):
        self.verify_policy()
        query = dict(params, issuers='false', maresi_subjects='false',
                     latest_edits_only='true', opinionated='true')
        result = json.loads(self.read(API + '/reviews?' + urlencode(query)))
        if not isinstance(result, dict) or not isinstance(result.get('reviews'), list):
            raise CollectionError('Malformed API response')
        return result['reviews']

    def discover(self, query, limit=5):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 200 \
                or isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 5:
            raise CollectionError('Invalid discovery request')
        candidates = self.page(dict(q=query.strip(), limit=20, offset=0))
        found = []
        seen = set()
        for entry in candidates:
            subject = (entry.get('payload') or {}).get('sub') if isinstance(entry, dict) else None
            if subject not in SOFTWARE or subject in seen:
                continue
            name, category = SOFTWARE[subject]
            try:
                normalized(entry, subject, name)
            except (AccessDenied, CollectionError, ValueError, OverflowError, OSError):
                continue
            seen.add(subject)
            found.append({'name': name, 'url': subject, 'category': category})
            if len(found) >= limit:
                break
        return found


class MangroveAPIConnector(ApprovedImportConnector):
    """Native Mangrove pages flow through normal ingestion and deduplication."""
    method = 'authorized_api'

    def __init__(self, client_factory=MangroveClient):
        self.client_factory = client_factory

    def discover_products(self, query, limit=5):
        return self.client_factory().discover(query, limit)

    def fetch_page(self, source, grant, mapping, cursor=None):
        if (source.get('id') != SOURCE_ID or source.get('url') != BASE
                or source.get('collection_method') != self.method
                or source.get('required_license_id') != 'CC-BY-4.0'
                or not source.get('enabled') or source.get('access_status') != 'approved'
                or not source.get('full_text_allowed') or not source.get('attribution_required')
                or grant.get('method') != self.method or grant.get('license_id') != 'CC-BY-4.0'
                or not grant.get('full_text_allowed') or grant.get('terms_url') != BASE + '/terms'):
            raise AccessDenied('Mangrove source and full-text authorization are required')
        subject = mapping.get('external_key')
        expected = mapping.get('expected_name')
        if subject not in SOFTWARE or SOFTWARE[subject][0] != expected:
            raise AccessDenied('Unreviewed Mangrove product mapping')
        offset = 0
        if cursor:
            match = re.fullmatch(r'mangrove-offset:(20|40|60|80)', cursor)
            if not match:
                raise CollectionError('Invalid Mangrove pagination cursor')
            offset = int(match.group(1))
        client = self.client_factory()
        client.verify_policy()
        entries = client.page(dict(sub=subject, limit=20, offset=offset))
        records = []
        for entry in entries:
            try:
                records.append(normalized(entry, subject, expected))
            except (AccessDenied, CollectionError, ValueError, OverflowError, OSError):
                continue
        next_offset = offset + len(entries)
        next_cursor = f'mangrove-offset:{next_offset}' if len(entries) == 20 and next_offset < 100 else None
        return {'records': records, 'next_url': next_cursor}
