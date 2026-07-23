import copy
import tempfile
import unittest
from datetime import date
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

def objective_payload(*, source="estimated", category="naked"):
    from backend.tests.test_motorcycles import VALID_MOTORCYCLE

    payload = copy.deepcopy(VALID_MOTORCYCLE)
    payload.pop("reliability_score")
    payload.pop("parts_availability_score")
    for field in (
        "recommended_experience",
        "urban_score",
        "road_score",
        "passenger_comfort_score",
        "luggage_score",
    ):
        payload["specifications"].pop(field)
    payload["data_source"] = source
    payload["data_confidence"] = 70
    payload["source_reference"] = "Cadastro técnico ainda sem fontes por grupo"
    payload["specifications"]["motorcycle_category"] = category
    return payload


def eligibility_ready_payload(*, confidence=80, reference_date="2026-07-01", displacement=293.5):
    payload = objective_payload()
    payload.update(
        {
            "market_condition": "used",
            "fuel_type": "gasoline",
            "price_reference_date": reference_date,
        }
    )
    payload["specifications"].update(
        {
            "engine_displacement_cc": displacement,
            "power_cv": 24.7,
            "transmission_type": "manual",
            "final_drive_type": "chain",
        }
    )
    payload["data_sources"] = [
        {
            "data_group": group,
            "source_type": "estimated",
            "source_reference": f"Metodologia documentada para {group}",
            "reference_date": reference_date,
            "confidence": confidence,
            "is_primary": True,
        }
        for group in ("identity", "market_price", "technical_specs", "consumption", "maintenance")
    ]
    return payload


