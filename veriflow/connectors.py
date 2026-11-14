"""Collectors emit normalized records. API/crawl adapters require separate approval."""
import csv
import hashlib
import io
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit


class CollectionError(Exception):
    code = 'invalid_import'


class AccessDenied(CollectionError):
    code = 'access_denied'


class Unsupported(CollectionError):
    code = 'connector_unavailable'


class RateLimited(CollectionError):
    code = 'rate_limited'

    def __init__(self, retry_after=60):
        self.retry_after = max(60, min(int(retry_after), 86400))


@dataclass(frozen=True)
class Review:
    external_id: str
    product_key: str
    software_name: str
    text: str | None
    rating: float | None
    rating_scale: float | None
    published_at: str
    original_url: str
    fingerprint: str


class Connector(Protocol):
    def collect(self, payload: str, format: str, source: dict, grant: dict) -> list[Review]: ...


def canonical_url(value):
    parts = urlsplit(value)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise CollectionError('HTTPS source URL required')
    if parts.port not in (None, 443):
        raise CollectionError('Unexpected URL port')
    # Preserve query parameters: some platforms use them as review identifiers.
    return urlunsplit(('https', parts.netloc.lower(), parts.path or '/', parts.query, ''))


def normalize(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', value)).strip().casefold()


class ApprovedImportConnector:
    """Only whitelisted fields survive; author names, emails, avatars are discarded."""
    method = 'approved_import'

    def collect(self, payload, format, source, grant):
        if source['collection_method'] != self.method or grant['method'] != self.method:
            raise AccessDenied()
        if format == 'json':
            rows = json.loads(payload)
        elif format == 'csv':
            rows = list(csv.DictReader(io.StringIO(payload)))
        else:
            raise CollectionError('Unsupported format')
        if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
            raise CollectionError('Expected 1–1000 records')
        records = []
        source_host = urlsplit(source['url']).hostname
        for r in rows:
            if not isinstance(r, dict):
                raise CollectionError('Expected object')
            required = ('external_id', 'product_key', 'software_name', 'published_at', 'original_url')
            if any(not isinstance(r.get(k), str) or not r[k].strip() or len(r[k]) > 2048 for k in required):
                raise CollectionError('Missing or oversized required field')
            url = canonical_url(r['original_url'])
            host = urlsplit(url).hostname
            if host != source_host and not host.endswith('.' + source_host):
                raise CollectionError('URL does not belong to source')
            published = date.fromisoformat(r['published_at']).isoformat()
            if published > date.today().isoformat():
                raise CollectionError('Future publication date')
            text = r.get('review_text') or None
            if text is not None and (not isinstance(text, str) or len(text) > 100000):
                raise CollectionError('Invalid review text')
            if text and not (source['full_text_allowed'] and grant['full_text_allowed']):
                raise AccessDenied('Full text is not authorized')
            raw_rating = r.get('rating')
            rating = None if raw_rating in (None, '') else float(raw_rating)
            raw_scale = r.get('rating_scale')
            scale = None if raw_scale in (None, '') else float(raw_scale)
            if rating is not None and (scale is None or not 0 <= rating <= scale or not 0 < scale <= 100):
                raise CollectionError('Rating requires a valid original scale')
            if rating is None and scale is not None:
                raise CollectionError('Scale requires rating')
            product = r['product_key'].strip()
            # Content matches remain scoped to a source/product; cross-source matches
            # become candidate groups in the DB without deleting source attribution.
            material = [product, normalize(text), published] if text else [product, url, r['external_id'].strip()]
            fingerprint = hashlib.sha256(json.dumps(material).encode()).hexdigest()
            records.append(Review(r['external_id'].strip(), product, r['software_name'].strip(),
                                  text, rating, scale, published, url, fingerprint))
        return records


class ApifyDatasetConnector(ApprovedImportConnector):
    method = 'apify'


class ConnectorRegistry:
    def __init__(self):
        self._connectors = {'approved_import': ApprovedImportConnector(), 'apify': ApifyDatasetConnector()}

    def register(self, method, connector):
        if method not in {'authorized_api', 'permitted_crawl', 'composio'}:
            raise ValueError('Unsupported extension method')
        self._connectors[method] = connector

    def get(self, method):
        if method not in self._connectors:
            raise Unsupported()
        return self._connectors[method]
