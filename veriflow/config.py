"""Optional owner-readable server environment file; never serve or log values."""
import os
import stat
from pathlib import Path

ALLOWED_KEYS = {'DATABASE_URL', 'SUPABASE_PROJECT_REF', 'ADMIN_USERNAME', 'ADMIN_PASSWORD',
                'COMPOSIO_API_KEY', 'COMPOSIO_USER_ID', 'APIFY_TOKEN',
                'APIFY_MAX_RUN_USD', 'APIFY_ROLLING_24H_BUDGET_USD', 'APIFY_MAX_RECORDS'}


def load_environment():
    location = os.environ.get('VERIFLOW_ENV_FILE')
    if not location:
        return
    path = Path(location)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError('Server environment file must be owner-readable only')
    for line in path.read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        key, separator, value = line.partition('=')
        if not separator or key not in ALLOWED_KEYS:
            raise ValueError('Invalid server environment configuration')
        os.environ.setdefault(key, value)
