import hashlib
import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts.release_packaging import build_release_package, collect_release_files


def _write(path: Path, content: str = "conteudo\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class ReleasePackagingCollectionTest(unittest.TestCase):
    def test_git_repository_includes_only_valid_tracked_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            _write(root / "README.md", "SIGRA\n")
            _write(root / "backend" / "app.py", "print('sigra')\n")
            _write(root / "untracked.txt")
            subprocess.run(
                ["git", "-C", str(root), "add", "README.md", "backend/app.py"],
                check=True,
            )

            included, _, violations = collect_release_files(root)

            relative = [path.relative_to(root).as_posix() for path in included]
            self.assertEqual(relative, ["README.md", "backend/app.py"])
            self.assertNotIn("untracked.txt", relative)
            self.assertEqual(violations, [])

    def test_git_repository_still_excludes_forced_blocked_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            _write(root / "README.md", "SIGRA\n")
            _write(root / "backend" / "sigra.db", "database")
            _write(root / "frontend" / "node_modules" / "package" / "index.js")
            _write(root / ".npm-cache" / "cache.bin")
            _write(root / "__pycache__" / "module.pyc")
            _write(root / "previous.zip", "archive")
            subprocess.run(
                ["git", "-C", str(root), "add", "-f", "."],
                check=True,
            )

            included, excluded_files, violations = collect_release_files(root)

            relative = [path.relative_to(root).as_posix() for path in included]
            self.assertEqual(relative, ["README.md"])
            self.assertEqual(excluded_files, 5)
            self.assertEqual(violations, [])

    def test_fallback_prunes_ignored_directories_before_descending(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(root / "README.md", "SIGRA\n")
            _write(root / "node_modules" / "package" / "dependency.js")
            _write(root / ".venv-validation" / "Lib" / "secret.py")
            _write(root / "tmp" / "nested" / "trace.txt")
            real_walk = os.walk
            root_directories_after_yield = []

            def guarded_walk(*args, **kwargs):
                for current, dirnames, filenames in real_walk(*args, **kwargs):
                    yield current, dirnames, filenames
                    if Path(current) == root:
                        root_directories_after_yield.extend(dirnames)

            with patch(
                "scripts.release_packaging.os.walk",
                side_effect=guarded_walk,
            ):
                included, _, violations = collect_release_files(root)

            self.assertEqual(
                [path.relative_to(root).as_posix() for path in included],
                ["README.md"],
            )
            self.assertNotIn("node_modules", root_directories_after_yield)
            self.assertNotIn(".venv-validation", root_directories_after_yield)
            self.assertNotIn("tmp", root_directories_after_yield)
            self.assertEqual(violations, [])

    def test_fallback_excludes_databases_caches_dependencies_and_archives(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(root / "README.md", "SIGRA\n")
            _write(root / "backend" / "sigra.db", "database")
            _write(root / "frontend" / "node_modules" / "package" / "index.js")
            _write(root / ".npm-cache" / "cache.bin")
            _write(root / "__pycache__" / "module.pyc")
            _write(root / "previous.zip", "archive")

            included, _, violations = collect_release_files(root)

            relative = [path.relative_to(root).as_posix() for path in included]
            self.assertEqual(relative, ["README.md"])
            self.assertEqual(violations, [])

    def test_fallback_build_preserves_manifest_and_sha256_contract(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(root / "README.md", "SIGRA\n")
            _write(root / "src" / "app.py", "print('sigra')\n")
            output = root / "dist" / "technical" / "sigra.zip"

            result = build_release_package(
                root=root,
                output=output,
                release_type="technical",
            )

            expected_archive_hash = hashlib.sha256(output.read_bytes()).hexdigest()
            self.assertEqual(result.report["sha256"], expected_archive_hash)
            self.assertEqual(
                result.checksum_path.read_text(encoding="ascii"),
                f"{expected_archive_hash}  {output.name}\n",
            )
            with zipfile.ZipFile(output) as archive:
                manifest = json.loads(archive.read("MANIFEST.json"))
                names = archive.namelist()
                self.assertEqual(
                    manifest["included_files"],
                    len(manifest["files"]) + 2,
                )
                self.assertEqual(manifest["included_files"], len(names))
                for entry in manifest["files"]:
                    self.assertEqual(
                        entry["sha256"],
                        hashlib.sha256(archive.read(entry["path"])).hexdigest(),
                    )


if __name__ == "__main__":
    unittest.main()
