import copy
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

from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.tests.test_motorcycle_schema_v03 import canonical_payload


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEED_SCRIPT = PROJECT_ROOT / "scripts" / "seed_motorcycles.py"


class MotorcycleMaintenanceOptionalTest(unittest.TestCase):
    def setUp(self):
        from app import models  # noqa: F401
        from app.database import Base

        self.engine = create_engine("sqlite:///:memory:")
        with self.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_create_serialization_and_update_preserve_missing_zero_and_positive(self):
        from app.repository import create_motorcycle, motorcycle_to_response, update_motorcycle
        from app.schemas import MotorcycleCreate, MotorcycleRead, MotorcycleUpdate

        payload_data = canonical_payload()
        payload_data.pop("annual_maintenance_cost", None)
        payload = MotorcycleCreate.model_validate(payload_data)
        self.assertIsNone(payload.annual_maintenance_cost)

        with Session(self.engine) as db:
            created = create_motorcycle(db, payload)
            self.assertIsNone(created["annual_maintenance_cost"])
            response = motorcycle_to_response(created)
            self.assertIsNone(response["annual_maintenance_cost"])
            self.assertIsNone(MotorcycleRead.model_validate(response).annual_maintenance_cost)

            zero = update_motorcycle(
                db,
                created,
                MotorcycleUpdate.model_validate({"annual_maintenance_cost": 0}),
            )
            self.assertEqual(zero["annual_maintenance_cost"], 0)
            positive = update_motorcycle(
                db,
                zero,
                MotorcycleUpdate.model_validate({"annual_maintenance_cost": 2500}),
            )
            self.assertEqual(positive["annual_maintenance_cost"], 2500)
            missing_again = update_motorcycle(
                db,
                positive,
                MotorcycleUpdate.model_validate({"annual_maintenance_cost": None}),
            )
            self.assertIsNone(missing_again["annual_maintenance_cost"])

    def test_negative_nan_and_infinity_are_rejected(self):
        from app.schemas import MotorcycleCreate, MotorcycleUpdate

        for value in (-1, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                MotorcycleCreate.model_validate(
                    {**canonical_payload(), "annual_maintenance_cost": value}
                )
            with self.subTest(update=value), self.assertRaises(ValidationError):
                MotorcycleUpdate.model_validate({"annual_maintenance_cost": value})


class MotorcycleCoverageV031Test(unittest.TestCase):
    def test_maintenance_is_complementary_and_readiness_is_not_a_score(self):
        from app.motorcycle_eligibility import evaluate_motorcycle_eligibility

        payload = canonical_payload()
        payload["annual_maintenance_cost"] = None
        payload["data_sources"] = [
            source for source in payload["data_sources"]
            if source["data_group"] != "maintenance"
        ]
        payload["economic_estimates"] = []
        result = evaluate_motorcycle_eligibility(payload)
        coverage = result["coverage"]
        self.assertEqual(result["eligibility_status"], "eligible")
        self.assertEqual(coverage["pilot_required_source_coverage_percent"], 100)
        self.assertIn("maintenance", coverage["missing_complementary_source_groups"])
        self.assertEqual(coverage["future_recommendation_readiness"], "missing_economic_data")
        self.assertNotIn("score", coverage)


class MotorcycleDemoNormalizationTest(unittest.TestCase):
    def test_normalize_demo_requires_confirmation_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "demo.db"
            environment = {
                **os.environ,
                "DATABASE_URL": f"sqlite:///{database_path.as_posix()}",
                "FIPE_AUTO_REFRESH": "false",
            }
            insert = subprocess.run(
                [sys.executable, str(SEED_SCRIPT), "insert"],
                cwd=PROJECT_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(insert.returncode, 0, insert.stderr)
            with closing(sqlite3.connect(database_path)) as connection:
                motorcycle_id = connection.execute(
                    "SELECT id FROM motorcycles WHERE brand = 'Honda' AND model = 'CB 300F Twister'"
                ).fetchone()[0]
                connection.execute(
                    "UPDATE motorcycles SET model = 'CB 300F Teste', source_name = 'Fabricante Exemplo' WHERE id = ?",
                    (motorcycle_id,),
                )
                connection.execute(
                    "UPDATE motorcycle_data_sources SET source_type = 'official', source_name = 'Fabricante Exemplo' WHERE motorcycle_id = ?",
                    (motorcycle_id,),
                )
                connection.commit()

            dry_run = subprocess.run(
                [sys.executable, str(SEED_SCRIPT), "normalize-demo", "--dry-run"],
                cwd=PROJECT_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
            self.assertIn('"mode": "dry-run"', dry_run.stdout)
            with closing(sqlite3.connect(database_path)) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT model FROM motorcycles WHERE id = ?", (motorcycle_id,)
                    ).fetchone()[0],
                    "CB 300F Teste",
                )

            applied = subprocess.run(
                [sys.executable, str(SEED_SCRIPT), "normalize-demo", "--confirm-normalization"],
                cwd=PROJECT_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(applied.returncode, 0, applied.stderr)
            with closing(sqlite3.connect(database_path)) as connection:
                row = connection.execute(
                    "SELECT model, source_name FROM motorcycles WHERE id = ?", (motorcycle_id,)
                ).fetchone()
                self.assertEqual(row, ("CB 300F Twister", "Base demonstrativa SIGRA"))

            repeated = subprocess.run(
                [sys.executable, str(SEED_SCRIPT), "normalize-demo", "--dry-run"],
                cwd=PROJECT_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertIn('"changes": []', repeated.stdout)


class ReleasePackagingTest(unittest.TestCase):
    def test_academic_package_excludes_database_and_nested_zip_and_generates_hash(self):
        from scripts.release_packaging import build_release_package

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "NOTICE.md").write_text("Autoria acadêmica.\n", encoding="utf-8")
            (root / "ACADEMIC_RELEASE.md").write_text("Release controlada.\n", encoding="utf-8")
            (root / "README.md").write_text("SIGRA\n", encoding="utf-8")
            (root / "backend").mkdir()
            (root / "backend" / "app.py").write_text("print('sigra')\n", encoding="utf-8")
            (root / "backend" / "sigra.db").write_bytes(b"database")
            validation_environment = root / ".venv-validation"
            validation_environment.mkdir()
            (validation_environment / "dependency.py").write_text(
                "url = 'postgresql://user:' + 'password' + '@localhost/example'\n",
                encoding="utf-8",
            )
            npm_cache = root / ".npm-cache-validation"
            npm_cache.mkdir()
            (npm_cache / "cache.bin").write_bytes(b"cache")
            (root / "old.zip").write_bytes(b"archive")
            output = root / "dist" / "academic" / "sigra.zip"
            result = build_release_package(root=root, output=output, release_type="academic")

            self.assertTrue(result.archive.is_file())
            self.assertEqual(hashlib.sha256(result.archive.read_bytes()).hexdigest(), result.report["sha256"])
            self.assertFalse(result.report["contains_database"])
            self.assertFalse(result.report["contains_secrets"])
            with zipfile.ZipFile(result.archive) as archive:
                names = archive.namelist()
                self.assertIn("NOTICE.md", names)
                self.assertIn("MANIFEST.json", names)
                self.assertFalse(any(name.endswith((".db", ".zip")) for name in names))
                self.assertFalse(
                    any(name.startswith(".venv-validation/") for name in names)
                )
                self.assertFalse(
                    any(name.startswith(".npm-cache-validation/") for name in names)
                )

    def test_environment_file_and_secret_are_blocking(self):
        from scripts.release_packaging import ReleaseValidationError, build_release_package

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "NOTICE.md").write_text("Autoria.\n", encoding="utf-8")
            (root / "ACADEMIC_RELEASE.md").write_text("Release.\n", encoding="utf-8")
            (root / ".env").write_text("TOKEN=valor-real\n", encoding="utf-8")
            with self.assertRaises(ReleaseValidationError):
                build_release_package(
                    root=root,
                    output=root / "dist" / "academic" / "sigra.zip",
                    release_type="academic",
                )


class DatabaseDiagnosticTest(unittest.TestCase):
    def test_password_is_masked_and_duplicate_candidates_are_found(self):
        from scripts.check_database_configuration import (
            find_sqlite_candidates,
            sanitized_database_url,
        )

        example_url = "postgresql+psycopg://sigra:" + "segredo" + "@localhost/sigra"
        masked = sanitized_database_url(example_url)
        self.assertNotIn("segredo", masked)
        self.assertIn("***", masked)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "sigra.db").write_bytes(b"")
            (root / "backend").mkdir()
            (root / "backend" / "sigra.db").write_bytes(b"")
            self.assertEqual(len(find_sqlite_candidates(root)), 2)


class MotorcycleApiCanonicalV031Test(unittest.TestCase):
    def test_openapi_response_is_canonical(self):
        from app.main import app

        schema = app.openapi()["components"]["schemas"]["MotorcycleRead"]["properties"]
        for field in (
            "data_source",
            "source_reference",
            "source_url",
            "reliability_score",
            "parts_availability_score",
            "depreciation_rate",
        ):
            self.assertNotIn(field, schema)
        self.assertIn("legacy_data", schema)
