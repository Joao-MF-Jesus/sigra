"""Reviewed public additions preserve the immutable baseline and candidate identity."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_preview_project as builder
import verify_published_sources as sources


class ReviewedSourceAdditionsTests(TestCase):
    def current(self):
        return json.loads((ROOT / 'deploy/published/source-revisions.json').read_text())

    def mapping_for(self, revised):
        with TemporaryDirectory(dir=ROOT / 'backend/tests') as temporary:
            fake = Path(temporary)
            (fake / 'deploy/published').mkdir(parents=True)
            (fake / 'deploy/published/correspondence.json').write_bytes(
                (ROOT / 'deploy/published/correspondence.json').read_bytes())
            (fake / 'deploy/published/source-revisions.json').write_text(json.dumps(revised))
            with patch.object(sources, 'ROOT', fake):
                return sources.current_mapping()

    def test_complete_reviewed_application_identity_is_reproduced(self):
        with TemporaryDirectory(dir=ROOT / 'backend/tests') as temporary:
            receipt = builder.assemble(Path(temporary) / 'project')
            self.assertEqual(receipt['release_id'], 'sigra-a6987bc66a8feb330f1db740')
            self.assertEqual(receipt['application_files'], 469)
            self.assertFalse(receipt['private_runtime_configuration_included'])

    def test_required_public_modules_and_tests_are_explicitly_mapped(self):
        mapping = sources.current_mapping()
        entries = {e['repository_path']: e for e in mapping['application_files']}
        self.assertEqual(len(self.current()['additions']), 9)
        for entry in self.current()['additions']:
            self.assertEqual(entries[entry['repository_path']], entry)
            self.assertEqual(sources.sha(ROOT / entry['repository_path']), entry['repository_sha256'])

    def test_changed_addition_content_is_not_admitted(self):
        actual = sources.sha
        name = self.current()['additions'][0]['repository_path']
        with patch.object(sources, 'sha', side_effect=lambda p: '0' * 64 if p == ROOT / name else actual(p)):
            with self.assertRaisesRegex(ValueError, 'SOURCE_CORRESPONDENCE_DIFFERS'):
                sources.verify()

    def test_unsafe_conflicting_missing_or_malformed_metadata_blocks(self):
        for case in ('destination', 'duplicate_source', 'duplicate_destination', 'bad_hash', 'extra_field', 'non_string', 'missing_review', 'wrong_schema'):
            with self.subTest(case=case):
                data = self.current()
                first = data['additions'][0]
                if case == 'destination': first['application_path'] = '../outside'
                elif case == 'duplicate_source': data['additions'].append(copy.deepcopy(first))
                elif case == 'duplicate_destination': data['additions'][1]['application_path'] = first['application_path']
                elif case == 'bad_hash': first['repository_sha256'] = 'invalid'
                elif case == 'extra_field': first['unreviewed'] = True
                elif case == 'non_string': first['application_path'] = None
                elif case == 'missing_review': data.pop('reviewed_candidate')
                else: data['schema'] = 'sigra-explicit-source-revisions-v1'
                with self.assertRaises(ValueError):
                    self.mapping_for(data)

    def test_changed_assembly_identity_has_no_silent_fallback(self):
        mapping = sources.current_mapping()
        mapping['reviewed_candidate']['release_id'] = 'sigra-' + '0' * 24
        with TemporaryDirectory(dir=ROOT / 'backend/tests') as temporary:
            with patch.object(builder, 'current_mapping', return_value=mapping):
                with self.assertRaisesRegex(ValueError, 'ASSEMBLED_APPLICATION_DIFFERS_FROM_REVIEWED_CANDIDATE'):
                    builder.assemble(Path(temporary) / 'project')
