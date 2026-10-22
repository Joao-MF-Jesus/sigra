"""Offline correspondence check. No imports of app, network, secrets or database."""
import hashlib
import json
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_path(name):
    rel = PurePosixPath(name)
    if rel.is_absolute() or '..' in rel.parts or '\\' in name or ':' in name:
        raise ValueError('UNSAFE_CORRESPONDENCE_PATH')
    path = ROOT / name
    if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
        raise ValueError('CORRESPONDENCE_PATH_ESCAPES')
    return path


def verify():
    mapping = json.loads((ROOT / 'deploy/published/correspondence.json').read_text(encoding='utf-8'))
    mismatches = []
    for entry in mapping['application_files']:
        path = checked_path(entry['repository_path'])
        if not path.is_file() or sha(path) != entry['repository_sha256']:
            mismatches.append(entry['repository_path'])
    for name, expected in mapping['outer_project_files'].items():
        path = checked_path(name)
        if not path.is_file() or sha(path) != expected:
            mismatches.append(name)
    config = json.loads(checked_path('deploy/published/project/vercel.json').read_text())
    include = config['functions']['api/index.py']['includeFiles']
    if not isinstance(include, str) or len(include) > 256:
        mismatches.append('effective_includeFiles_schema')
    if mismatches:
        raise ValueError('SOURCE_CORRESPONDENCE_DIFFERS: ' + ', '.join(mismatches))
    return {'status': 'PUBLIC_SOURCE_CORRESPONDENCE_VERIFIED',
            'application_files': len(mapping['application_files']),
            'outer_files': len(mapping['outer_project_files']),
            'private_artifacts_not_checked': len(mapping['outside_git_artifacts']),
            'remote_tests_executed': False}


if __name__ == '__main__':
    print(json.dumps(verify()))
