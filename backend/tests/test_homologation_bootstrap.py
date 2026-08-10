import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

class HomologationBootstrapTest(unittest.TestCase):
    def setUp(self):
        from app import models
        from app.database import Base, EXPECTED_ALEMBIC_HEAD
        from scripts.bootstrap_homologation_data import (
            BOOTSTRAP_VERSION,
            bootstrap_homologation_data,
            database_target,
        )

        self.models = models
        self.bootstrap_version = BOOTSTRAP_VERSION
        self.bootstrap_homologation_data = bootstrap_homologation_data
        self.database_target = database_target
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
            )
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
                {"revision": EXPECTED_ALEMBIC_HEAD},
            )
        self.session_factory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
        )

    def tearDown(self):
        self.engine.dispose()

    def test_dry_run_reports_plan_without_modifying_database(self):
        report = self.bootstrap_homologation_data(
            self.engine,
            self.session_factory,
            require_postgresql=False,
        )
        self.assertEqual(report["status"], "ready")
        self.assertFalse(report["database_modified"])
        with self.session_factory() as db:
            self.assertEqual(db.query(self.models.Vehicle).count(), 0)
            self.assertIsNone(
                db.get(
                    self.models.SigraSchemaMigration,
                    self.bootstrap_version,
                )
            )

    def test_confirmed_bootstrap_is_idempotent_and_validated(self):
        first = self.bootstrap_homologation_data(
            self.engine,
            self.session_factory,
            confirm=True,
            require_postgresql=False,
        )
        second = self.bootstrap_homologation_data(
            self.engine,
            self.session_factory,
            confirm=True,
            require_postgresql=False,
        )

        self.assertEqual(first["status"], "applied")
        self.assertTrue(first["database_modified"])
        self.assertEqual(second["status"], "already_applied")
        self.assertFalse(second["database_modified"])
        self.assertEqual(first["table_counts"], second["table_counts"])
        self.assertEqual(first["orphan_references"], [])
        self.assertEqual(second["validation_issues"], [])
        with self.session_factory() as db:
            self.assertEqual(db.query(self.models.Vehicle).count(), 34)
            self.assertEqual(db.query(self.models.Motorcycle).count(), 4)

    def test_nonempty_unmarked_database_is_refused(self):
        with self.session_factory() as db:
            db.add(
                self.models.User(
                    name="Registro existente",
                    email="existing@example.test",
                )
            )
            db.commit()

        with self.assertRaisesRegex(ValueError, "possui dados sem o marcador"):
            self.bootstrap_homologation_data(
                self.engine,
                self.session_factory,
                confirm=True,
                require_postgresql=False,
            )

    def test_missing_migration_is_refused(self):
        with self.engine.begin() as connection:
            connection.execute(text("DELETE FROM alembic_version"))
        with self.assertRaisesRegex(ValueError, "Alembic head"):
            self.bootstrap_homologation_data(
                self.engine,
                self.session_factory,
                require_postgresql=False,
            )

    def test_database_target_never_contains_user_or_password(self):
        target = self.database_target(
            "postgresql+psycopg://sigra:"
            + "secret@db.example.test:5432/postgres"
        )
        self.assertEqual(
            target,
            {
                "dialect": "postgresql",
                "host": "db.example.test",
                "port": 5432,
                "database": "postgres",
            },
        )
        self.assertNotIn("secret", str(target))


class HomologationManifestTest(unittest.TestCase):
    def test_manifests_do_not_embed_credentials_or_enable_automatic_deploy(self):
        render = (PROJECT_ROOT / "render.yaml").read_text(encoding="utf-8")
        vercel = (PROJECT_ROOT / "frontend" / "vercel.json").read_text(
            encoding="utf-8"
        )
        homologation_env = (
            PROJECT_ROOT / ".env.homologation.example"
        ).read_text(encoding="utf-8")

        self.assertIn("autoDeployTrigger: off", render)
        self.assertIn("sync: false", render)
        self.assertIn("PUBLIC_DEMO_MODE", render)
        self.assertIn('"outputDirectory": "dist"', vercel)
        self.assertIn("DATABASE_URL=SET_IN_RENDER_SECRET_STORE", homologation_env)
        self.assertIn(
            "MIGRATION_DATABASE_URL=SET_ONLY_DURING_MANUAL_MIGRATION",
            homologation_env,
        )
        self.assertNotIn("sigra_dev_only", render + vercel + homologation_env)
        self.assertNotIn("service_role", render + vercel + homologation_env)


if __name__ == "__main__":
    unittest.main()
