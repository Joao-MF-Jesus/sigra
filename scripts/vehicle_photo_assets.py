"""Validate the bounded static-photo set; no application/DB imports or network."""
import hashlib
import json
import re
from pathlib import Path

MANIFEST = 'frontend/src/features/vehicle-images/vehiclePhotos.json'
DIRECTORY = 'frontend/public/assets/vehicle-photos'
PREFIX = '/assets/vehicle-photos/'


def photo_assets(root):
    root = Path(root).resolve()
    manifest = json.loads((root / MANIFEST).read_text(encoding='utf-8'))
    if manifest.get('schema') != 'sigra-static-vehicle-photos-v1':
        raise ValueError('PHOTO_MANIFEST_SCHEMA_DIFFERS')
    directory = root / DIRECTORY
    expected = {}
    for photo in manifest['photos'].values():
        if (not photo['artist'] or not photo['licenseUrl'].startswith('https://creativecommons.org/')
                or not photo['sourcePage'].startswith('https://commons.wikimedia.org/wiki/File:')):
            raise ValueError('PHOTO_SOURCE_OR_LICENSE_REQUIRED')
        for variant in photo['variants']:
            name = variant['src'].removeprefix(PREFIX)
            if (not variant['src'].startswith(PREFIX)
                    or not re.fullmatch(r'[a-z0-9-]+-[a-f0-9]{12}\.webp', name)
                    or name in expected or not 0 < variant['bytes'] <= 300_000):
                raise ValueError('PHOTO_PATH_OR_SIZE_DIFFERS')
            path = directory / name
            if path.is_symlink() or directory.is_symlink() or not path.is_file():
                raise ValueError('PHOTO_REGULAR_FILE_REQUIRED')
            data = path.read_bytes()
            if (len(data) != variant['bytes'] or hashlib.sha256(data).hexdigest() != variant['sha256']
                    or data[:4] != b'RIFF' or data[8:12] != b'WEBP'):
                raise ValueError('PHOTO_BYTES_DIFFER')
            expected[name] = variant['sha256']
    actual = {p.name for p in directory.iterdir()}
    if actual != set(expected):
        raise ValueError('PHOTO_FILE_SET_DIFFERS')
    return expected
