import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text

from app.migrations import (
    apply_motorcycle_foundation_migration,
    apply_motorcycle_hardening_migration,
    backup_database_before_motorcycle_hardening,
    backup_database_before_motorcycle_migration,
)
from app.schemas import MotorcycleCreate
from app.vehicle_domain import DataSource, MotorcycleCategory, RiderExperience, VehicleType


VALID_MOTORCYCLE = {
    "brand": "Honda",
    "model": "CB 300F",
    "year": 2025,
    "price": 25000,
    "city_consumption": 30,
    "road_consumption": 34,
    "annual_maintenance_cost": 2200,
    "reliability_score": 80,
    "parts_availability_score": 85,
    "depreciation_rate": 10,
    "data_source": "demonstration",
    "data_confidence": 35,
    "specifications": {
        "engine_displacement_cc": 293.5,
        "motorcycle_category": "naked",
        "wet_weight_kg": 153,
        "seat_height_mm": 789,
        "tank_capacity_l": 13.8,
        "has_abs": True,
        "recommended_experience": "intermediate",
        "urban_score": 80,
        "road_score": 72,
        "passenger_comfort_score": 60,
        "luggage_score": 40,
    },
}


class MotorcycleSchemaTest(unittest.TestCase):
    def test_controlled_enums(self):
        self.assertEqual({item.value for item in VehicleType}, {"car", "motorcycle"})
        self.assertIn(MotorcycleCategory.ADVENTURE, MotorcycleCategory)
        self.assertEqual(RiderExperience.BEGINNER.value, "beginner")
        self.assertEqual(DataSource.DEMONSTRATION.value, "demonstration")

    def test_valid_motorcycle_and_demonstration_file(self):
        payload = MotorcycleCreate.model_validate(VALID_MOTORCYCLE)
        self.assertEqual(payload.specifications.motorcycle_category, MotorcycleCategory.NAKED)
        data_file = Path(__file__).resolve().parents[1] / "data" / "motorcycles.demo.json"
        records = json.loads(data_file.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(records), 3)
        self.assertTrue(all(item["data_source"] == "demonstration" for item in records))
        self.assertTrue(all(MotorcycleCreate.model_validate(item) for item in records))

    def test_invalid_motorcycle_fields(self):
        invalid_cases = (
            ("category", {"specifications": {**VALID_MOTORCYCLE["specifications"], "motorcycle_category": "urbana-livre"}}),
            ("experience", {"specifications": {**VALID_MOTORCYCLE["specifications"], "recommended_experience": "novato"}}),
            ("displacement", {"specifications": {**VALID_MOTORCYCLE["specifications"], "engine_displacement_cc": 0}}),
            ("weight", {"specifications": {**VALID_MOTORCYCLE["specifications"], "wet_weight_kg": -1}}),
            ("seat", {"specifications": {**VALID_MOTORCYCLE["specifications"], "seat_height_mm": 200}}),
            ("tank", {"specifications": {**VALID_MOTORCYCLE["specifications"], "tank_capacity_l": 0}}),
            ("score", {"reliability_score": 101}),
            ("boolean", {"specifications": {**VALID_MOTORCYCLE["specifications"], "has_abs": "sim"}}),
            ("infinite", {"price": float("inf")}),
        )
        for name, changes in invalid_cases:
            with self.subTest(name=name), self.assertRaises(ValidationError):
                MotorcycleCreate.model_validate({**VALID_MOTORCYCLE, **changes})


class MotorcycleMigrationTest(unittest.TestCase):
    def test_migration_preserves_cars_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "legacy.db"
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE vehicles (id INTEGER PRIMARY KEY, brand VARCHAR(80))"))
                connection.execute(text("INSERT INTO vehicles (id, brand) VALUES (1, 'Marca A'), (2, 'Marca B')"))

            backup = backup_database_before_motorcycle_migration(engine)
            first = apply_motorcycle_foundation_migration(engine)
            second = apply_motorcycle_foundation_migration(engine)

            self.assertIsNotNone(backup)
            self.assertTrue(backup.exists())
            self.assertTrue(first["applied"])
            self.assertFalse(second["applied"])
            columns = {column["name"] for column in inspect(engine).get_columns("vehicles")}
            self.assertIn("vehicle_type", columns)
            with engine.connect() as connection:
                rows = connection.execute(text("SELECT id, vehicle_type FROM vehicles ORDER BY id")).all()
            self.assertEqual(rows, [(1, "car"), (2, "car")])
            engine.dispose()

    def test_traceability_migration_is_safe_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "foundation.db"
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE motorcycles (id INTEGER PRIMARY KEY, brand VARCHAR(80), model VARCHAR(120), year INTEGER, data_source VARCHAR(30))"))
                connection.execute(text("INSERT INTO motorcycles (id, brand, model, year, data_source) VALUES (1, 'Marca A', 'Modelo A', 2024, 'demonstration')"))

            backup = backup_database_before_motorcycle_hardening(engine)
            first = apply_motorcycle_hardening_migration(engine)
            second = apply_motorcycle_hardening_migration(engine)

            self.assertIsNotNone(backup)
            self.assertTrue(backup.exists())
            self.assertEqual(len(first["columns_added"]), 6)
            self.assertFalse(second["applied"])
            columns = {column["name"] for column in inspect(engine).get_columns("motorcycles")}
            self.assertIn("source_name", columns)
            self.assertIn("last_verified_at", columns)
            with engine.connect() as connection:
                self.assertEqual(connection.execute(text("SELECT brand FROM motorcycles WHERE id = 1")).scalar_one(), "Marca A")
            engine.dispose()
