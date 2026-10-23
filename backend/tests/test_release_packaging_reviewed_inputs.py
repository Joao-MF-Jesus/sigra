"""Exact, reviewed public inputs; no network, credentials or application startup."""
import gzip
import hashlib
import io
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import release_packaging as packaging

ROOT = Path(__file__).resolve().parents[2]
PLAN = "build_inputs/revision6/plan.json.gz"


class ReviewedPackageInputsTest(unittest.TestCase):
    def temporary(self):
        return TemporaryDirectory(dir=ROOT / "backend/tests")

    def test_reviewed_test_bytes_are_included_and_still_scanned(self):
        with self.temporary() as temporary:
            root = Path(temporary)
            for name, expected in packaging.REVIEWED_SYNTHETIC_URL_FIXTURES.items():
                destination = root / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, destination)
                self.assertEqual(packaging._sha256(destination), expected)
            included, _, violations = packaging.collect_release_files(root)
            self.assertEqual(violations, [])
            self.assertEqual({p.relative_to(root).as_posix() for p in included},
                             set(packaging.REVIEWED_SYNTHETIC_URL_FIXTURES))

    def test_edited_reviewed_fixture_remains_blocked(self):
        for name in packaging.REVIEWED_SYNTHETIC_URL_FIXTURES:
            with self.subTest(name=name), self.temporary() as temporary:
                root = Path(temporary)
                destination = root / name
                destination.parent.mkdir(parents=True)
                destination.write_bytes((ROOT / name).read_bytes() + b"\n# unreviewed edit\n")
                _, _, violations = packaging.collect_release_files(root)
                self.assertEqual(violations[0]["types"], ["credentialed_database_url"])

    def test_reviewed_path_cannot_fallback_to_the_generic_local_rule(self):
        from tests.test_release_packaging_collection import _database_url
        with self.temporary() as temporary:
            root = Path(temporary)
            destination = root / "backend/tests/test_deployment_preparation.py"
            destination.parent.mkdir(parents=True)
            destination.write_text(_database_url(username="synthetic-user", password="synthetic-secret",
                                                host="localhost", database="fixture_test"))
            _, _, violations = packaging.collect_release_files(root)
            self.assertEqual(violations[0]["types"], ["credentialed_database_url"])

    def test_same_fixture_bytes_at_other_paths_are_not_admitted(self):
        for name in packaging.REVIEWED_SYNTHETIC_URL_FIXTURES:
            with self.subTest(name=name), self.temporary() as temporary:
                root = Path(temporary)
                destination = root / "unreviewed" / Path(name).name
                destination.parent.mkdir()
                shutil.copyfile(ROOT / name, destination)
                _, _, violations = packaging.collect_release_files(root)
                self.assertEqual(violations[0]["types"], ["credentialed_database_url"])

    def test_another_secret_in_a_reviewed_fixture_still_blocks(self):
        with self.temporary() as temporary:
            root = Path(temporary)
            name = next(iter(packaging.REVIEWED_SYNTHETIC_URL_FIXTURES))
            destination = root / name
            destination.parent.mkdir(parents=True)
            destination.write_bytes((ROOT / name).read_bytes() + b"\nkey = 'sk-" + b"A" * 24 + b"'\n")
            _, _, violations = packaging.collect_release_files(root)
            self.assertIn("openai_key", violations[0]["types"])

    def test_exact_approved_gzip_is_included_without_changing_global_limit(self):
        self.assertEqual(packaging.MAX_INCLUDED_FILE_BYTES, 10 * 1024 * 1024)
        with self.temporary() as temporary:
            root = Path(temporary)
            destination = root / PLAN
            destination.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / PLAN, destination)
            included, _, violations = packaging.collect_release_files(root)
            self.assertEqual(violations, [])
            self.assertEqual(included, [destination])

    def test_changed_truncated_small_or_oversized_plan_is_blocked(self):
        original = (ROOT / PLAN).read_bytes()
        for content in [original[:-1], original + b"x", gzip.compress(b"not the approved plan"),
                        bytes([original[0] ^ 1]) + original[1:]]:
            with self.subTest(size=len(content)), self.temporary() as temporary:
                root = Path(temporary)
                destination = root / PLAN
                destination.parent.mkdir(parents=True)
                destination.write_bytes(content)
                with patch.object(packaging.gzip, "open", side_effect=AssertionError("Rejected before restoration")):
                    _, _, violations = packaging.collect_release_files(root)
                self.assertEqual(violations, [{"path": PLAN, "reason": "pinned_build_input_integrity"}])

    def test_approved_large_bytes_at_another_path_remain_blocked(self):
        with self.temporary() as temporary:
            root = Path(temporary)
            shutil.copyfile(ROOT / PLAN, root / "unexpected.gz")
            _, _, violations = packaging.collect_release_files(root)
            self.assertEqual(violations[0]["reason"], "unexpected_file_size")

    def test_restoration_checks_size_hash_bomb_limit_and_invalid_gzip(self):
        for result in [b"short", b"x" * 11, b"x" * 10, EOFError("synthetic truncation")]:
            with self.subTest(result_type=type(result).__name__):
                identity = {**packaging.PINNED_LARGE_BUILD_INPUTS[PLAN],
                            "restored_bytes": 10, "restored_sha256": hashlib.sha256(b"approved!!").hexdigest()}
                kwargs = {"side_effect": result} if isinstance(result, Exception) else {"return_value": io.BytesIO(result)}
                with patch.object(packaging.gzip, "open", **kwargs):
                    self.assertFalse(packaging._pinned_build_input_valid(ROOT / PLAN, identity))


if __name__ == "__main__":
    unittest.main()
