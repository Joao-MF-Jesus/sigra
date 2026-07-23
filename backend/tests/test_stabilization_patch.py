import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEED_SCRIPT = PROJECT_ROOT / "scripts" / "seed_motorcycles.py"
EXPECTED_DEMO_IDENTITIES = {
    ("Honda", "CG 160 Fan", 2025),
    ("Yamaha", "NMax 160 ABS", 2025),
    ("Royal Enfield", "Himalayan 450", 2025),
    ("Honda", "CB 300F Twister", 2025),
}


def isolated_environment(database_path: Path) -> dict:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.casefold() != "pythonpath"
    }
    environment.update(
        {
            "DATABASE_URL": f"sqlite:///{database_path.as_posix()}",
            "FIPE_AUTO_REFRESH": "false",
        }
    )
    return environment


def run_seed(database_path: Path, *arguments: str, cwd: Path = PROJECT_ROOT):
    return subprocess.run(
        [sys.executable, str(SEED_SCRIPT), *arguments],
        cwd=cwd,
        env=isolated_environment(database_path),
        capture_output=True,
        text=True,
        timeout=90,
    )


class ScriptPortabilityTest(unittest.TestCase):
    def test_seed_runs_from_root_without_pythonpath(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "root.db"
            result = run_seed(database_path, "--rebuild-demo", "--dry-run")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"canonical_seed_count": 4', result.stdout)

    def test_seed_runs_from_another_directory_without_pythonpath(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            database_path = directory / "other-cwd.db"
            result = run_seed(
                database_path,
                "--rebuild-demo",
                "--dry-run",
                cwd=directory,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_seed_runs_as_module_without_duplicate_backend_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "module.db"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.seed_motorcycles",
                    "--rebuild-demo",
                    "--dry-run",
                ],
                cwd=PROJECT_ROOT,
                env=isolated_environment(database_path),
                capture_output=True,
                text=True,
                timeout=90,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_official_command_is_documented_without_pythonpath(self):
        expected = "python -m unittest discover -s backend/tests -t backend -v"
        workflow = (PROJECT_ROOT / ".github" / "workflows" / "quality.yml").read_text(
            encoding="utf-8"
        )
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(expected, workflow)
        self.assertIn(expected, readme)
        self.assertNotIn("PYTHONPATH=backend python -m unittest", workflow)


class DemonstrationSeedRebuildTest(unittest.TestCase):
    def _prepare_database(self, database_path: Path) -> None:
        code = (
            "import sys;"
            f"sys.path.insert(0,{str(PROJECT_ROOT / 'backend')!r});"
            "from app.database import create_database,SessionLocal;"
            "from app.repository import ensure_seed_data;"
            "create_database();"
            "db=SessionLocal();ensure_seed_data(db);db.close()"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=PROJECT_ROOT,
            env=isolated_environment(database_path),
            capture_output=True,
            text=True,
            timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        inserted = run_seed(database_path, "insert")
        self.assertEqual(inserted.returncode, 0, inserted.stderr)
        with closing(sqlite3.connect(database_path)) as connection:
            connection.execute(
                """
                INSERT INTO motorcycles (
                    brand, model, year, price, city_consumption, road_consumption,
                    vehicle_type, image_url, is_demonstration
                ) VALUES (?, ?, ?, ?, ?, ?, 'motorcycle', '', 0)
                """,
                ("Honda", "CB 300F", 2025, 24000, 30, 34),
            )
            connection.commit()

    def test_dry_run_does_not_modify_database_and_reports_relations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "dry-run.db"
            inserted = run_seed(database_path, "insert")
            self.assertEqual(inserted.returncode, 0, inserted.stderr)
            before = database_path.read_bytes()
            result = run_seed(database_path, "--rebuild-demo", "--dry-run")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"database_modified": false', result.stdout)
            self.assertIn('"related_totals"', result.stdout)
            self.assertEqual(database_path.read_bytes(), before)

    def test_rebuild_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "confirmation.db"
            result = run_seed(database_path, "--rebuild-demo")
            self.assertEqual(result.returncode, 0, result.stderr)
            with closing(sqlite3.connect(database_path)) as connection:
                count = connection.execute("SELECT COUNT(*) FROM motorcycles").fetchone()[0]
            self.assertEqual(count, 0)

    def test_rebuild_is_idempotent_and_preserves_cars_and_real_motorcycle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "rebuild.db"
            self._prepare_database(database_path)

            for _ in range(2):
                result = run_seed(database_path, "--rebuild-demo", "--confirm")
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual(report["real_motorcycles_before"], 1)
                self.assertEqual(report["real_motorcycles_after"], 1)

            with closing(sqlite3.connect(database_path)) as connection:
                cars = connection.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0]
                demo_rows = set(
                    connection.execute(
                        """
                        SELECT brand, model, year
                        FROM motorcycles
                        WHERE is_demonstration = 1 OR data_source = 'demonstration'
                        """
                    ).fetchall()
                )
                real_rows = connection.execute(
                    """
                    SELECT brand, model, year
                    FROM motorcycles
                    WHERE is_demonstration = 0
                      AND (data_source IS NULL OR data_source != 'demonstration')
                    """
                ).fetchall()
                duplicate_primary_sources = connection.execute(
                    """
                    SELECT motorcycle_id, data_group, COUNT(*)
                    FROM motorcycle_data_sources
                    WHERE is_primary = 1
                    GROUP BY motorcycle_id, data_group
                    HAVING COUNT(*) > 1
                    """
                ).fetchall()
            self.assertEqual(cars, 34)
            self.assertEqual(demo_rows, EXPECTED_DEMO_IDENTITIES)
            self.assertEqual(real_rows, [("Honda", "CB 300F", 2025)])
            self.assertEqual(duplicate_primary_sources, [])
            backups = list((database_path.parent / "backups").glob("pre_demo_rebuild_*.db"))
            self.assertEqual(len(backups), 2)

    def test_rebuild_rolls_back_all_changes_when_insertion_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "rollback.db"
            inserted = run_seed(database_path, "insert")
            self.assertEqual(inserted.returncode, 0, inserted.stderr)
            code = f"""
import sys
sys.path.insert(0, {str(PROJECT_ROOT)!r})
import scripts.seed_motorcycles as seed
seed.create_database()
calls = 0
def failing_create(db, payload, commit=False):
    global calls
    calls += 1
    if calls == 2:
        raise RuntimeError("falha controlada")
    return seed.create_motorcycle(db, payload, commit=commit)
try:
    seed.rebuild_demonstration_records(persist=True, create_record=failing_create)
except RuntimeError:
    pass
else:
    raise SystemExit("a falha controlada nao ocorreu")
with seed.SessionLocal() as db:
    identities = {{(item.brand, item.model, item.year) for item in db.query(seed.models.Motorcycle).all()}}
if identities != {EXPECTED_DEMO_IDENTITIES!r}:
    raise SystemExit(f"rollback incompleto: {{identities}}")
"""
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=PROJECT_ROOT,
                env=isolated_environment(database_path),
                capture_output=True,
                text=True,
                timeout=90,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


class DatabaseAndCleanupTest(unittest.TestCase):
    def test_database_candidate_classification_is_explicit(self):
        from scripts.check_database_configuration import (
            classify_sqlite_candidate,
            find_sqlite_candidates,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "backend").mkdir()
            (root / "tmp").mkdir()
            canonical = root / "backend" / "sigra.db"
            legacy = root / "sigra.db"
            temporary = root / "tmp" / "sigra-e2e-test.db"
            for path in (canonical, legacy, temporary):
                path.write_bytes(b"")
            self.assertEqual(classify_sqlite_candidate(canonical, root), "canonical")
            self.assertEqual(classify_sqlite_candidate(legacy, root), "legacy_root")
            self.assertEqual(classify_sqlite_candidate(temporary, root), "temporary")
            self.assertEqual(len(find_sqlite_candidates(root)), 3)

    def test_cleanup_dry_run_and_confirm_preserve_protected_items(self):
        from scripts.clean_workspace import clean_workspace

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "backend").mkdir()
            canonical = root / "backend" / "sigra.db"
            canonical.write_bytes(b"canonical")
            source = root / "app.py"
            source.write_text("print('preservado')\n", encoding="utf-8")
            cache = root / "__pycache__"
            cache.mkdir()
            (cache / "module.pyc").write_bytes(b"cache")
            temporary = root / "tmp" / "sigra-e2e-test.db"
            temporary.parent.mkdir()
            temporary.write_bytes(b"temporary")
            temporary_backup = root / "tmp" / "backups" / "pre_demo_rebuild.db"
            temporary_backup.parent.mkdir()
            temporary_backup.write_bytes(b"backup")
            dependencies = root / "node_modules"
            dependencies.mkdir()
            (dependencies / "package.txt").write_text("preservado", encoding="utf-8")

            dry_run = clean_workspace(root)
            self.assertEqual(dry_run["mode"], "dry-run")
            self.assertTrue(cache.exists())
            self.assertTrue(temporary.exists())

            applied = clean_workspace(root, confirm=True)
            self.assertEqual(applied["mode"], "apply")
            self.assertFalse(cache.exists())
            self.assertFalse(temporary.exists())
            self.assertTrue(canonical.exists())
            self.assertTrue(source.exists())
            self.assertTrue(dependencies.exists())
            self.assertTrue(temporary_backup.exists())

    def test_cleanup_preserves_latest_backup_without_explicit_flag(self):
        from scripts.clean_workspace import scan_workspace

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backups = root / "backend" / "backups"
            backups.mkdir(parents=True)
            older = backups / "pre_demo_rebuild_old.db"
            latest = backups / "pre_demo_rebuild_new.db"
            older.write_bytes(b"old")
            latest.write_bytes(b"new")
            os.utime(older, (1, 1))
            os.utime(latest, (2, 2))

            report = scan_workspace(root, include_backups=True)
            by_path = {item["path"]: item for item in report["items"]}
            self.assertTrue(
                by_path["backend/backups/pre_demo_rebuild_old.db"][
                    "selected_for_removal"
                ]
            )
            self.assertFalse(
                by_path["backend/backups/pre_demo_rebuild_new.db"][
                    "selected_for_removal"
                ]
            )

    def test_cleanup_requires_specific_flag_and_backs_up_legacy_root_database(self):
        from scripts.clean_workspace import clean_workspace, scan_workspace

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "backend").mkdir()
            canonical = root / "backend" / "sigra.db"
            legacy = root / "sigra.db"
            canonical.write_bytes(b"canonical")
            legacy.write_bytes(b"legacy-database")

            default_report = scan_workspace(root)
            by_path = {item["path"]: item for item in default_report["items"]}
            self.assertEqual(
                by_path["sigra.db"]["kind"], "legacy_root_database"
            )
            self.assertFalse(by_path["sigra.db"]["selected_for_removal"])

            explicit_dry_run = scan_workspace(
                root, include_legacy_databases=True
            )
            by_path = {item["path"]: item for item in explicit_dry_run["items"]}
            self.assertTrue(by_path["sigra.db"]["selected_for_removal"])
            self.assertTrue(legacy.exists())

            applied = clean_workspace(
                root,
                confirm=True,
                include_legacy_databases=True,
            )
            self.assertFalse(legacy.exists())
            self.assertTrue(canonical.exists())
            backup = applied["legacy_database_backups"][0]
            self.assertTrue(backup["backup_created"])
            backup_path = Path(backup["backup_path"])
            self.assertTrue(backup_path.exists())
            self.assertEqual(
                hashlib.sha256(backup_path.read_bytes()).hexdigest(),
                backup["sha256"],
            )

    def test_cleanup_does_not_backup_empty_legacy_database(self):
        from scripts.clean_workspace import clean_workspace

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "backend").mkdir()
            (root / "backend" / "sigra.db").write_bytes(b"canonical")
            legacy = root / "sigra.db"
            legacy.write_bytes(b"")

            applied = clean_workspace(
                root,
                confirm=True,
                include_legacy_databases=True,
            )
            self.assertFalse(legacy.exists())
            backup = applied["legacy_database_backups"][0]
            self.assertFalse(backup["backup_created"])
            self.assertIsNone(backup["backup_path"])


