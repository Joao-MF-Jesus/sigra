from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from app.config import DatabaseSettings, load_database_settings


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

models = None
Base = None
create_database_engine = None
get_db = None
compare_databases = None
CANONICAL_SQLITE_PATH = None
decode_value = None
encode_value = None
sha256_file = None
export_sqlite_database = None
import_database_export = None
validate_database_export = None


def setUpModule():
    global models
    global Base, create_database_engine, get_db
    global compare_databases, CANONICAL_SQLITE_PATH
    global decode_value, encode_value, sha256_file
    global export_sqlite_database, import_database_export
    global validate_database_export

    from app import models as app_models
    from app.database import (
        Base as app_base,
        create_database_engine as engine_factory,
        get_db as database_dependency,
    )
    from compare_database_contents import compare_databases as compare
    from database_migration_common import (
        CANONICAL_SQLITE_PATH as canonical_path,
        decode_value as decode,
        encode_value as encode,
        sha256_file as file_hash,
    )
    from export_sqlite_data import export_sqlite_database as export_database
    from import_postgresql_data import import_database_export as import_database
    from validate_database_export import (
        validate_database_export as validate_export,
    )

    models = app_models
    Base = app_base
    create_database_engine = engine_factory
    get_db = database_dependency
    compare_databases = compare
    CANONICAL_SQLITE_PATH = canonical_path
    decode_value = decode
    encode_value = encode
    sha256_file = file_hash
    export_sqlite_database = export_database
    import_database_export = import_database
    validate_database_export = validate_export


def sqlite_settings(url: str = "sqlite:///:memory:") -> DatabaseSettings:
    return DatabaseSettings(
        url=url,
        environment="test",
        echo=False,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=1800,
        allow_sqlite_in_production=False,
    )


class DatabaseConfigurationTest(unittest.TestCase):
    def test_sqlite_is_default_only_for_development(self):
        settings = load_database_settings({})
        self.assertTrue(settings.is_sqlite)
        self.assertEqual(settings.environment, "development")
        self.assertTrue(settings.bootstrap_schema)

    def test_postgresql_url_is_normalized_to_psycopg(self):
        settings = load_database_settings(
            {
                "DATABASE_ENV": "integration",
                "DATABASE_URL": (
                    "postgresql://sigra:" + "secret@localhost/sigra"
                ),
            }
        )
        self.assertTrue(settings.is_postgresql)
        self.assertTrue(settings.url.startswith("postgresql+psycopg://"))
        self.assertNotIn("secret", settings.safe_url)

    def test_zero_pool_overflow_is_valid(self):
        settings = load_database_settings(
            {"DATABASE_MAX_OVERFLOW": "0"}
        )
        self.assertEqual(settings.max_overflow, 0)

    def test_production_rejects_sqlite_without_explicit_override(self):
        with self.assertRaises(RuntimeError):
            load_database_settings(
                {
                    "DATABASE_ENV": "production",
                    "DATABASE_URL": "sqlite:///:memory:",
                }
            )
        settings = load_database_settings(
            {
                "DATABASE_ENV": "production",
                "DATABASE_URL": "sqlite:///:memory:",
                "ALLOW_SQLITE_IN_PRODUCTION": "true",
            }
        )
        self.assertTrue(settings.is_sqlite)
        self.assertFalse(settings.bootstrap_schema)

    def test_invalid_database_configuration_is_rejected(self):
        for environment in ("unknown", "prod"):
            with self.subTest(environment=environment):
                with self.assertRaises(ValueError):
                    load_database_settings({"DATABASE_ENV": environment})
        with self.assertRaises(ValueError):
            load_database_settings({"DATABASE_URL": "mysql://localhost/sigra"})
        with self.assertRaises(ValueError):
            load_database_settings({"DATABASE_ECHO": "talvez"})

    def test_engine_identifies_sqlite_and_enables_foreign_keys(self):
        engine = create_database_engine(sqlite_settings())
        try:
            self.assertEqual(engine.dialect.name, "sqlite")
            with engine.connect() as connection:
                self.assertEqual(
                    connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one(),
                    1,
                )
        finally:
            engine.dispose()

    def test_engine_identifies_postgresql_without_opening_connection(self):
        settings = DatabaseSettings(
            url="postgresql+psycopg:///sigra_test",
            environment="integration",
            echo=False,
            pool_size=2,
            max_overflow=0,
            pool_timeout=5,
            pool_recycle=60,
            allow_sqlite_in_production=False,
        )
        engine = create_database_engine(settings)
        try:
            self.assertEqual(engine.dialect.name, "postgresql")
            self.assertEqual(engine.pool._max_overflow, 0)
        finally:
            engine.dispose()

    def test_session_dependency_rolls_back_and_closes_on_failure(self):
        fake_session = Mock()
        with patch("app.database.SessionLocal", return_value=fake_session):
            dependency = get_db()
            self.assertIs(next(dependency), fake_session)
            with self.assertRaises(RuntimeError):
                dependency.throw(RuntimeError("falha controlada"))
        fake_session.rollback.assert_called_once()
        fake_session.close.assert_called_once()


class PortableTypeContractTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_database_engine(sqlite_settings())
        Base.metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_money_is_returned_as_decimal(self):
        with Session(self.engine) as db:
            vehicle = models.Vehicle(
                brand="Teste",
                model="Numeric",
                year=2026,
                price=Decimal("123456.78"),
                fuel_efficiency_km_l=12,
                annual_maintenance_cost=Decimal("3456.70"),
                reliability_score=80,
                parts_availability_score=80,
                depreciation_rate=8,
                use_cases="cidade",
                chronic_issues="",
                image_url="",
                category="compact",
                segment_level=2,
                comfort_score=60,
                space_score=60,
                safety_score=60,
                urban_score=70,
                road_score=60,
                family_score=60,
                app_score=60,
                vehicle_type="car",
            )
            db.add(vehicle)
            db.commit()
            db.refresh(vehicle)
            self.assertIsInstance(vehicle.price, Decimal)
            self.assertEqual(vehicle.price, Decimal("123456.78"))

    def test_json_decimal_null_and_timezone_serialization(self):
        payload = {"ordem": ["a", "b"], "ativo": True}
        self.assertEqual(
            decode_value(encode_value("x", "json", payload)),
            payload,
        )
        decimal_value = encode_value("vehicles", "price", Decimal("10.20"))
        self.assertEqual(decode_value(decimal_value), Decimal("10.20"))
        self.assertIsNone(decode_value(None))
        aware = models.utc_now()
        self.assertEqual(aware.tzinfo, timezone.utc)


