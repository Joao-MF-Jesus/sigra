import copy
import tempfile
import unittest
from datetime import date
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from backend.tests.test_motorcycle_spec_v1 import eligibility_ready_payload


def canonical_payload():
    payload = eligibility_ready_payload()
    for field in (
        "data_source",
        "data_confidence",
        "source_name",
        "source_reference",
        "source_url",
        "source_collected_at",
        "source_reference_date",
        "last_verified_at",
        "reliability_score",
        "parts_availability_score",
        "depreciation_rate",
    ):
        payload.pop(field, None)
    return payload


class MotorcycleSchemaV03ContractTest(unittest.TestCase):
    def setUp(self):
        from app import models  # noqa: F401 - registra tabelas no metadata declarativo
        from app.database import Base

        self.engine = create_engine("sqlite:///:memory:")
        with self.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_canonical_record_needs_grouped_identity_and_omits_legacy_by_default(self):
        from app.repository import create_motorcycle, motorcycle_to_response
        from app.schemas import MotorcycleCreate

        with self.assertRaises(ValidationError):
            MotorcycleCreate.model_validate({**canonical_payload(), "data_sources": []})

        with Session(self.engine) as db:
            record = create_motorcycle(db, MotorcycleCreate.model_validate(canonical_payload()))
            response = motorcycle_to_response(record, include_legacy=False)

        self.assertNotIn("data_source", response)
        self.assertNotIn("reliability_score", response)
        self.assertNotIn("legacy_data", response)
        self.assertTrue(response["source_contract"]["canonical_precedence"])
        self.assertEqual(response["source_contract"]["required_for_registration"], ["identity"])
        self.assertEqual(response["derived_metrics"], [])
        self.assertEqual(response["economic_estimates"], [])
        self.assertNotIn("rank", response)
        self.assertNotIn("final_score", response)

    def test_secondary_demonstration_source_is_informational_and_primary_switch_is_transactional(self):
        from app.motorcycle_eligibility import evaluate_motorcycle_eligibility
        from app.repository import (
            create_motorcycle,
            create_motorcycle_source,
            get_motorcycle_record,
            list_motorcycle_sources,
            set_motorcycle_primary_source,
        )
        from app.schemas import MotorcycleCreate, MotorcycleDataSourceCreate

        with Session(self.engine) as db:
            record = create_motorcycle(db, MotorcycleCreate.model_validate(canonical_payload()))
            optional = create_motorcycle_source(
                db,
                record["id"],
                MotorcycleDataSourceCreate.model_validate(
                    {
                        "data_group": "ergonomics",
                        "source_type": "demonstration",
                        "source_name": "Base demonstrativa SIGRA",
                        "confidence": 30,
                        "is_primary": False,
                    }
                ),
            )
            after_optional = evaluate_motorcycle_eligibility(get_motorcycle_record(db, record["id"]), today=date(2026, 7, 21))
            self.assertEqual(after_optional["eligibility_status"], "eligible")
            self.assertEqual(after_optional["informational_issues"][0]["code"], "secondary_demonstration_source")

            demo_identity = create_motorcycle_source(
                db,
                record["id"],
                MotorcycleDataSourceCreate.model_validate(
                    {
                        "data_group": "identity",
                        "source_type": "demonstration",
                        "source_name": "Base demonstrativa SIGRA",
                        "confidence": 30,
                        "is_primary": False,
                    }
                ),
            )
            set_motorcycle_primary_source(db, record["id"], demo_identity["id"])
            sources = list_motorcycle_sources(db, record["id"])
            identity_sources = [item for item in sources if item["data_group"] == "identity"]
            self.assertEqual(sum(item["is_primary"] for item in identity_sources), 1)
            self.assertTrue(next(item for item in identity_sources if item["id"] == demo_identity["id"])["is_primary"])
            eligibility = evaluate_motorcycle_eligibility(get_motorcycle_record(db, record["id"]), today=date(2026, 7, 21))
            self.assertEqual(eligibility["eligibility_status"], "demonstration_only")
            self.assertTrue(any(item["field"] == "data_sources.identity" for item in eligibility["blocking_issues"]))
            self.assertEqual(optional["data_group"], "ergonomics")

    def test_explicit_demonstration_flag_blocks_canonical_record(self):
        from app.motorcycle_eligibility import evaluate_motorcycle_eligibility
        from app.repository import create_motorcycle, get_motorcycle_record
        from app.schemas import MotorcycleCreate

        payload = {**canonical_payload(), "is_demonstration": True}
        with Session(self.engine) as db:
            record = create_motorcycle(db, MotorcycleCreate.model_validate(payload))
            eligibility = evaluate_motorcycle_eligibility(
                get_motorcycle_record(db, record["id"]),
                today=date(2026, 7, 21),
            )
        self.assertEqual(eligibility["eligibility_status"], "demonstration_only")
        self.assertEqual(eligibility["blocking_issues"][0]["code"], "demonstration_record")

    def test_metric_and_economic_estimate_public_contracts(self):
        from app.repository import (
            create_motorcycle,
            create_motorcycle_derived_metric,
            create_motorcycle_economic_estimate,
        )
        from app.schemas import (
            MotorcycleCreate,
            MotorcycleDerivedMetricCreate,
            MotorcycleEconomicEstimateCreate,
        )

        invalid_metrics = (
            {"metric_name": "urban_score", "metric_value": 70, "metric_status": "uncalculated", "method_version": "manual-v1"},
            {"metric_name": "urban_score", "metric_value": 70, "metric_status": "calculated", "method_version": "manual-v1"},
            {"metric_name": "urban_score", "metric_value": 70, "metric_status": "deprecated", "method_version": "manual-v1"},
            {"metric_name": "urban_score", "metric_value": 70, "metric_status": "unvalidated", "method_version": "manual-v1"},
            {"metric_name": "urban_score", "metric_value": 70, "metric_status": "demonstration", "method_version": "manual-v1"},
            {"metric_name": "urban_score", "metric_value": 70, "metric_status": "demonstration", "method_version": "demonstration-v0", "confidence": 51},
        )
        for payload in invalid_metrics:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                MotorcycleDerivedMetricCreate.model_validate(payload)

        invalid_estimates = (
            {"estimate_name": "depreciation_rate_annual_percent", "estimate_value": 9, "unit": "percent_per_year", "method_version": "manual-v1", "reference_date": "2026-07-01", "status": "calculated"},
            {"estimate_name": "depreciation_rate_annual_percent", "estimate_value": 9, "unit": "percent_per_year", "method_version": "manual-v1", "reference_date": "2026-07-01", "status": "deprecated"},
            {"estimate_name": "depreciation_rate_annual_percent", "estimate_value": 9, "unit": "percent_per_year", "method_version": "manual-v1", "reference_date": "2026-07-01", "status": "unvalidated"},
        )
        for payload in invalid_estimates:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                MotorcycleEconomicEstimateCreate.model_validate(payload)

        metric = MotorcycleDerivedMetricCreate.model_validate(
            {
                "metric_name": "urban_score",
                "metric_value": 70,
                "metric_status": "unvalidated",
                "method_version": "manual-v1",
                "notes": "Rubrica ainda pendente de validação.",
            }
        )
        estimate = MotorcycleEconomicEstimateCreate.model_validate(
            {
                "estimate_name": "depreciation_rate_annual_percent",
                "estimate_value": 9,
                "unit": "percent_per_year",
                "method_version": "demonstration-v0",
                "reference_date": "2026-07-01",
                "status": "demonstration",
                "confidence": 30,
                "notes": "Valor exclusivamente demonstrativo.",
            }
        )
        with Session(self.engine) as db:
            record = create_motorcycle(db, MotorcycleCreate.model_validate(canonical_payload()))
            create_motorcycle_derived_metric(db, record["id"], metric)
            created_estimate = create_motorcycle_economic_estimate(db, record["id"], estimate)
            self.assertEqual(created_estimate["status"], "demonstration")
            with self.assertRaises(ValueError):
                create_motorcycle_economic_estimate(db, record["id"], estimate)


