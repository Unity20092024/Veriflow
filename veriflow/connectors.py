"""Collectors emit normalized records. API/crawl adapters require separate approval."""
import csv
import hashlib
import io
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class CollectionError(Exception):
    code = 'invalid_import'


class AccessDenied(CollectionError):
    code = 'access_denied'


class Unsupported(CollectionError):
    code = 'connector_unavailable'


class SourceUnavailable(CollectionError):
    code = 'source_unavailable'


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
    license_metadata: dict | None = None


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
            from .licensing import validate_license
            license_metadata=validate_license(r.get('license_metadata'),source,grant)
            records.append(Review(r['external_id'].strip(), product, r['software_name'].strip(),
                                  text, rating, scale, published, url, fingerprint,license_metadata))
        return records


class ApifyDatasetConnector(ApprovedImportConnector):
    method = 'apify'

    def collect(self,*args,**kwargs):
        records=super().collect(*args,**kwargs)
        from .pilot import max_records
        if len(records)>max_records():
            raise CollectionError('First-test review record ceiling exceeded')
        return records


class PermittedCrawlConnector(ApprovedImportConnector):
    """Validates records extracted by the bounded, robots-aware crawler."""
    method = 'permitted_crawl'


def _request_api_json(url, token):
    """Fetch a bounded official API response without exposing credentials or bodies."""
    request = Request(url, headers={
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json',
        'User-Agent': 'Veriflow authorized API collector',
    })
    try:
        class NoRedirectHandler(HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, message, headers, new_url):
                return None

        with build_opener(NoRedirectHandler).open(request, timeout=15) as response:
            if response.status != 200:
                raise SourceUnavailable()
            payload = response.read(5_000_001)
    except HTTPError as exc:
        if exc.code == 429:
            try:
                delay = int(exc.headers.get('Retry-After', '60'))
            except (TypeError, ValueError):
                delay = 60
            raise RateLimited(delay) from None
        if exc.code in (401, 403):
            raise AccessDenied('Provider rejected API authorization') from None
        if exc.code >= 500:
            raise SourceUnavailable() from None
        raise CollectionError('Provider rejected the API request') from None
    except (TimeoutError, URLError, OSError):
        raise SourceUnavailable() from None
    if len(payload) > 5_000_000:
        raise CollectionError('Provider response exceeds 5MB')
    try:
        result = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        raise CollectionError('Provider returned invalid JSON') from None
    if not isinstance(result, dict):
        raise CollectionError('Provider returned an invalid response')
    return result


def _api_token(name):
    token = os.environ.get(name, '')
    if not token or len(token) > 8192 or '\r' in token or '\n' in token:
        error = CollectionError('Authorized API credential is missing or invalid')
        error.code = 'api_credentials_missing'
        raise error
    return token


class AuthorizedApiConnector(ApprovedImportConnector):
    """Shared normalized-record validation for source-specific official APIs."""
    method = 'authorized_api'
    source_id = None
    credential_name = None

    def __init__(self, request_json=None):
        self.request_json = request_json or _request_api_json

    def _authorize(self, source, grant):
        if (source.get('id') != self.source_id
                or source.get('collection_method') != self.method
                or grant.get('method') != self.method):
            raise AccessDenied()
        return _api_token(self.credential_name)

    def collect(self, *args, **kwargs):
        return super().collect(*args, **kwargs)

    @staticmethod
    def _is_full_text_allowed(source, grant):
        return bool(source.get('full_text_allowed') and grant.get('full_text_allowed'))

    @staticmethod
    def _standard_record(external_id, mapping, published_at, original_url,
                         text=None, rating=None, rating_scale=None):
        return {
            'external_id': str(external_id),
            'product_key': mapping['external_key'],
            'software_name': mapping['expected_name'],
            'review_text': text,
            'rating': rating,
            'rating_scale': rating_scale,
            'published_at': published_at,
            'original_url': original_url,
        }


