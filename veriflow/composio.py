"""Discovery first: never guess toolkit names or execute undiscovered tools.

No credentials or connected-account payloads are stored. Google Trends capability
is an inventory finding, not proof of provider access or collection permission.
"""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from .connectors import CollectionError, RateLimited

BASE_URL = 'https://backend.composio.dev/api/v3.1'


class DiscoveryUnavailable(CollectionError):
    code = 'discovery_unavailable'


class ComposioClient:
    def __init__(self, api_key=None, user_id=None, transport=None):
        self.api_key = api_key or os.environ.get('COMPOSIO_API_KEY')
        self.user_id = user_id or os.environ.get('COMPOSIO_USER_ID')
        self.transport = transport or urlopen

    def _get(self, path, params):
        if not self.api_key or not self.user_id:
            raise DiscoveryUnavailable('Configure COMPOSIO_API_KEY and COMPOSIO_USER_ID')
        request = Request(BASE_URL + path + '?' + urlencode(params, doseq=True),
                          headers={'x-api-key': self.api_key, 'Accept': 'application/json'})
        try:
            with self.transport(request, timeout=20) as response:
                body = response.read(5_000_001)
                if len(body) > 5_000_000:
                    raise DiscoveryUnavailable('Discovery response too large')
                return json.loads(body)
        except HTTPError as exc:
            if exc.code == 429:
                try:
                    delay = int(exc.headers.get('Retry-After', '60'))
                except ValueError:
                    delay = 60
                raise RateLimited(delay) from None
            raise DiscoveryUnavailable('Composio discovery request failed') from None
        except (URLError, TimeoutError, ValueError):
            raise DiscoveryUnavailable('Composio discovery request failed') from None

    def _pages(self, path, params):
        seen = set()
        for _ in range(100):
            page = self._get(path, dict(params, limit=100))
            if not isinstance(page.get('items'), list):
                raise DiscoveryUnavailable('Unexpected discovery response')
            yield from page['items']
            cursor = page.get('next_cursor')
            if not cursor:
                return
            if cursor in seen:
                raise DiscoveryUnavailable('Repeated pagination cursor')
            seen.add(cursor)
            params = dict(params, cursor=cursor)
        raise DiscoveryUnavailable('Discovery page limit exceeded')

    def discover(self):
        accounts = list(self._pages('/connected_accounts', {'user_ids': [self.user_id], 'statuses': ['ACTIVE']}))
        # Keep only provider, status and account id; provider credentials and
        # account owners' personal details are not part of the inventory.
        connected = [dict(id=a['id'], toolkit=a['toolkit']['slug'], status=a['status'])
                     for a in accounts if a.get('status') == 'ACTIVE']
        tools = {}
        for toolkit in sorted({a['toolkit'] for a in connected}):
            for t in self._pages('/tools', {'toolkit_slug': toolkit}):
                tools[t['slug']] = self._capability(t, True)
        for t in self._pages('/tools', {'query': 'Google Trends'}):
            tools.setdefault(t['slug'], self._capability(t, t['toolkit']['slug'] in {a['toolkit'] for a in connected}))
        return dict(status='discovered',connected_services=connected,tools=list(tools.values()),
                    google_trends_status='requires_capability_review',execution_enabled=False)

    @staticmethod
    def _capability(tool, connected):
        return dict(slug=tool['slug'], toolkit=tool['toolkit']['slug'],
                    version=tool.get('version'), name=tool.get('name'),
                    description=tool.get('description'), input_parameters=tool.get('input_parameters'),
                    connected=connected)
