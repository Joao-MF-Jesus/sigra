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


def _database_url(
    *,
    username: str,
    password: str,
    host: str,
    database: str,
    scheme: str = "postgresql",
) -> str:
    authority_host = f"[{host}]" if ":" in host else host
    return (
        scheme
        + "://"
        + username
        + ":"
        + password
        + "@"
        + authority_host
        + "/"
        + database
    )


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

    def test_environment_templates_are_excluded_but_real_environment_file_blocks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(root / "README.md", "SIGRA\n")
            _write(root / ".env.example", "DATABASE_URL=configure-externally\n")
            _write(root / ".env.homologation.example", "PUBLIC_DEMO_MODE=true\n")
            _write(root / "frontend" / ".env.example", "VITE_API_URL=configure-externally\n")

            included, excluded_files, violations = collect_release_files(root)

            self.assertEqual(
                [path.relative_to(root).as_posix() for path in included],
                ["README.md"],
            )
            self.assertEqual(excluded_files, 3)
            self.assertEqual(violations, [])

            _write(root / ".env", "TOKEN=valor-real\n")
            _, _, violations = collect_release_files(root)
            self.assertIn(
                {"path": ".env", "reason": "forbidden_environment_file"},
                violations,
            )

    def test_real_secret_and_remote_credentialed_url_remain_blocking(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(root / "README.md", "SIGRA\n")
            _write(root / "secrets.txt", "sk-" + "A" * 24 + "\n")
            _write(
                root / "docs" / "remote.md",
                _database_url(
                    username="operator",
                    password="real-password",
                    host="database.example.com",
                    database="sigra",
                ),
            )

            _, _, violations = collect_release_files(root)
            by_path = {item["path"]: item for item in violations}
            self.assertEqual(by_path["secrets.txt"]["reason"], "possible_secret")
            self.assertIn("openai_key", by_path["secrets.txt"]["types"])
            self.assertEqual(by_path["docs/remote.md"]["reason"], "possible_secret")
            self.assertIn(
                "credentialed_database_url",
                by_path["docs/remote.md"]["types"],
            )

    def test_synthetic_database_fixture_requires_every_restriction(self):
        cases = (
            (
                "data_platform/tests/test_safe_fixture.py",
                "127.0.0.1",
                "sigra_fixture_test",
                "synthetic-user",
                "synthetic-secret",
                True,
            ),
            (
                "docs/test_safe_fixture.py",
                "127.0.0.1",
                "sigra_fixture_test",
                "synthetic-user",
                "synthetic-secret",
                False,
            ),
            (
                "data_platform/tests/test_remote_fixture.py",
                "database.example.com",
                "sigra_fixture_test",
                "synthetic-user",
                "synthetic-secret",
                False,
            ),
            (
                "data_platform/tests/test_wrong_database.py",
                "localhost",
                "sigra_fixture",
                "synthetic-user",
                "synthetic-secret",
                False,
            ),
            (
                "data_platform/tests/test_real_credentials.py",
                "::1",
                "sigra_fixture_test",
                "operator",
                "real-password",
                False,
            ),
            (
                "data_platform/tests/test_marker_substring.py",
                "localhost",
                "sigra_fixture_test",
                "contest-user",
                "protest-password",
                False,
            ),
        )
        for relative, host, database, username, password, accepted in cases:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                fixture = root / relative
                _write(
                    fixture,
                    _database_url(
                        username=username,
                        password=password,
                        host=host,
                        database=database,
                    ),
                )

                included, _, violations = collect_release_files(root)
                included_paths = {
                    path.relative_to(root).as_posix() for path in included
                }
                if accepted:
                    self.assertIn(relative, included_paths)
                    self.assertEqual(violations, [])
                else:
                    self.assertNotIn(relative, included_paths)
                    self.assertEqual(violations[0]["path"], relative)
                    self.assertIn(
                        "credentialed_database_url",
                        violations[0]["types"],
                    )

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

    def test_package_contains_no_environment_file_or_operational_secret(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(root / "README.md", "SIGRA\n")
            _write(root / ".env.example", "DATABASE_URL=configure-externally\n")
            _write(root / ".env.homologation.example", "PUBLIC_DEMO_MODE=true\n")
            _write(root / "frontend" / ".env.example", "VITE_API_URL=configure-externally\n")
            fixture = root / "data_platform" / "tests" / "test_safe_fixture.py"
            _write(
                fixture,
                _database_url(
                    username="synthetic-user",
                    password="synthetic-secret",
                    host="localhost",
                    database="sigra_fixture_test",
                ),
            )

            output = root / "dist" / "technical" / "sigra.zip"
            result = build_release_package(
                root=root,
                output=output,
                release_type="technical",
            )

            self.assertFalse(result.report["contains_secrets"])
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
                self.assertFalse(
                    any(
                        Path(name).name == ".env"
                        or Path(name).name.startswith(".env.")
                        for name in names
                    )
                )
                self.assertIn(
                    "data_platform/tests/test_safe_fixture.py",
                    names,
                )


if __name__ == "__main__":
    unittest.main()
