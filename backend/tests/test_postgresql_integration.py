from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


RUN_POSTGRESQL_TESTS = (
    os.getenv("SIGRA_RUN_POSTGRES_TESTS", "").strip() == "1"
)
POSTGRESQL_URL = os.getenv("TEST_POSTGRESQL_URL", "").strip()
POSTGRESQL_AVAILABLE = RUN_POSTGRESQL_TESTS and POSTGRESQL_URL.startswith(
    ("postgresql://", "postgresql+psycopg://")
)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


class PostgreSQLIntegrationEnvironmentTest(unittest.TestCase):
    def test_postgresql_integration_environment_is_active(self):
        if not RUN_POSTGRESQL_TESTS:
            self.skipTest(
                "SIGRA_RUN_POSTGRES_TESTS nao habilitado; "
                "sentinela PostgreSQL nao executada."
            )
        self.assertTrue(
            POSTGRESQL_URL.startswith(
                ("postgresql://", "postgresql+psycopg://")
            ),
            "SIGRA_RUN_POSTGRES_TESTS=1 exige TEST_POSTGRESQL_URL PostgreSQL.",
        )
        engine = create_engine(POSTGRESQL_URL, pool_pre_ping=True)
        try:
            self.assertEqual(engine.dialect.name, "postgresql")
            with engine.connect() as connection:
                self.assertEqual(
                    connection.execute(text("SELECT 1")).scalar_one(),
                    1,
                )
        finally:
            engine.dispose()