class ExportImportContractTest(unittest.TestCase):
    def test_canonical_export_counts_hashes_decimal_and_relations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "export"
            report = export_sqlite_database(
                CANONICAL_SQLITE_PATH,
                output,
            )
            validation = validate_database_export(output)
            manifest = json.loads(
                (output / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["counts"]["vehicles"], 34)
            self.assertEqual(report["counts"]["motorcycles"], 5)
            self.assertEqual(validation["status"], "valid")
            self.assertEqual(validation["orphan_references"], [])
            self.assertEqual(
                sha256_file(output / "vehicles.jsonl"),
                manifest["tables"]["vehicles"]["sha256"],
            )
            first_vehicle = json.loads(
                (output / "vehicles.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )
            self.assertEqual(first_vehicle["price"]["$type"], "decimal")

    def test_validator_rejects_negative_money_after_valid_checksum(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "export"
            export_sqlite_database(
                CANONICAL_SQLITE_PATH,
                output,
            )
            vehicle_path = output / "vehicles.jsonl"
            rows = [
                json.loads(line)
                for line in vehicle_path.read_text(encoding="utf-8").splitlines()
            ]
            rows[0]["price"] = {"$type": "decimal", "value": "-1.00"}
            vehicle_path.write_text(
                "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
                encoding="utf-8",
            )
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["tables"]["vehicles"]["sha256"] = sha256_file(vehicle_path)
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            validation = validate_database_export(output)
            self.assertEqual(validation["status"], "invalid")
            self.assertTrue(
                any(
                    "vehicles:1:price: valor monetario deve ser positivo" in error
                    for error in validation["errors"]
                )
            )

    def test_dry_run_import_and_equivalence_on_empty_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            output = directory / "export"
            target = directory / "target.db"
            export_report = export_sqlite_database(
                CANONICAL_SQLITE_PATH,
                output,
            )
            target_url = f"sqlite:///{target.as_posix()}"
            engine = create_engine(target_url)
            Base.metadata.create_all(engine)
            engine.dispose()

            dry_run = import_database_export(
                output,
                target_url,
                require_postgresql=False,
            )
            self.assertEqual(dry_run["status"], "dry-run")
            self.assertTrue(dry_run["destination_empty"])
            self.assertEqual(
                dry_run["transaction_strategy"],
                "single_transaction",
            )
            self.assertEqual(
                dry_run["rows_planned"],
                sum(export_report["counts"].values()),
            )

            imported = import_database_export(
                output,
                target_url,
                confirm_import=True,
                require_postgresql=False,
            )
            self.assertEqual(imported["status"], "imported")
            comparison = compare_databases(
                f"sqlite:///{CANONICAL_SQLITE_PATH.as_posix()}",
                target_url,
            )
            self.assertEqual(comparison["status"], "equivalent")
            self.assertEqual(comparison["value_differences"], [])
            self.assertEqual(
                comparison["source_rows"],
                comparison["target_rows"],
            )
            self.assertEqual(comparison["sequence_issues"], [])

    def test_non_empty_target_requires_two_explicit_confirmations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            output = directory / "export"
            target = directory / "target.db"
            export_sqlite_database(CANONICAL_SQLITE_PATH, output)
            target_url = f"sqlite:///{target.as_posix()}"
            engine = create_engine(target_url)
            Base.metadata.create_all(engine)
            with engine.begin() as connection:
                connection.execute(
                    models.User.__table__.insert(),
                    {"id": 99, "name": "Existente", "email": "x@example.com"},
                )
            engine.dispose()
            with self.assertRaisesRegex(ValueError, "Destino nao vazio"):
                import_database_export(
                    output,
                    target_url,
                    confirm_import=True,
                    require_postgresql=False,
                )
            with self.assertRaisesRegex(ValueError, "Destino nao vazio"):
                import_database_export(
                    output,
                    target_url,
                    confirm_import=True,
                    allow_non_empty_target=True,
                    require_postgresql=False,
                )

    def test_import_rolls_back_every_table_on_database_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            output = directory / "export"
            target = directory / "target.db"
            export_sqlite_database(CANONICAL_SQLITE_PATH, output)
            target_url = f"sqlite:///{target.as_posix()}"
            engine = create_engine(target_url)
            Base.metadata.create_all(engine)
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    """
                    CREATE TRIGGER fail_part_prices
                    BEFORE INSERT ON part_prices
                    BEGIN
                      SELECT RAISE(ABORT, 'falha controlada');
                    END
                    """
                )
            engine.dispose()

            with self.assertRaises(DatabaseError):
                import_database_export(
                    output,
                    target_url,
                    confirm_import=True,
                    require_postgresql=False,
                )
            engine = create_engine(target_url)
            try:
                with engine.connect() as connection:
                    for table in Base.metadata.sorted_tables:
                        self.assertEqual(
                            connection.execute(
                                text(f'SELECT COUNT(*) FROM "{table.name}"')
                            ).scalar_one(),
                            0,
                        )
            finally:
                engine.dispose()


class AlembicStructureTest(unittest.TestCase):
    def test_initial_revision_covers_current_tables_and_has_no_seed(self):
        revision = (
            PROJECT_ROOT
            / "backend"
            / "alembic"
            / "versions"
            / "20260723_0001_initial_schema.py"
        ).read_text(encoding="utf-8")
        for table_name in Base.metadata.tables:
            self.assertIn(f'"{table_name}"', revision)
        self.assertNotIn("ensure_seed_data", revision)
        self.assertNotIn("create_all", revision)

    def test_alembic_commands_are_portable_from_project_root(self):
        readme = (
            PROJECT_ROOT / "backend" / "alembic" / "README.md"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "python -m alembic -c backend/alembic.ini upgrade head",
            readme,
        )

    def test_postgresql_schema_validator_loads_model_metadata(self):
        validator = (
            PROJECT_ROOT / "scripts" / "validate_postgresql_schema.py"
        ).read_text(encoding="utf-8")
        self.assertIn("from app import models", validator)
        self.assertIn("Contrato de schema vazio", validator)

    def test_postgresql_importer_starts_from_project_root(self):
        result = subprocess.run(
            [
                sys.executable,
                str(
                    PROJECT_ROOT
                    / "scripts"
                    / "import_postgresql_data.py"
                ),
                "--help",
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_alembic_environment_uses_database_settings(self):
        env_source = (
            PROJECT_ROOT / "backend" / "alembic" / "env.py"
        ).read_text(encoding="utf-8")
        self.assertIn("load_database_settings()", env_source)
        self.assertNotIn("password=", env_source)

    def test_expected_head_matches_initial_revision(self):
        from app.database import EXPECTED_ALEMBIC_HEAD

        revision = (
            PROJECT_ROOT
            / "backend"
            / "alembic"
            / "versions"
            / "20260723_0001_initial_schema.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            f'revision: str = "{EXPECTED_ALEMBIC_HEAD}"',
            revision,
        )
