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
    if revisions['schema'] not in {'sigra-explicit-source-revisions-v1', 'sigra-explicit-source-revisions-v2'} or revisions['historical_release'] != mapping['release']:
        raise ValueError('SOURCE_REVISION_SCHEMA_OR_RELEASE_DIFFERS')
    entries = {entry['repository_path']: entry for entry in mapping['application_files']}
    for name, change in revisions['changes'].items():
        checked_path(name)
        if (name not in entries or entries[name]['repository_sha256'] != change['before']
                or len(change['after']) != 64 or any(c not in '0123456789abcdef' for c in change['after'])):
            raise ValueError('SOURCE_REVISION_REFERENCE_DIFFERS')
        entries[name]['repository_sha256'] = change['after']
    additions = revisions.get('additions', [])
    if not isinstance(additions, list) or (additions and revisions['schema'] != 'sigra-explicit-source-revisions-v2'):
        raise ValueError('SOURCE_ADDITION_SCHEMA_DIFFERS')
    destinations = {entry['application_path'] for entry in mapping['application_files']}
    for entry in additions:
        if not isinstance(entry, dict) or set(entry) != {'repository_path', 'application_path', 'repository_sha256'}:
            raise ValueError('SOURCE_ADDITION_FIELDS_DIFFER')
        source, destination, expected = entry['repository_path'], entry['application_path'], entry['repository_sha256']
        if not all(isinstance(value, str) for value in (source, destination, expected)):
            raise ValueError('SOURCE_ADDITION_FIELDS_DIFFER')
        checked_path(source)
        rel = PurePosixPath(destination)
        if (not destination or not rel.parts or destination != rel.as_posix() or rel.is_absolute() or '..' in rel.parts or '\\' in destination or ':' in destination
                or source in entries or destination in destinations or len(expected) != 64
                or any(c not in '0123456789abcdef' for c in expected)):
            raise ValueError('SOURCE_ADDITION_PATH_HASH_OR_DUPLICATE_DIFFERS')
        mapping['application_files'].append(dict(entry))
        entries[source] = entry
        destinations.add(destination)
    if revisions['schema'] == 'sigra-explicit-source-revisions-v2':
        reviewed = revisions.get('reviewed_candidate', {})
        identity = reviewed.get('release_id', '')
        if (not isinstance(identity, str) or not identity.startswith('sigra-') or len(identity) != 30
                or any(c not in '0123456789abcdef' for c in identity[6:])
                or type(reviewed.get('application_files')) is not int or reviewed['application_files'] < 1):
            raise ValueError('REVIEWED_CANDIDATE_IDENTITY_REQUIRED')
        mapping['reviewed_candidate'] = reviewed
    # Preserve both historical mappings; the photo feature is a separate delta
    # against the exact main/PR3 reviewed bytes, never a replacement baseline.
    feature_file = ROOT / 'deploy/published/vehicle-photos-revision.json'
    if feature_file.exists():
        feature = json.loads(feature_file.read_text(encoding='utf-8'))
        if (feature['schema'] != 'sigra-vehicle-photos-revision-v1'
                or feature['parent_candidate'] != mapping['reviewed_candidate']['release_id']):
            raise ValueError('PHOTO_REVISION_PARENT_DIFFERS')
        for name, change in feature['changes'].items():
            checked_path(name)
            if name not in entries or entries[name]['repository_sha256'] != change['before']:
                raise ValueError('PHOTO_REVISION_REFERENCE_DIFFERS')
            if not isinstance(change['after'], str) or len(change['after']) != 64 or any(c not in '0123456789abcdef' for c in change['after']):
                raise ValueError('PHOTO_REVISION_HASH_DIFFERS')
            entries[name]['repository_sha256'] = change['after']
        for entry in feature['additions']:
            source, destination, expected = entry['repository_path'], entry['application_path'], entry['repository_sha256']
            checked_path(source)
            rel = PurePosixPath(destination)
            if (set(entry) != {'repository_path', 'application_path', 'repository_sha256'}
                    or source in entries or destination in destinations or not destination
                    or destination != rel.as_posix() or rel.is_absolute() or '..' in rel.parts
                    or '\\' in destination or ':' in destination or len(expected) != 64
                    or any(c not in '0123456789abcdef' for c in expected)):
                raise ValueError('PHOTO_ADDITION_DIFFERS')
            mapping['application_files'].append(dict(entry))
            entries[source] = entry
            destinations.add(destination)
        for name, change in feature['outer_changes'].items():
            if name != 'deploy/published/project/vercel.json' or mapping['outer_project_files'].get(name) != change['before']:
                raise ValueError('PHOTO_OUTER_REVISION_DIFFERS')
            if len(change['after']) != 64 or any(c not in '0123456789abcdef' for c in change['after']):
                raise ValueError('PHOTO_OUTER_HASH_DIFFERS')
            mapping['outer_project_files'][name] = change['after']
        candidate = feature['candidate']
        identity = candidate.get('release_id', '')
        if (not isinstance(identity, str) or len(identity) != 30 or not identity.startswith('sigra-')
                or any(c not in '0123456789abcdef' for c in identity[6:])
                or type(candidate.get('application_files')) is not int or candidate['application_files'] < 1):
            raise ValueError('PHOTO_CANDIDATE_IDENTITY_REQUIRED')
        mapping['reviewed_candidate'] = candidate
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
