"""Public clean-checkout recipe and negative guards; no runtime credentials."""
import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_preview_project as builder
import prepare_build_inputs as inputs
import verify_published_sources as sources


class ReproduciblePreviewBuildTests(unittest.TestCase):
    def test_two_assemblies_are_byte_identical_and_private_files_absent(self):
        with TemporaryDirectory(dir=ROOT / 'backend/tests') as temporary:
            a, b = Path(temporary) / 'a', Path(temporary) / 'b'
            first, second = builder.assemble(a), builder.assemble(b)
            self.assertEqual(first, second)
            self.assertNotEqual(first['release_id'], first['historical_release'])
            entries = {p.relative_to(a) for p in a.rglob('*') if p.is_file()}
            self.assertEqual(entries, {p.relative_to(b) for p in b.rglob('*') if p.is_file()})
            for name in entries:
                self.assertEqual(builder.digest(a / name), builder.digest(b / name), str(name))
                self.assertFalse((a / name).is_symlink())
            self.assertFalse((a / 'application/release/functional-acceptance.json').exists())
            self.assertFalse((a / 'application/release/neon-transport-acceptance.json').exists())
            config = json.loads((a / 'vercel.json').read_text())
            self.assertIsInstance(config['functions']['api/index.py']['includeFiles'], str)
            target = a / 'application/backend/app/neon_transport.py'
            target.write_bytes(target.read_bytes() + b'\n# synthetic tamper\n')
            manifest = a / 'application/release/manifest.json'
            with self.assertRaisesRegex(ValueError, 'RELEASE_FILE_CHANGED'):
                builder.verify_release(a / 'application', manifest, first['release_id'])

    def test_existing_directory_is_not_overwritten(self):
        with TemporaryDirectory(dir=ROOT / 'backend/tests') as temporary:
            with self.assertRaisesRegex(ValueError, 'NEW_EMPTY_BUILD_DIRECTORY_REQUIRED'):
                builder.assemble(temporary)

    def test_original_mapping_cannot_be_rewritten(self):
        real = sources.ROOT
        with TemporaryDirectory(dir=ROOT / 'backend/tests') as temporary:
            fake = Path(temporary)
            (fake / 'deploy/published').mkdir(parents=True)
            for name in ['correspondence.json', 'source-revisions.json']:
                (fake / 'deploy/published' / name).write_bytes((real / 'deploy/published' / name).read_bytes())
            baseline = fake / 'deploy/published/correspondence.json'
            baseline.write_bytes(baseline.read_bytes() + b' ')
            with patch.object(sources, 'ROOT', fake):
                with self.assertRaisesRegex(ValueError, 'HISTORICAL_CORRESPONDENCE_CHANGED'):
                    sources.current_mapping()

    def test_unsafe_destination_is_rejected(self):
        for name in ['../outside', '/absolute', 'a\\b', 'C:/private']:
            with self.assertRaisesRegex(ValueError, 'UNSAFE_BUILD_DESTINATION'):
                builder.safe_destination(ROOT, name)

    def test_public_input_hash_change_blocks_before_any_fallback(self):
        with TemporaryDirectory(dir=ROOT / 'backend/tests') as temporary:
            fake = Path(temporary)
            (fake / 'build_inputs/revision6').mkdir(parents=True)
            for name in ['inputs.json', 'coverage-decision.json']:
                (fake / 'build_inputs/revision6' / name).write_bytes((ROOT / 'build_inputs/revision6' / name).read_bytes())
            (fake / 'build_inputs/revision6/plan.json.gz').write_bytes(b'NOT THE APPROVED GZIP')
            with patch.object(inputs, 'ROOT', fake):
                with self.assertRaisesRegex(ValueError, 'PACKED_PLAN_FILE_CHANGED'):
                    inputs.prepare(fake / 'restored')