class GooglePlayReviewsConnector(AuthorizedApiConnector):
    """Google Play reviews for apps owned by the authorized Android Publisher account."""
    source_id = 'google-play'
    credential_name = 'GOOGLE_PLAY_ACCESS_TOKEN'
    endpoint = 'https://androidpublisher.googleapis.com/androidpublisher/v3/applications'

    @staticmethod
    def _package_name(mapping):
        key = str(mapping.get('external_key', '')).strip()
        try:
            parsed = urlsplit(key)
            port = parsed.port
        except ValueError:
            raise CollectionError('Invalid Google Play product mapping') from None
        if parsed.scheme:
            if (parsed.scheme != 'https' or parsed.hostname != 'play.google.com'
                    or parsed.username or parsed.password or port not in (None, 443)):
                raise CollectionError('Invalid Google Play product mapping')
            key = parse_qs(parsed.query).get('id', [''])[0]
        if not re.fullmatch(r'[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+', key):
            raise CollectionError('Invalid Google Play package identifier')
        return key

    def fetch_page(self, source, grant, mapping, cursor=None):
        token = self._authorize(source, grant)
        package = self._package_name(mapping)
        url = f'{self.endpoint}/{quote(package, safe="")}/reviews?{urlencode({"maxResults": 100})}'
        if cursor:
            if not cursor.startswith('pageToken:') or len(cursor) > 4096:
                raise CollectionError('Invalid Google Play pagination cursor')
            page_token = cursor.removeprefix('pageToken:')
            if not page_token or len(page_token) > 2048:
                raise CollectionError('Invalid Google Play pagination cursor')
            url += '&' + urlencode({'token': page_token})
        response = self.request_json(url, token)
        review_items = response.get('reviews', [])
        if not isinstance(review_items, list):
            raise CollectionError('Invalid Google Play review response')
        listing = 'https://play.google.com/store/apps/details?' + urlencode({'id': package})
        rows, seen = [], set()
        for item in review_items:
            if not isinstance(item, dict):
                continue
            external_id = item.get('reviewId')
            comments = item.get('comments')
            comment = comments[0].get('userComment') if isinstance(comments, list) and comments and isinstance(comments[0], dict) else None
            modified = comment.get('lastModified') if isinstance(comment, dict) else None
            try:
                published = datetime.fromtimestamp(
                    int(modified['seconds']), timezone.utc
                ).date().isoformat()
            except (TypeError, ValueError, KeyError, OverflowError, OSError):
                continue
            if not isinstance(external_id, (str, int)) or str(external_id) in seen:
                continue
            seen.add(str(external_id))
            original_url = listing + '&' + urlencode({'reviewId': str(external_id)})
            text = None
            if isinstance(comment, dict) and self._is_full_text_allowed(source, grant):
                text = comment.get('originalText') or comment.get('text')
                if not isinstance(text, str):
                    text = None
            rating = comment.get('starRating') if isinstance(comment, dict) else None
            try:
                rating = float(rating) if rating is not None else None
            except (TypeError, ValueError):
                rating = None
            rows.append(self._standard_record(
                external_id, mapping, published, original_url, text, rating,
                5 if rating is not None else None,
            ))
        pagination = response.get('tokenPagination') or {}
        if not isinstance(pagination, dict):
            raise CollectionError('Invalid Google Play pagination response')
        next_token = pagination.get('nextPageToken')
        next_cursor = None
        if next_token:
            if not isinstance(next_token, str) or len(next_token) > 2048:
                raise CollectionError('Invalid Google Play pagination token')
            next_cursor = 'pageToken:' + next_token
            if next_cursor == cursor:
                raise CollectionError('Repeated Google Play pagination token')
        return rows, next_cursor


