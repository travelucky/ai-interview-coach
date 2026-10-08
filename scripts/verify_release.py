"""Reject release inputs that contain local state, credentials, or missing assets."""

import argparse
import re
# Only a fixed Git command is executed below and no shell is involved.
import subprocess  # nosec B404
import sys
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parent.parent
REQUIRED = {
    'LICENSE',
    'SECURITY.md',
    'VERSION',
    'README.md',
    'requirements.txt',
    'run.py',
    'start.bat',
    'scripts/setup.ps1',
    'scripts/start.ps1',
    'seed/positions.json',
    'seed/questions.json',
    'seed/knowledge.json',
    'app/static/vendor/bootstrap/bootstrap.min.css',
    'app/static/vendor/bootstrap/bootstrap.bundle.min.js',
    'app/static/vendor/chart/chart.umd.min.js',
}
SECRET_PATTERNS = {
    'OpenAI-style key': re.compile(rb'\bsk-[A-Za-z0-9_-]{20,}\b'),
    'GitHub token': re.compile(rb'\bgh[pousr]_[A-Za-z0-9_]{20,}\b'),
    'AWS access key': re.compile(rb'\bAKIA[0-9A-Z]{16}\b'),
    'Google API key': re.compile(rb'\bAIza[0-9A-Za-z_-]{30,}\b'),
    'private key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
}
TEXT_SUFFIXES = {
    '.py', '.js', '.css', '.html', '.md', '.txt', '.json', '.ini', '.toml',
    '.yaml', '.yml', '.ps1', '.bat', '.example',
}


def _forbidden(name):
    path = PurePosixPath(name.replace('\\', '/'))
    parts = {part.lower() for part in path.parts}
    basename = path.name.lower()
    if basename == '.env' or (basename.startswith('.env.') and basename != '.env.example'):
        return 'local environment configuration'
    if parts & {'.git', '.venv', 'venv', '__pycache__', '.pytest_cache', 'instance', 'uploads', 'recordings', 'logs'}:
        return 'runtime directory'
    if basename.endswith(('.db', '.sqlite', '.sqlite3', '.log', '.pyc')):
        return 'runtime data'
    return None


def _tracked_entries():
    result = subprocess.run(
        ['git', 'ls-files', '-z'], cwd=ROOT, check=True, capture_output=True  # nosec B603 B607
    )
    names = [item.decode('utf-8') for item in result.stdout.split(b'\0') if item]
    return {name: (ROOT / name).read_bytes() for name in names if (ROOT / name).is_file()}


def _archive_entries(path):
    with zipfile.ZipFile(path) as archive:
        return {
            info.filename: archive.read(info)
            for info in archive.infolist()
            if not info.is_dir()
        }


def verify(entries):
    errors = []
    normalized = {name.replace('\\', '/').lstrip('./'): data for name, data in entries.items()}
    # Allow a single top-level release directory in a hand-built archive.
    if normalized and all('/' in name for name in normalized):
        roots = {name.split('/', 1)[0] for name in normalized}
        if len(roots) == 1:
            normalized = {
                name.split('/', 1)[1]: data for name, data in normalized.items()
            }
    visible = set(normalized)
    for required in REQUIRED:
        if required not in visible and not any(name.endswith('/' + required) for name in visible):
            errors.append(f'Missing required release file: {required}')
    for name, data in normalized.items():
        reason = _forbidden(name)
        if reason:
            errors.append(f'Contains {reason}: {name}')
        if PurePosixPath(name).suffix.lower() in TEXT_SUFFIXES:
            if name == 'scripts/verify_release.py':
                continue
            for label, pattern in SECRET_PATTERNS.items():
                if pattern.search(data):
                    errors.append(f'Possible {label}: {name}')
            if not name.startswith('tests/') and (
                b'cdn.jsdelivr.net' in data or b'unpkg.com' in data
            ):
                errors.append(f'External CDN dependency remains: {name}')
    return errors


def main():
    parser = argparse.ArgumentParser(description='Verify release contents are clean and self-contained.')
    parser.add_argument('--archive', type=Path, help='Check a ZIP instead of Git-tracked files.')
    args = parser.parse_args()
    entries = _archive_entries(args.archive) if args.archive else _tracked_entries()
    errors = verify(entries)
    if errors:
        print('Release verification failed:')
        for error in errors:
            print(f'- {error}')
        return 1
    print(f'Release verification passed: {len(entries)} files; no runtime data, secrets, or CDN dependencies found.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