@unittest.skipUnless(
    POSTGRESQL_AVAILABLE,
    "SIGRA_RUN_POSTGRES_TESTS=1 e TEST_POSTGRESQL_URL PostgreSQL "
    "sao obrigatorios para a integracao.",
)
class PostgreSQLIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous_database_url = os.environ.get("DATABASE_URL")
        cls.previous_database_env = os.environ.get("DATABASE_ENV")
        os.environ["DATABASE_URL"] = POSTGRESQL_URL
        os.environ["DATABASE_ENV"] = "integration"

        from alembic import command
        from alembic.config import Config

        from database_migration_common import CANONICAL_SQLITE_PATH
        from export_sqlite_data import export_sqlite_database
        from import_postgresql_data import import_database_export

        cls.config = Config(str(PROJECT_ROOT / "backend" / "alembic.ini"))
        command.downgrade(cls.config, "base")
        command.upgrade(cls.config, "head")
        command.downgrade(cls.config, "base")
        command.upgrade(cls.config, "head")
        cls.migration_cycle_completed = True

        cls.engine = create_engine(POSTGRESQL_URL, pool_pre_ping=True)
        cls.export_tmp = tempfile.TemporaryDirectory()
        cls.export_directory = Path(cls.export_tmp.name) / "export"
        export_sqlite_database(
            CANONICAL_SQLITE_PATH,
            cls.export_directory,
        )
        import_database_export(
            cls.export_directory,
            POSTGRESQL_URL,
            confirm_import=True,
        )

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        cls.export_tmp.cleanup()
        if cls.previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = cls.previous_database_url
        if cls.previous_database_env is None:
            os.environ.pop("DATABASE_ENV", None)
        else:
            os.environ["DATABASE_ENV"] = cls.previous_database_env

    def test_schema_revision_tables_constraints_numeric_json_and_timezone(self):
        from app.database import EXPECTED_ALEMBIC_HEAD
        from database_migration_common import (
            MONEY_COLUMNS,
            expected_table_order,
        )
        from psycopg.types.json import Jsonb

        inspector = inspect(self.engine)
        expected_tables = set(expected_table_order())
        self.assertTrue(
            expected_tables.issubset(inspector.get_table_names())
        )
        self.assertEqual(len(expected_tables), 18)
        motorcycle_checks = {
            item["name"]
            for item in inspector.get_check_constraints("motorcycles")
        }
        self.assertIn("ck_motorcycles_price_positive", motorcycle_checks)
        motorcycle_indexes = {
            item["name"]
            for item in inspector.get_indexes("motorcycles")
        }
        self.assertIn("ix_motorcycles_brand_model_year", motorcycle_indexes)
        expense_foreign_keys = inspector.get_foreign_keys("expenses")
        self.assertEqual(
            {
                foreign_key["referred_table"]
                for foreign_key in expense_foreign_keys
            },
            {"users", "vehicles"},
        )
        for table_name, column_name in MONEY_COLUMNS:
            columns = {
                column["name"]: column
                for column in inspector.get_columns(table_name)
            }
            self.assertEqual(
                columns[column_name]["type"].__class__.__name__,
                "NUMERIC",
            )
        with self.engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            self.assertEqual(revision, EXPECTED_ALEMBIC_HEAD)
            price = connection.execute(
                text("SELECT price FROM vehicles ORDER BY id LIMIT 1")
            ).scalar_one()
            self.assertIsInstance(price, Decimal)
            now = connection.execute(text("SELECT CURRENT_TIMESTAMP")).scalar_one()
            self.assertIsNotNone(now.tzinfo)
            payload = {"ordem": ["a", "b"], "ativo": True}
            round_trip = connection.execute(
                text("SELECT CAST(:payload AS JSONB)"),
                {"payload": Jsonb(payload)},
            ).scalar_one()
            self.assertEqual(round_trip, payload)

    def test_alembic_downgrade_and_second_upgrade_completed(self):
        self.assertTrue(self.migration_cycle_completed)

    def test_constraints_null_boolean_cascade_and_rollback(self):
        from app import models

        with Session(self.engine) as db:
            demonstration = db.scalar(
                select(models.Motorcycle).where(
                    models.Motorcycle.is_demonstration.is_(True)
                )
            )
            self.assertIsInstance(demonstration.is_demonstration, bool)

        with Session(self.engine) as db:
            transaction = db.begin()
            nullable_maintenance = models.Motorcycle(
                brand="Integracao",
                model="Nullable",
                year=2026,
                price=Decimal("20000.00"),
                city_consumption=30,
                road_consumption=34,
                annual_maintenance_cost=None,
                vehicle_type="motorcycle",
                image_url="",
                is_demonstration=False,
            )
            db.add(nullable_maintenance)
            db.flush()
            self.assertIsNone(
                db.get(
                    models.Motorcycle,
                    nullable_maintenance.id,
                ).annual_maintenance_cost
            )
            transaction.rollback()

        with Session(self.engine) as db:
            existing_email = db.scalar(select(models.User.email).limit(1))
            db.add(models.User(name="Duplicado", email=existing_email))
            with self.assertRaises(IntegrityError):
                db.flush()
            db.rollback()

        with self.engine.begin() as connection:
            transaction = connection.begin_nested()
            with self.assertRaises(IntegrityError):
                connection.execute(
                    models.Expense.__table__.insert(),
                    {
                        "user_id": 999999,
                        "vehicle_id": 999999,
                        "category": "teste",
                        "amount": Decimal("10.00"),
                        "expense_date": date(2026, 1, 1),
                        "description": "",
                    },
                )
            transaction.rollback()

        with Session(self.engine) as db:
            transaction = db.begin()
            motorcycle = models.Motorcycle(
                brand="Integracao",
                model="Cascade",
                year=2026,
                price=Decimal("20000.00"),
                city_consumption=30,
                road_consumption=34,
                vehicle_type="motorcycle",
                image_url="",
                is_demonstration=False,
            )
            db.add(motorcycle)
            db.flush()
            specification = models.MotorcycleSpecification(
                motorcycle_id=motorcycle.id,
                engine_displacement_cc=300,
                motorcycle_category="naked",
                wet_weight_kg=160,
                seat_height_mm=790,
                tank_capacity_l=14,
                has_abs=True,
                recommended_experience="intermediate",
                urban_score=80,
                road_score=75,
                passenger_comfort_score=65,
                luggage_score=40,
            )
            db.add(specification)
            db.flush()
            specification_id = specification.id
            db.delete(motorcycle)
            db.flush()
            self.assertIsNone(
                db.get(models.MotorcycleSpecification, specification_id)
            )
            transaction.rollback()

    def test_application_health_uses_postgresql_without_exposing_url(self):
        code = """
import json
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as client:
    response = client.get('/health/database')
    print(json.dumps(response.json()))
    raise SystemExit(0 if response.status_code == 200 else 1)
"""
        environment = os.environ.copy()
        environment.update(
            {
                "DATABASE_ENV": "integration",
                "DATABASE_URL": POSTGRESQL_URL,
                "FIPE_AUTO_REFRESH": "false",
            }
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=PROJECT_ROOT / "backend",
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(payload["database"]["engine"], "postgresql")
        self.assertTrue(payload["database"]["reachable"])
        self.assertTrue(payload["database"]["migration_up_to_date"])
        self.assertNotIn("url", payload["database"])

    def test_imported_content_is_equivalent_to_sqlite(self):
        from compare_database_contents import compare_databases
        from database_migration_common import CANONICAL_SQLITE_PATH

        report = compare_databases(
            f"sqlite:///{CANONICAL_SQLITE_PATH.as_posix()}",
            POSTGRESQL_URL,
        )
        self.assertEqual(report["status"], "equivalent", report)
        self.assertEqual(report["row_count_differences"], [])
        self.assertEqual(report["relation_differences"], [])

    def test_car_and_motorcycle_crud_rollback_without_persisting(self):
        from app import models

        with Session(self.engine) as db:
            transaction = db.begin()
            car = models.Vehicle(
                brand="Integracao",
                model="PostgreSQL",
                year=2026,
                price=Decimal("100000.00"),
                fuel_efficiency_km_l=12,
                annual_maintenance_cost=Decimal("3000.00"),
                reliability_score=80,
                parts_availability_score=80,
                depreciation_rate=8,
                use_cases="cidade",
                chronic_issues="",
                image_url="",
                category="compact",
                segment_level=2,
                comfort_score=70,
                space_score=70,
                safety_score=70,
                urban_score=70,
                road_score=70,
                family_score=70,
                app_score=70,
                vehicle_type="car",
            )
            motorcycle = models.Motorcycle(
                brand="Integracao",
                model="Moto PostgreSQL",
                year=2026,
                price=Decimal("25000.00"),
                city_consumption=30,
                road_consumption=34,
                vehicle_type="motorcycle",
                image_url="",
                is_demonstration=False,
            )
            db.add_all([car, motorcycle])
            db.flush()
            self.assertIsNotNone(car.id)
            self.assertIsNotNone(motorcycle.id)
            self.assertGreater(car.id, 34)
            self.assertGreater(motorcycle.id, 5)
            transaction.rollback()
        with Session(self.engine) as db:
            self.assertIsNone(
                db.scalar(
                    select(models.Vehicle).where(
                        models.Vehicle.brand == "Integracao"
                    )
                )
            )

    def test_automobile_ranking_matches_sqlite_and_motorcycle_stays_501(self):
        from app.recommender import RecommendationProfile, recommend
        from app.repository import model_to_recommendation_vehicle
        from app.vehicle_queries import car_query
        from database_migration_common import CANONICAL_SQLITE_PATH

        fixture = json.loads(
            (
                PROJECT_ROOT
                / "backend"
                / "tests"
                / "fixtures"
                / "cars_regression_v1.json"
            ).read_text(encoding="utf-8")
        )
        sqlite_engine = create_engine(
            f"sqlite:///{CANONICAL_SQLITE_PATH.as_posix()}"
        )
        try:
            with Session(sqlite_engine) as db:
                sqlite_vehicles = [
                    model_to_recommendation_vehicle(item)
                    for item in car_query(db).order_by(text("id")).all()
                ]
        finally:
            sqlite_engine.dispose()
        with Session(self.engine) as db:
            postgresql_vehicles = [
                model_to_recommendation_vehicle(item)
                for item in car_query(db).order_by(text("id")).all()
            ]
        for scenario in fixture["scenarios"]:
            sqlite_results = recommend(
                sqlite_vehicles,
                RecommendationProfile(**scenario["profile"]),
            )
            postgresql_results = recommend(
                postgresql_vehicles,
                RecommendationProfile(**scenario["profile"]),
            )
            self.assertEqual(
                [item["vehicle"].id for item in postgresql_results],
                [item["vehicle"].id for item in sqlite_results],
            )
            for result, expected in zip(
                postgresql_results,
                sqlite_results,
            ):
                self.assertAlmostEqual(
                    result["score"],
                    expected["score"],
                    delta=fixture["score_tolerance"],
                )
                self.assertEqual(
                    result["recommendation_status"],
                    expected["recommendation_status"],
                )
                self.assertEqual(
                    result["score_components"]["fully_viable"],
                    expected["score_components"]["fully_viable"],
                )

        code = """
import json
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as client:
    response = client.post('/motorcycles/recommendations', json={})
    print(json.dumps({
        'status_code': response.status_code,
        'payload': response.json(),
    }))
    raise SystemExit(0 if response.status_code == 501 else 1)
"""
        environment = os.environ.copy()
        environment.update(
            {
                "DATABASE_ENV": "integration",
                "DATABASE_URL": POSTGRESQL_URL,
                "FIPE_AUTO_REFRESH": "false",
            }
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=PROJECT_ROOT / "backend",
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(response["status_code"], 501)
        self.assertIsNone(response["payload"]["algorithm_version"])
