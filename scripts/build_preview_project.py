"""Reproducible public project assembly. No private configuration or DB access."""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.release_manifest import release_id, verify_release
from app.packed_plan import APPROVED_SHA256, APPROVED_BYTES, STORAGE_FILE
from app.deployment import ACCEPTANCE_SHA256 as FUNCTIONAL_PIN
from app.neon_transport import ACCEPTANCE_SHA256 as TRANSPORT_PIN
from verify_published_sources import verify, current_mapping, checked_path


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_destination(root, name):
    rel = PurePosixPath(name)
    if rel.is_absolute() or '..' in rel.parts or '\\' in name or ':' in name:
        raise ValueError('UNSAFE_BUILD_DESTINATION')
    result = root / name
    if not result.resolve().is_relative_to(root.resolve()):
        raise ValueError('BUILD_DESTINATION_ESCAPES')
    return result


def assemble(output):
    verify()
    mapping = current_mapping()
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('NEW_EMPTY_BUILD_DIRECTORY_REQUIRED')
    inputs = json.loads((ROOT / 'build_inputs/revision6/inputs.json').read_text())
    packed = ROOT / 'build_inputs/revision6/plan.json.gz'
    if digest(packed) != inputs['compressed_sha256']:
        raise ValueError('PUBLIC_PLAN_INPUT_CHANGED')
    output.mkdir(parents=True)
    application = output / 'application'
    application.mkdir()
    for entry in mapping['application_files']:
        destination = safe_destination(application, entry['application_path'])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(checked_path(entry['repository_path']), destination)
    for name in mapping['outer_project_files']:
        relative = Path(name).relative_to('deploy/published/project')
        destination = safe_destination(output, relative.as_posix())
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(checked_path(name), destination)
    # The inner config is not used by the outer builder; include the same
    # effective string overlay rather than the obsolete internal array config.
    shutil.copyfile(output / 'vercel.json', application / 'vercel.json')
    (application / 'release').mkdir()
    shutil.copyfile(packed, application / STORAGE_FILE)
    files = {p.relative_to(application).as_posix(): digest(p)
             for p in sorted(application.rglob('*')) if p.is_file()}
    identity = release_id(files)
    reviewed = mapping.get('reviewed_candidate')
    if reviewed is not None and (identity != reviewed['release_id'] or len(files) != reviewed['application_files']):
        raise ValueError('ASSEMBLED_APPLICATION_DIFFERS_FROM_REVIEWED_CANDIDATE')
    manifest = {
        'schema': 'sigra-source-release-v1', 'files': files, 'release_id': identity,
        'based_on_historical_release': mapping['release'],
        'private_runtime_configuration': 'external-acceptances-v1',
        'functional_acceptance_sha256': FUNCTIONAL_PIN, 'transport_acceptance_sha256': TRANSPORT_PIN,
        'runtime_plan_storage': {
            'schema': 'sigra-pinned-gzip-plan-v1', 'file': STORAGE_FILE,
            'compressed_sha256': inputs['compressed_sha256'],
            'uncompressed_sha256': APPROVED_SHA256, 'uncompressed_bytes': APPROVED_BYTES},
        'real_collection_enabled': False, 'historical_row_changed': 1,
    }
    manifest_file = application / 'release/manifest.json'
    manifest_file.write_bytes((json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode())
    verify_release(application, manifest_file, manifest['release_id'])
    # Public receipt has content identity only, never timestamps or local paths.
    receipt = {
        'schema': 'sigra-reproducible-public-build-v1', 'release_id': manifest['release_id'],
        'historical_release': mapping['release'], 'application_files': len(files),
        'manifest_sha256': digest(manifest_file), 'plan_compressed_sha256': digest(packed),
        'outer_files': {p.relative_to(output).as_posix(): digest(p)
                        for p in sorted(output.rglob('*')) if p.is_file() and not p.is_relative_to(application)},
        'private_runtime_configuration_included': False, 'remote_validation_performed': False,
    }
    (output / 'build-receipt.json').write_bytes((json.dumps(receipt, sort_keys=True, indent=2) + '\n').encode())
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(assemble(args.output), sort_keys=True))