class DemonstrationDataContractTest(unittest.TestCase):
    def test_canonical_seed_has_four_distinct_demonstration_models(self):
        records = json.loads(
            (PROJECT_ROOT / "backend" / "data" / "motorcycles.demo.json").read_text(
                encoding="utf-8"
            )
        )
        identities = {(item["brand"], item["model"], item["year"]) for item in records}
        self.assertEqual(identities, EXPECTED_DEMO_IDENTITIES)
        self.assertEqual(len(records), 4)
        for item in records:
            self.assertEqual(item["data_source"], "demonstration")
            self.assertTrue(item["is_demonstration"])
            self.assertEqual(item["source_name"], "Base demonstrativa SIGRA")
            self.assertNotIn("oficial", item["source_name"].casefold())


class StabilizedReleaseTest(unittest.TestCase):
    def test_technical_release_contains_seed_and_versioned_manifest_only(self):
        from scripts.release_packaging import build_release_package

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seed_path = root / "backend" / "data" / "motorcycles.demo.json"
            seed_path.parent.mkdir(parents=True)
            seed_path.write_text("[]\n", encoding="utf-8")
            (root / "backend" / "sigra.db").write_bytes(b"database")
            dependencies = root / "frontend" / "node_modules"
            dependencies.mkdir(parents=True)
            (dependencies / "package.txt").write_text("dependency", encoding="utf-8")
            (root / "old.zip").write_bytes(b"archive")

            result = build_release_package(
                root=root,
                output=root / "dist" / "technical" / "sigra.zip",
                release_type="technical",
            )
            self.assertEqual(
                hashlib.sha256(result.archive.read_bytes()).hexdigest(),
                result.report["sha256"],
            )
            self.assertEqual(result.report["stabilization_build"], "2026.07.1")
            with zipfile.ZipFile(result.archive) as archive:
                names = archive.namelist()
                self.assertIn("backend/data/motorcycles.demo.json", names)
                self.assertFalse(any(name.endswith((".db", ".zip")) for name in names))
                self.assertFalse(any("node_modules" in name for name in names))
                metadata = json.loads(archive.read("RELEASE_METADATA.json"))
            self.assertEqual(metadata["functional_versions"]["cars_algorithm"], "2.1.2")
            self.assertEqual(metadata["functional_versions"]["cars_weights"], "cars-v1")
            self.assertIsNone(
                metadata["functional_versions"]["motorcycles_algorithm"]
            )


if __name__ == "__main__":
    unittest.main()