class AppleAppStoreReviewsConnector(AuthorizedApiConnector):
    """App Store Connect reviews for apps the authorized account can access."""
    source_id = 'apple-app-store'
    credential_name = 'APP_STORE_CONNECT_TOKEN'
    endpoint = 'https://api.appstoreconnect.apple.com/v1/apps'

    @staticmethod
    def _app_id(mapping):
        key = str(mapping.get('external_key', '')).strip()
        if key.isdigit():
            return key
        try:
            parsed = urlsplit(key)
            port = parsed.port
        except ValueError:
            raise CollectionError('Invalid App Store product mapping') from None
        if parsed.scheme and (
                parsed.scheme != 'https' or parsed.hostname != 'apps.apple.com'
                or parsed.username or parsed.password or port not in (None, 443)):
            raise CollectionError('Invalid App Store product mapping')
        match = re.search(r'(?:^|/)id(\d+)(?:/|$)', parsed.path if parsed.scheme else key)
        if not match:
            raise CollectionError('Invalid App Store app identifier')
        return match.group(1)

    @staticmethod
    def _valid_next_url(url, app_id):
        try:
            parsed = urlsplit(url)
            return (parsed.scheme == 'https' and parsed.hostname == 'api.appstoreconnect.apple.com'
                    and parsed.port in (None, 443) and not parsed.username and not parsed.password
                    and not parsed.fragment and parsed.path == f'/v1/apps/{app_id}/customerReviews')
        except ValueError:
            return False

    def fetch_page(self, source, grant, mapping, cursor=None):
        token = self._authorize(source, grant)
        app_id = self._app_id(mapping)
        url = cursor or f'{self.endpoint}/{app_id}/customerReviews?{urlencode({"limit": 200, "sort": "-createdDate"})}'
        if not self._valid_next_url(url, app_id):
            raise CollectionError('Invalid App Store pagination URL')
        response = self.request_json(url, token)
        review_items = response.get('data', [])
        if not isinstance(review_items, list):
            raise CollectionError('Invalid App Store review response')
        mapped_url = str(mapping.get('external_key', ''))
        if not mapped_url.startswith('https://apps.apple.com/'):
            mapped_url = f'https://apps.apple.com/app/id{app_id}'
        rows, seen = [], set()
        for item in review_items:
            if not isinstance(item, dict) or not isinstance(item.get('attributes'), dict):
                continue
            attributes = item['attributes']
            external_id = item.get('id')
            if not isinstance(external_id, (str, int)) or str(external_id) in seen:
                continue
            try:
                published_at = str(attributes.get('createdDate', '')).replace('Z', '+00:00')
                published = date.fromisoformat(published_at[:10]).isoformat()
                rating = float(attributes['rating'])
            except (TypeError, ValueError, KeyError):
                continue
            seen.add(str(external_id))
            text = None
            if self._is_full_text_allowed(source, grant):
                title = attributes.get('title')
                body = attributes.get('body')
                text = '\n\n'.join(part for part in (title, body) if isinstance(part, str) and part)
                text = text or None
            rows.append(self._standard_record(
                external_id, mapping, published, mapped_url, text, rating, 5,
            ))
        links = response.get('links') or {}
        if not isinstance(links, dict):
            raise CollectionError('Invalid App Store pagination response')
        next_url = links.get('next')
        if next_url and (not isinstance(next_url, str) or not self._valid_next_url(next_url, app_id) or next_url == cursor):
            raise CollectionError('Invalid App Store pagination link')
        return rows, next_url


class ConnectorRegistry:
    def __init__(self):
        self._connectors = {
            'approved_import': ApprovedImportConnector(),
            'apify': ApifyDatasetConnector(),
            'permitted_crawl': PermittedCrawlConnector(),
        }
        self._api_connectors = {
            'google-play': GooglePlayReviewsConnector(),
            'apple-app-store': AppleAppStoreReviewsConnector(),
        }
        # Import lazily to avoid the native adapter's dependency on this module.
        from .mangrove_live import MangroveAPIConnector
        self._api_connectors['mangrove-reviews'] = MangroveAPIConnector()

    def register(self, method, connector):
        if method not in {'authorized_api', 'permitted_crawl', 'composio'}:
            raise ValueError('Unsupported extension method')
        self._connectors[method] = connector

    def get(self, method, source=None):
        if method == 'authorized_api' and source:
            connector = self._api_connectors.get(source.get('id'))
            if connector:
                return connector
        if method not in self._connectors:
            raise Unsupported()
        return self._connectors[method]