class MotorcycleSchemaV03MigrationTest(unittest.TestCase):
    def test_migration_is_idempotent_and_does_not_fabricate_canonical_data(self):
        from app.migrations import (
            apply_motorcycle_schema_v03_migration,
            backup_database_before_motorcycle_schema_v03,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "motorcycles-v020.db"
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE vehicles (id INTEGER PRIMARY KEY, vehicle_type VARCHAR(20))"))
                for identifier in range(1, 35):
                    connection.execute(text("INSERT INTO vehicles VALUES (:id, 'car')"), {"id": identifier})
                connection.execute(
                    text(
                        "CREATE TABLE motorcycles (id INTEGER PRIMARY KEY, brand VARCHAR(80) NOT NULL, model VARCHAR(120) NOT NULL, "
                        "year INTEGER NOT NULL, price FLOAT NOT NULL, city_consumption FLOAT NOT NULL, road_consumption FLOAT NOT NULL, "
                        "annual_maintenance_cost FLOAT NOT NULL, reliability_score FLOAT, parts_availability_score FLOAT, depreciation_rate FLOAT, "
                        "data_source VARCHAR(30) NOT NULL, data_confidence FLOAT NOT NULL, source_name VARCHAR(160), source_reference VARCHAR(240), "
                        "source_url VARCHAR(500), source_collected_at DATETIME, source_reference_date DATE, last_verified_at DATETIME, "
                        "vehicle_type VARCHAR(20) NOT NULL, image_url VARCHAR(240) NOT NULL, version VARCHAR(120), market_condition VARCHAR(20), "
                        "fuel_type VARCHAR(30), price_reference_date DATE)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO motorcycles VALUES (1, 'Honda', 'Legada', 2025, 25000, 30, 34, 2200, 80, 85, 10, "
                        "'demonstration', 35, NULL, NULL, NULL, NULL, NULL, NULL, 'motorcycle', '', NULL, NULL, NULL, NULL)"
                    )
                )
                connection.execute(text("CREATE TABLE motorcycle_data_sources (id INTEGER PRIMARY KEY, motorcycle_id INTEGER NOT NULL, data_group VARCHAR(40), source_type VARCHAR(30))"))
                connection.execute(text("INSERT INTO motorcycle_data_sources VALUES (1, 1, 'identity', 'demonstration')"))
                connection.execute(text("CREATE TABLE motorcycle_derived_metrics (id INTEGER PRIMARY KEY, motorcycle_id INTEGER NOT NULL, metric_name VARCHAR(60), metric_value FLOAT)"))
                connection.execute(text("INSERT INTO motorcycle_derived_metrics VALUES (1, 1, 'urban_score', 70)"))

            backup = backup_database_before_motorcycle_schema_v03(engine)
            first = apply_motorcycle_schema_v03_migration(engine)
            second = apply_motorcycle_schema_v03_migration(engine)

            self.assertIsNotNone(backup)
            self.assertTrue(backup.exists())
            self.assertTrue(first["applied"])
            self.assertFalse(second["applied"])
            self.assertEqual(first["sources_created"], 0)
            self.assertEqual(first["metrics_created"], 0)
            self.assertEqual(first["estimates_created"], 0)
            columns = {item["name"]: item for item in inspect(engine).get_columns("motorcycles")}
            self.assertTrue(columns["data_source"]["nullable"])
            self.assertTrue(columns["data_confidence"]["nullable"])
            self.assertTrue(columns["annual_maintenance_cost"]["nullable"])
            self.assertIn("is_demonstration", columns)
            with engine.connect() as connection:
                self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM vehicles")).scalar_one(), 34)
                self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM motorcycles")).scalar_one(), 1)
                self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM motorcycle_data_sources")).scalar_one(), 1)
                self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM motorcycle_derived_metrics")).scalar_one(), 1)
                self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM motorcycle_economic_estimates")).scalar_one(), 0)
                self.assertEqual(connection.execute(text("SELECT is_demonstration FROM motorcycles")).scalar_one(), 1)
            engine.dispose()
