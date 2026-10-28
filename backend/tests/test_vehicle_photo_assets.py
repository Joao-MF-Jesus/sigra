"""Static assets remain complete and separate from the exact Python file plane."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import vehicle_photo_assets as assets
import verify_published_sources as sources
import build_preview_project as builder
import release_packaging as packaging


class VehiclePhotoAssetsTests(TestCase):
    def test_assets_are_all_pinned_and_stay_outside_application(self):
        expected = assets.photo_assets(ROOT)
        self.assertEqual(len(expected), 106)
        with TemporaryDirectory(dir=ROOT / 'backend/tests') as tmp:
            target = Path(tmp) / 'project'
            receipt = builder.assemble(target)
            self.assertFalse(list((target / 'application').rglob('*.webp')))
            self.assertEqual(set(expected), {p.name for p in (target / 'public-assets/vehicle-photos').iterdir()})
            config = json.loads((target / 'vercel.json').read_text())
            self.assertIn('application/frontend/dist/assets/vehicle-photos/**', config['functions']['api/index.py']['excludeFiles'])
            self.assertIn('public-assets/vehicle-photos/**', config['functions']['api/index.py']['excludeFiles'])
            self.assertNotIn('test-results,dist', config['functions']['api/index.py']['includeFiles'])
            self.assertFalse(receipt['private_runtime_configuration_included'])

    def test_tampering_missing_files_extra_files_and_license_gap_block(self):
        original = json.loads((ROOT / assets.MANIFEST).read_text(encoding='utf-8'))
        source = next(iter(original['photos'].values()))['variants'][0]
        for case in ('bytes', 'missing', 'extra', 'license'):
            with self.subTest(case=case), TemporaryDirectory(dir=ROOT / 'backend/tests') as tmp:
                fake = Path(tmp)
                directory = fake / assets.DIRECTORY
                directory.mkdir(parents=True)
                manifest = copy.deepcopy(original)
                for photo in manifest['photos'].values():
                    for image in photo['variants']:
                        name = image['src'].removeprefix(assets.PREFIX)
                        (directory / name).write_bytes((ROOT / assets.DIRECTORY / name).read_bytes())
                first = directory / source['src'].removeprefix(assets.PREFIX)
                if case == 'bytes': first.write_bytes(first.read_bytes() + b'tamper')
                if case == 'missing': first.unlink()
                if case == 'extra': (directory / 'unexpected.webp').write_bytes(b'not admitted')
                if case == 'license': next(iter(manifest['photos'].values()))['artist'] = ''
                path = fake / assets.MANIFEST
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(manifest),encoding='utf-8')
                with self.assertRaises(ValueError): assets.photo_assets(fake)

    def test_source_package_admits_exact_photos_not_arbitrary_media(self):
        expected = assets.photo_assets(ROOT)
        for name in expected:
            path = ROOT / assets.DIRECTORY / name
            self.assertIsNone(packaging._skip_reason(path, ROOT))
        with TemporaryDirectory(dir=ROOT / 'backend/tests') as tmp:
            fake = Path(tmp)
            image = fake / assets.DIRECTORY / next(iter(expected))
            image.parent.mkdir(parents=True)
            (fake / assets.MANIFEST).parent.mkdir(parents=True)
            (fake / assets.MANIFEST).write_bytes((ROOT / assets.MANIFEST).read_bytes())
            image.write_bytes(b'not the pinned image')
            self.assertEqual(packaging._skip_reason(image,fake),'forbidden_photo_asset')
            included, _, violations = packaging.collect_release_files(fake)
            self.assertNotIn(image,included)
            self.assertTrue(any(v['reason']=='forbidden_photo_asset' for v in violations))
            nested = image.parent / 'unreviewed' / image.name
            nested.parent.mkdir()
            nested.write_bytes((ROOT / assets.DIRECTORY / image.name).read_bytes())
            self.assertEqual(packaging._skip_reason(nested,fake),'forbidden_photo_asset')
            arbitrary = fake / 'private.webp'
            arbitrary.write_bytes(b'arbitrary')
            self.assertEqual(packaging._skip_reason(arbitrary,fake),'excluded_extension')

    def test_feature_parent_and_hashes_remain_strict(self):
        feature = ROOT / 'deploy/published/vehicle-photos-revision.json'
        value = json.loads(feature.read_text())
        actual_read = Path.read_text
        for case in ('parent', 'before', 'candidate'):
            data = copy.deepcopy(value)
            if case == 'parent': data['parent_candidate'] = 'sigra-' + '0'*24
            if case == 'before': next(iter(data['changes'].values()))['before'] = '0'*64
            if case == 'candidate': data['candidate']['release_id'] = 'not an identity'
            def read(path, *args, **kwargs):
                return json.dumps(data) if path == feature else actual_read(path,*args,**kwargs)
            with self.subTest(case=case), patch.object(Path,'read_text',read), self.assertRaises(ValueError):
                sources.current_mapping()
