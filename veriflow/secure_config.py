"""Hidden terminal-only token entry. Never accept a token as a CLI argument."""
import getpass
import os
import stat
import sys
import tempfile
import warnings
from pathlib import Path
from .config import ALLOWED_KEYS,read_environment
from .connectors import CollectionError

DEFAULT_ENV=Path(__file__).resolve().parents[2]/'.veriflow-secrets/runtime.env'
REPOSITORY=Path(__file__).resolve().parents[1]


class SecureConfigError(CollectionError):
    code='secure_configuration_failed'


def write_environment(path,updates):
    path=Path(path).absolute()
    if path.resolve().is_relative_to(REPOSITORY) or path.is_symlink():
        raise SecureConfigError('Store server secrets outside the repository')
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    info=path.parent.stat()
    if info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)&0o077:
        raise SecureConfigError('Secret directory must be owner-only')
    values=read_environment(path) if path.exists() else {}
    if any(k not in ALLOWED_KEYS or not isinstance(v,str) or '\n' in v or '\r' in v or '\x00' in v for k,v in updates.items()):
        raise SecureConfigError('Invalid server configuration')
    values.update(updates)
    fd,tmp=tempfile.mkstemp(prefix='.runtime-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as out:
            os.fchmod(out.fileno(),0o600)
            out.write(''.join(k+'='+v+'\n' for k,v in values.items()))
            out.flush();os.fsync(out.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return path


def configure_token(path=DEFAULT_ENV):
    if not sys.stdin.isatty():
        error=SecureConfigError();error.code='interactive_terminal_required';raise error
    with warnings.catch_warnings():
        warnings.simplefilter('error',getpass.GetPassWarning)
        token=getpass.getpass('APIFY_TOKEN (hidden input): ')
    if not 20<=len(token)<=4096 or any(c.isspace() or ord(c)<32 for c in token):
        error=SecureConfigError();error.code='invalid_token_format';raise error
    # Token configuration never enables paid runs or overwrites DB/admin secrets.
    target=write_environment(path,{'APIFY_TOKEN':token,'APIFY_MAX_RUN_USD':'1',
        'APIFY_ROLLING_24H_BUDGET_USD':'1','APIFY_MAX_RECORDS':'20','APIFY_PAID_RUNS_ENABLED':'false'})
    return dict(apify_token_configured=True,environment_file=str(target),paid_runs_enabled=False)
