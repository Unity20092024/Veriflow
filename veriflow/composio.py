"""Discovery first: never guess toolkit names or execute undiscovered tools.

No credentials or connected-account payloads are stored. Google Trends capability
is an inventory finding, not proof of provider access or collection permission.
"""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request
from .connectors import CollectionError, RateLimited
from .config import load_environment

BASE_URL = 'https://backend.composio.dev/api/v3.1'


class DiscoveryUnavailable(CollectionError):
    code = 'discovery_unavailable'


class ComposioClient:
    def __init__(self, api_key=None, user_id=None, transport=None, sdk=None):
        load_environment()
        self.sdk = sdk
        self.api_key = api_key or os.environ.get('COMPOSIO_API_KEY')
        self.user_id = user_id or os.environ.get('COMPOSIO_USER_ID')
        self.transport = transport

    def _get(self, path, params):
        if not self.api_key or not self.user_id:
            raise DiscoveryUnavailable('Configure COMPOSIO_API_KEY and COMPOSIO_USER_ID')
        if self.transport is None:
            return self._sdk_get(path, params)
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


    def _ensure_sdk(self):
        if not self.api_key or not self.user_id:
            raise DiscoveryUnavailable('Configure COMPOSIO_API_KEY and COMPOSIO_USER_ID')
        if self.sdk is None:
            from composio import Composio
            import logging
            logger = logging.Logger('veriflow.composio-sdk')
            logger.addHandler(logging.NullHandler())
            logger.propagate = False
            self.sdk = Composio(api_key=self.api_key, base_url=BASE_URL, timeout=20, max_retries=0,
                allow_tracking=False, dangerously_allow_auto_upload_download_files=False,
                file_upload_dirs=False, logger=logger)
        return self.sdk

    @staticmethod
    def _sdk_error(exc):
        status = getattr(exc, 'status_code', None)
        if status == 429:
            try:
                delay = int(exc.response.headers.get('Retry-After', '60'))
            except (ValueError, AttributeError):
                delay = 60
            raise RateLimited(delay) from None
        error = DiscoveryUnavailable()
        error.code = 'authentication_failed' if status == 401 else 'permission_denied' if status == 403 else 'discovery_unavailable'
        raise error from None

    def _sdk_get(self, path, params):
        sdk = self._ensure_sdk()
        try:
            endpoint = sdk.client.connected_accounts if path == '/connected_accounts' else sdk.client.tools
            response = endpoint.list(**params)
            return response.model_dump(mode='json') if hasattr(response, 'model_dump') else response
        except Exception as exc:
            self._sdk_error(exc)

    def execute_read_only(self, binding, arguments, inventory):
        """Execute only a manually approved, pinned action on a discovered account.

        Discovery is repeated immediately before use; no account or tool is created.
        Read-only semantics require operator review of the actual action contract.
        """
        import hashlib
        from jsonschema import Draft202012Validator
        from .connectors import AccessDenied
        if not binding['enabled'] or not binding['read_only_approved']:
            raise AccessDenied()
        if binding['user_scope_hash'] != hashlib.sha256(self.user_id.encode()).hexdigest():
            raise AccessDenied()
        account = next((a for a in inventory['connected_services']
                        if a['id'] == binding['connected_account_id']
                        and a['toolkit'] == binding['provider'] and a['status'] == 'ACTIVE'), None)
        tool = next((t for t in inventory['tools'] if t['slug'] == binding['tool_slug']
                     and t['toolkit'] == binding['provider'] and t['connected']
                     and t['version'] == binding['tool_version']), None)
        if not account or not tool or tool['input_parameters'] != binding['input_schema']:
            raise AccessDenied('Connected account or approved tool contract changed')
        try:
            def local_refs_only(value):
                if isinstance(value,dict):
                    for key,item in value.items():
                        if key in ('$ref','$dynamicRef') and (not isinstance(item,str) or not item.startswith('#')):
                            raise ValueError('Remote schema references are unsupported')
                        local_refs_only(item)
                elif isinstance(value,list):
                    for item in value:
                        local_refs_only(item)
            local_refs_only(binding['input_schema'])
            if len(json.dumps(arguments)) > 100_000:
                raise ValueError('Action arguments too large')
            Draft202012Validator.check_schema(binding['input_schema'])
            Draft202012Validator(binding['input_schema']).validate(arguments)
        except Exception:
            raise AccessDenied('Arguments do not satisfy the reviewed tool schema') from None
        try:
            result = self._ensure_sdk().tools.execute(
                binding['tool_slug'], arguments=arguments,
                connected_account_id=binding['connected_account_id'],
                user_id=self.user_id, version=binding['tool_version'])
            result = result.model_dump(mode='json') if hasattr(result, 'model_dump') else result
            if not isinstance(result, dict) or result.get('successful') is not True:
                raise DiscoveryUnavailable('Provider action failed')
            return result['data']
        except CollectionError:
            raise
        except Exception as exc:
            self._sdk_error(exc)
