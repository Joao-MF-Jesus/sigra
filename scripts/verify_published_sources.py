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


def current_mapping():
    baseline = ROOT / 'deploy/published/correspondence.json'
    mapping = json.loads(baseline.read_text(encoding='utf-8'))
    revisions = json.loads((ROOT / 'deploy/published/source-revisions.json').read_text(encoding='utf-8'))
    # Git's existing text policy checks this metadata out as CRLF on Windows.
    # Pin the original Git LF bytes, not one operator's checkout conversion.
    baseline_lf = baseline.read_bytes().replace(b'\r\n', b'\n')
    if hashlib.sha256(baseline_lf).hexdigest() != revisions['historical_correspondence_lf_sha256']:
        raise ValueError('HISTORICAL_CORRESPONDENCE_CHANGED')
    if revisions['schema'] != 'sigra-explicit-source-revisions-v1' or revisions['historical_release'] != mapping['release']:
        raise ValueError('SOURCE_REVISION_SCHEMA_OR_RELEASE_DIFFERS')
    entries = {entry['repository_path']: entry for entry in mapping['application_files']}
    for name, change in revisions['changes'].items():
        checked_path(name)
        if (name not in entries or entries[name]['repository_sha256'] != change['before']
                or len(change['after']) != 64 or any(c not in '0123456789abcdef' for c in change['after'])):
            raise ValueError('SOURCE_REVISION_REFERENCE_DIFFERS')
        entries[name]['repository_sha256'] = change['after']
    return mapping


def verify():
    mapping = current_mapping()
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
