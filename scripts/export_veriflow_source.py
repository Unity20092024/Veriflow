"""Create a versioned portable source snapshot without secrets or datasets."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
DATA_FILES = {
    'data/sources.json',
    'data/source-capabilities.json',
    'data/collection-strategy.json',
}
SECRET_PATTERNS = (
    re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----'),
    re.compile(
        rb'(?i)postgres(?:ql)?://[^/\s:@]+:(?!your[_-]?password|password|placeholder|example)[^@\s]{8,}@'
        rb'(?:aws-1-us-west-2\.pooler\.supabase\.com|db\.[a-z0-9-]+\.supabase\.co)'
    ),
    re.compile(rb'\b(?:sk_live_|sk_test_|apify_api_|gh[pousr]_|xox[baprs]-)[A-Za-z0-9_-]{20,}\b'),
    re.compile(rb'\bglpat-[A-Za-z0-9_-]{20,}\b'),
    re.compile(rb'\bAIza[0-9A-Za-z_-]{30,}\b'),
    re.compile(rb'\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b'),
    re.compile(
        rb'(?i)\b(?:ADMIN_PASSWORD|VERIFLOW_APP_PASSWORD|VERIFLOW_RESET_POSTGRES_PASSWORD|'
        rb'VERIFLOW_RESET_CONFIRM|APIFY_API_KEY|APIFY_TOKEN|COMPOSIO_API_KEY)\s*=\s*'
        rb'["\']([^"\']{12,})["\']'
    ),
)


def versioned_output():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    base = ROOT / 'generated-artifacts' / f'veriflow-complete-source-{stamp}.zip'
    output = base
    suffix = 2
    while output.exists():
        output = base.with_name(f'{base.stem}-{suffix}{base.suffix}')
        suffix += 1
    return output


def contains_secret(content):
    placeholders = (
        b'a-long-random-secret-of-at-least-24-characters',
        b'server-side-project-key',
        b'your-password',
        b'your-secret',
        b'placeholder',
        b'example',
        b'redacted',
        b'changeme',
        b'replace-me',
    )
    for index, pattern in enumerate(SECRET_PATTERNS):
        for match in pattern.finditer(content):
            if index == len(SECRET_PATTERNS) - 1:
                value = match.group(1).strip().lower()
                if any(marker in value for marker in placeholders):
                    continue
            return True
    return False


def main():
    # Git's source allowlist includes modifications and nonignored new source.
    # Add the small safe runtime catalogs explicitly; omit generated datasets.
    listed = subprocess.check_output(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
        cwd=ROOT).decode().split('\0')
    excluded = ('.agents/', 'attached_assets/', 'maintenance/',
                'generated-artifacts/', '.local/', '.config/', '.cache/')
    files = []
    listed = set(name for name in listed if name)
    listed.update(DATA_FILES)
    for name in sorted(listed):
        if not name or name.startswith(excluded):
            continue
        path = ROOT / name
        if any(part in {'node_modules','.pythonlibs','.venv','venv','__pycache__',
                        '.pytest_cache','.mypy_cache','dist','coverage'}
               for part in path.relative_to(ROOT).parts):
            continue
        if (not path.is_file() or path.is_symlink()
                or (path.name.startswith('.env') and path.name not in ('.env.example','.env.sample'))
                or path.name.endswith('.env')
                or path.suffix in ('.pem', '.key', '.p12', '.pfx', '.sqlite', '.sqlite3', '.db')
                or path.stat().st_size > 5_000_000):
            continue
        files.append(name)
    manifest = []
    required = {
        'veriflow/worker.py','veriflow/bounded_collection.py',
        'veriflow/libreviews_live.py','veriflow/admin.py','veriflow/exports.py',
        'veriflow/mangrove_live.py','veriflow/strategy.py','veriflow/coverage.py',
        'supabase/migrations/20261115050000_bounded_free_batch.sql',
        'supabase/migrations/20261115180000_product_coverage_strategy.sql',
        'supabase/migrations/20261115190000_mangrove_and_product_classifications.sql',
        'requirements-veriflow.txt','pyproject.toml','pnpm-lock.yaml',
        'docs/veriflow/source-backup-restore.md','docs/veriflow/mangrove-worker.md',
        'artifacts/veriflow/vite.config.ts','data/sources.json',
        'data/source-capabilities.json','data/collection-strategy.json',
    }
    if not required.issubset(files):
        raise ValueError('Source backup is missing required application files')
    output = versioned_output()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            content = (ROOT/name).read_bytes()
            manifest.append({'path': name, 'sha256': hashlib.sha256(content).hexdigest()})
            archive.writestr('veriflow/'+name, content)
        # This is the public CA, not a client/private key or credential.
        from veriflow.config import load_environment
        load_environment()
        ca = os.environ.get('SUPABASE_SSL_ROOT_CERT')
        if ca and Path(ca).is_file():
            content = Path(ca).read_bytes()
            if b'BEGIN CERTIFICATE' in content and b'PRIVATE KEY' not in content:
                archive.writestr('veriflow/certificates/supabase-ca.crt', content)
                manifest.append({
                    'path': 'certificates/supabase-ca.crt',
                    'sha256': hashlib.sha256(content).hexdigest(),
                })
        archive.writestr('veriflow/SOURCE-MANIFEST.json', json.dumps(manifest, indent=2))
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError('Source archive integrity check failed')
        required_archive_paths = {'veriflow/' + name for name in required}
        if not required_archive_paths.issubset(archive.namelist()):
            raise ValueError('Source archive is missing required application files')
        flagged = []
        for member in archive.infolist():
            if member.is_dir() or member.filename.endswith('SOURCE-MANIFEST.json'):
                continue
            content = archive.read(member)
            if contains_secret(content):
                flagged.append(member.filename)
        if flagged:
            # Report paths only; never reveal matched credential material.
            raise ValueError('Potential credential material found in: ' + ', '.join(flagged))
    print(json.dumps({'path': str(output.relative_to(ROOT)), 'source_files': len(files),
                      'bytes': output.stat().st_size,
                      'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