class MotorcycleSpecV1Test(unittest.TestCase):
    def setUp(self):
        from app.database import Base
        from app.motorcycle_eligibility import evaluate_motorcycle_eligibility
        from app.models import MotorcycleDataSource, MotorcycleDerivedMetric
        from app.repository import (
            create_motorcycle,
            create_motorcycle_derived_metric,
            create_motorcycle_source,
            delete_motorcycle_record,
            motorcycle_to_response,
        )
        from app.schemas import (
            MotorcycleCreate,
            MotorcycleDataSourceCreate,
            MotorcycleDerivedMetricCreate,
        )

        self.MotorcycleCreate = MotorcycleCreate
        self.MotorcycleDataSourceCreate = MotorcycleDataSourceCreate
        self.MotorcycleDerivedMetricCreate = MotorcycleDerivedMetricCreate
        self.MotorcycleDataSource = MotorcycleDataSource
        self.MotorcycleDerivedMetric = MotorcycleDerivedMetric
        self.create_motorcycle = create_motorcycle
        self.create_motorcycle_source = create_motorcycle_source
        self.create_motorcycle_derived_metric = create_motorcycle_derived_metric
        self.delete_motorcycle_record = delete_motorcycle_record
        self.motorcycle_to_response = motorcycle_to_response
        self.evaluate_motorcycle_eligibility = evaluate_motorcycle_eligibility
        self.engine = create_engine("sqlite:///:memory:")
        with self.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_motorcycle_without_derived_metrics_is_valid_and_incomplete_only_for_future_eligibility(self):
        with Session(self.engine) as db:
            record = self.create_motorcycle(db, self.MotorcycleCreate.model_validate(objective_payload()))
            self.assertEqual(record["derived_metrics"], [])
            self.assertEqual(self.motorcycle_to_response(record)["eligibility_status"], "incomplete")
            self.assertIsNotNone(record["specifications"])

    def test_demonstration_record_is_structurally_ineligible(self):
        payload = objective_payload(source="demonstration")
        payload.pop("source_reference", None)
        with Session(self.engine) as db:
            record = self.create_motorcycle(db, self.MotorcycleCreate.model_validate(payload))
            self.assertEqual(self.motorcycle_to_response(record)["eligibility_status"], "demonstration_only")

    def test_unsupported_category_is_reported_without_score(self):
        with Session(self.engine) as db:
            record = self.create_motorcycle(
                db,
                self.MotorcycleCreate.model_validate(objective_payload(category="sport")),
            )
            self.assertEqual(self.motorcycle_to_response(record)["eligibility_status"], "unsupported_category")

    def test_structural_eligibility_distinguishes_ready_low_confidence_outdated_and_domain_excluded(self):
        cases = (
            (eligibility_ready_payload(), "eligible"),
            (eligibility_ready_payload(confidence=40), "insufficient_confidence"),
            (eligibility_ready_payload(reference_date="2020-01-01"), "outdated_data"),
            (eligibility_ready_payload(displacement=90), "excluded_by_domain_rule"),
        )
        with Session(self.engine) as db:
            for payload, expected in cases:
                with self.subTest(expected=expected):
                    record = self.create_motorcycle(db, self.MotorcycleCreate.model_validate(payload))
                    eligibility = self.evaluate_motorcycle_eligibility(record, today=date(2026, 7, 21))
                    self.assertEqual(eligibility["eligibility_status"], expected)
                    self.assertNotIn("final_score", eligibility)
                    self.assertNotIn("rank", eligibility)

    def test_metric_validation_rejects_range_infinity_and_duplicate_method(self):
        for invalid in (101, float("inf")):
            with self.subTest(value=invalid), self.assertRaises(ValidationError):
                self.MotorcycleDerivedMetricCreate.model_validate(
                    {
                        "metric_name": "urban_score",
                        "metric_value": invalid,
                        "metric_status": "demonstration",
                        "method_version": "demonstration-v0",
                    }
                )

        with Session(self.engine) as db:
            record = self.create_motorcycle(db, self.MotorcycleCreate.model_validate(objective_payload()))
            metric = self.MotorcycleDerivedMetricCreate.model_validate(
                {
                    "metric_name": "urban_score",
                    "metric_value": 75,
                    "metric_status": "unvalidated",
                    "method_version": "manual-unvalidated-v1",
                    "notes": "Avaliação manual ainda não validada.",
                }
            )
            self.create_motorcycle_derived_metric(db, record["id"], metric)
            with self.assertRaises(ValueError):
                self.create_motorcycle_derived_metric(db, record["id"], metric)

    def test_sources_are_grouped_and_primary_source_is_unique(self):
        with Session(self.engine) as db:
            record = self.create_motorcycle(db, self.MotorcycleCreate.model_validate(objective_payload()))
            identity = self.MotorcycleDataSourceCreate.model_validate(
                {
                    "data_group": "identity",
                    "source_type": "official",
                    "source_name": "Fabricante Exemplo",
                    "source_reference": "Ficha do modelo",
                    "confidence": 80,
                    "is_primary": True,
                }
            )
            technical = self.MotorcycleDataSourceCreate.model_validate(
                {
                    "data_group": "technical_specs",
                    "source_type": "estimated",
                    "source_reference": "Coleta técnica documentada",
                    "confidence": 65,
                    "is_primary": True,
                }
            )
            self.create_motorcycle_source(db, record["id"], identity)
            self.create_motorcycle_source(db, record["id"], technical)
            with self.assertRaises(ValueError):
                self.create_motorcycle_source(db, record["id"], identity)

    def test_source_schema_rejects_invalid_official_url_and_confidence(self):
        invalid_payloads = (
            {"data_group": "identity", "source_type": "official", "source_reference": "Ref"},
            {"data_group": "identity", "source_type": "official", "source_name": "Fonte", "source_url": "invalida"},
            {"data_group": "identity", "source_type": "estimated", "source_reference": "Ref", "confidence": 101},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                self.MotorcycleDataSourceCreate.model_validate(payload)

    def test_cascade_removes_sources_and_metrics(self):
        with Session(self.engine) as db:
            record = self.create_motorcycle(db, self.MotorcycleCreate.model_validate(objective_payload()))
            self.create_motorcycle_source(
                db,
                record["id"],
                self.MotorcycleDataSourceCreate.model_validate(
                    {
                        "data_group": "identity",
                        "source_type": "estimated",
                        "source_reference": "Ref",
                    }
                ),
            )
            self.create_motorcycle_derived_metric(
                db,
                record["id"],
                self.MotorcycleDerivedMetricCreate.model_validate(
                    {
                        "metric_name": "urban_score",
                        "metric_value": 70,
                        "metric_status": "unvalidated",
                        "method_version": "manual-v1",
                        "notes": "Avaliação manual ainda não validada.",
                    }
                ),
            )
            self.assertTrue(self.delete_motorcycle_record(db, record["id"]))
            self.assertEqual(db.query(self.MotorcycleDataSource).count(), 0)
            self.assertEqual(db.query(self.MotorcycleDerivedMetric).count(), 0)


class MotorcycleSpecV1MigrationTest(unittest.TestCase):
    def test_migration_is_idempotent_preserves_rows_and_creates_no_false_sources(self):
        from app.migrations import (
            apply_motorcycle_spec_v1_migration,
            backup_database_before_motorcycle_spec_v1,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "legacy-v011.db"
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE vehicles (id INTEGER PRIMARY KEY, brand VARCHAR(80), vehicle_type VARCHAR(20))"))
                for identifier in range(1, 35):
                    connection.execute(
                        text("INSERT INTO vehicles (id, brand, vehicle_type) VALUES (:id, 'Carro', 'car')"),
                        {"id": identifier},
                    )
                connection.execute(
                    text(
                        "CREATE TABLE motorcycles (id INTEGER PRIMARY KEY, brand VARCHAR(80) NOT NULL, model VARCHAR(120) NOT NULL, "
                        "year INTEGER NOT NULL, price FLOAT NOT NULL, city_consumption FLOAT NOT NULL, road_consumption FLOAT NOT NULL, "
                        "annual_maintenance_cost FLOAT NOT NULL, reliability_score FLOAT NOT NULL, parts_availability_score FLOAT NOT NULL, "
                        "depreciation_rate FLOAT NOT NULL, data_source VARCHAR(30) NOT NULL, data_confidence FLOAT NOT NULL, "
                        "source_name VARCHAR(160), source_reference VARCHAR(240), source_url VARCHAR(500), source_collected_at DATETIME, "
                        "source_reference_date DATE, last_verified_at DATETIME, vehicle_type VARCHAR(20) NOT NULL, image_url VARCHAR(240) NOT NULL)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO motorcycles VALUES (1, 'Honda', 'Demo', 2025, 25000, 30, 34, 2200, 80, 85, 10, "
                        "'demonstration', 35, NULL, NULL, NULL, NULL, NULL, NULL, 'motorcycle', '')"
                    )
                )
                connection.execute(
                    text(
                        "CREATE TABLE motorcycle_specifications (id INTEGER PRIMARY KEY, motorcycle_id INTEGER UNIQUE NOT NULL, "
                        "engine_displacement_cc FLOAT NOT NULL, motorcycle_category VARCHAR(30) NOT NULL, wet_weight_kg FLOAT NOT NULL, "
                        "seat_height_mm FLOAT NOT NULL, tank_capacity_l FLOAT NOT NULL, has_abs BOOLEAN NOT NULL, "
                        "recommended_experience VARCHAR(30) NOT NULL, urban_score FLOAT NOT NULL, road_score FLOAT NOT NULL, "
                        "passenger_comfort_score FLOAT NOT NULL, luggage_score FLOAT NOT NULL)"
                    )
                )
                connection.execute(
                    text("INSERT INTO motorcycle_specifications VALUES (1, 1, 293.5, 'naked', 153, 789, 13.8, 1, 'intermediate', 80, 72, 60, 40)")
                )

            backup = backup_database_before_motorcycle_spec_v1(engine)
            first = apply_motorcycle_spec_v1_migration(engine)
            second = apply_motorcycle_spec_v1_migration(engine)

            self.assertIsNotNone(backup)
            self.assertTrue(backup.exists())
            self.assertTrue(first["applied"])
            self.assertFalse(second["applied"])
            with engine.connect() as connection:
                self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM vehicles")).scalar_one(), 34)
                self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM motorcycles")).scalar_one(), 1)
                self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM motorcycle_objective_specifications")).scalar_one(), 1)
                self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM motorcycle_derived_metrics")).scalar_one(), 7)
                self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM motorcycle_data_sources")).scalar_one(), 0)
            engine.dispose()
