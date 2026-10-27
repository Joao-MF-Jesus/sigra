"""Inspect an official Linux Function; never launch it against a database."""
import argparse
import hashlib
import json
from pathlib import Path
import stat
import sys
import zipfile


def validate(output):
    output = Path(output)
    receipt = json.loads((output / 'builder-receipt.json').read_text())
    archive = output / 'function.zip'
    if hashlib.sha256(archive.read_bytes()).hexdigest() != receipt['zip_sha256']:
        raise ValueError('OFFICIAL_FUNCTION_ARCHIVE_CHANGED')
    with zipfile.ZipFile(archive) as compressed:
        infos = compressed.infolist()
        if len({i.filename for i in infos}) != len(infos):
            raise ValueError('DUPLICATE_FUNCTION_ENTRIES')
        for info in infos:
            name = Path(info.filename)
            if name.is_absolute() or '..' in name.parts:
                raise ValueError('UNSAFE_FUNCTION_PATH')
            destination = output / 'function' / name
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                if not destination.is_symlink() or destination.readlink().as_posix() != compressed.read(info).decode():
                    raise ValueError('FUNCTION_LINK_CHANGED')
                if not destination.resolve(strict=True).is_relative_to((output / 'function').resolve()):
                    raise ValueError('FUNCTION_LINK_ESCAPES')
            elif not info.is_dir():
                if not destination.is_file() or destination.is_symlink() or destination.read_bytes() != compressed.read(info):
                    raise ValueError('FUNCTION_BYTES_CHANGED')
                if stat.S_IMODE(destination.stat().st_mode) != stat.S_IMODE(mode):
                    raise ValueError('FUNCTION_MODE_CHANGED')
        size = sum(i.file_size for i in infos)
    if size >= 225 * 1024 * 1024:
        raise ValueError('OBSERVED_REMOTE_BUILDER_SIZE_BUDGET_EXCEEDED')
    root = output / 'function' / 'application'
    vendor = output.resolve() / 'function' / '_vendor'
    sys.path.insert(0, str(vendor))
    sys.path.insert(0, str(root / 'backend'))
    import pydantic
    import psycopg
    import sqlalchemy
    for dependency in (pydantic, psycopg, sqlalchemy):
        if not Path(dependency.__file__).resolve().is_relative_to(vendor):
            raise ValueError('IMPORT_NOT_FROM_OFFICIAL_FUNCTION_VENDOR')
    from app.release_manifest import verify_release
    manifest = json.loads((root / 'release/manifest.json').read_text())
    verify_release(root, root / 'release/manifest.json', manifest['release_id'])
    for name in ['functional-acceptance.json', 'neon-transport-acceptance.json']:
        if (root / 'release' / name).exists():
            raise ValueError('PRIVATE_ACCEPTANCE_IN_PUBLIC_FUNCTION')
    from app import vercel_runtime
    vercel_runtime.create_vercel_app()  # Import/factory only; lifespan requires private config.
    try:
        vercel_runtime.prepare_environment({}, output / 'not-created-private-scratch')
    except vercel_runtime.VercelBlocked as exc:
        if exc.code != 'VERCEL_ENTRYPOINT_DISABLED':
            raise
    else:
        raise ValueError('UNCONFIGURED_RUNTIME_DID_NOT_FAIL_CLOSED')
    result = dict(receipt, status='PUBLIC_LINUX_FUNCTION_VERIFIED_PRIVATE_RUNTIME_NOT_STARTED',
                  uncompressed_zip_member_bytes=size, files=len(infos), release_id=manifest['release_id'],
                  full_manifest_verified=True, real_database_runtime_validated=False)
    (output / 'validation.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    print(json.dumps(validate(parser.parse_args().output)))
