import csv
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = PROJECT_ROOT / "scripts" / "validate_motorcycle_pilot_data.py"
IMPORTER_PATH = PROJECT_ROOT / "scripts" / "import_motorcycle_pilot_data.py"
TEMPLATE_PATH = PROJECT_ROOT / "backend" / "data" / "templates" / "motorcycle_pilot_collection_v1.csv"


def load_validator():
    spec = importlib.util.spec_from_file_location("motorcycle_pilot_validator", VALIDATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pilot_rows(module):
    base = {column: "" for column in module.REQUIRED_COLUMNS}
    base.update(
        {
            "record_key": "honda-modelo-2025",
            "brand": "Honda",
            "model": "Modelo auditável",
            "version": "Versão A",
            "year": "2025",
            "category": "naked",
            "engine_displacement_cc": "300",
            "market_condition": "new",
            "fuel_type": "gasoline",
            "price_brl": "25000",
            "price_reference_date": "2026-07-01",
            "power_cv": "25",
            "torque_nm": "26",
            "wet_weight_kg": "150",
            "seat_height_mm": "790",
            "tank_capacity_l": "14",
            "city_consumption_km_l": "30",
            "road_consumption_km_l": "34",
            "transmission_type": "manual",
            "gear_count": "6",
            "final_drive_type": "chain",
            "has_abs": "true",
            "has_cbs": "false",
            "has_traction_control": "false",
            "source_type": "official",
            "source_name": "Fonte identificada",
            "source_reference": "Documento consultado pela coleta piloto",
            "confidence": "85",
            "collected_at": "2026-07-21T10:00:00-03:00",
            "reference_date": "2026-07-01",
            "is_primary": "true",
            "review_status": "reviewed",
        }
    )
    return [
        {**base, "data_group": group}
        for group in ("identity", "market_price", "technical_specs", "consumption")
    ]


class MotorcyclePilotToolsTest(unittest.TestCase):
    def test_template_is_structurally_valid_without_invented_rows(self):
        module = load_validator()
        report, rows = module.validate_pilot_file(TEMPLATE_PATH)
        self.assertTrue(report["valid"])
        self.assertEqual(report["record_count"], 0)
        self.assertEqual(rows, [])

    def test_validator_reports_coverage_and_duplicate_primary(self):
        module = load_validator()
        with tempfile.TemporaryDirectory() as tmpdir:
            valid_path = Path(tmpdir) / "valid.csv"
            rows = pilot_rows(module)
            with valid_path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=sorted(module.REQUIRED_COLUMNS))
                writer.writeheader()
                writer.writerows(rows)
            valid, _ = module.validate_pilot_file(valid_path)
            self.assertTrue(valid["valid"], valid["errors"])
            self.assertEqual(valid["record_count"], 1)
            self.assertEqual(valid["source_count"], 4)
            self.assertEqual(valid["coverage"][0]["pilot_required_source_coverage_percent"], 100)
            self.assertTrue(any(item["field"] == "annual_maintenance_cost_brl" for item in valid["warnings"]))

            invalid_path = Path(tmpdir) / "invalid.csv"
            duplicate_rows = rows + [{**rows[0], "source_name": "Outra fonte"}]
            with invalid_path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=sorted(module.REQUIRED_COLUMNS))
                writer.writeheader()
                writer.writerows(duplicate_rows)
            invalid, _ = module.validate_pilot_file(invalid_path)
            self.assertFalse(invalid["valid"])
            self.assertTrue(any(item["code"] == "duplicate_primary" for item in invalid["errors"]))

    def test_importer_dry_run_does_not_create_database(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "must-not-exist.db"
            environment = {**os.environ, "DATABASE_URL": f"sqlite:///{database_path.as_posix()}"}
            result = subprocess.run(
                [sys.executable, str(IMPORTER_PATH), str(TEMPLATE_PATH), "--dry-run"],
                cwd=PROJECT_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"database_modified": false', result.stdout)
            self.assertFalse(database_path.exists())

    def test_consistent_equivalent_values_and_optional_maintenance(self):
        module = load_validator()
        rows = pilot_rows(module)
        rows[1]["price_brl"] = "25.000,00"
        rows[2]["price_brl"] = "25000.0"
        rows[1]["has_abs"] = "1"
        rows[2]["has_abs"] = "sim"
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "equivalent.csv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=sorted(module.REQUIRED_COLUMNS))
                writer.writeheader()
                writer.writerows(rows)
            report, _ = module.validate_pilot_file(path)
        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(report["record_consistency"]["records_with_inconsistency"], 0)
        self.assertEqual(report["coverage"][0]["pilot_required_source_coverage_percent"], 100)
        self.assertEqual(report["coverage"][0]["complementary_source_coverage_percent"], 0)
        self.assertIn("maintenance", report["coverage"][0]["missing_complementary_source_groups"])
        self.assertEqual(report["coverage"][0]["future_recommendation_readiness"], "missing_economic_data")

    def test_objective_divergences_report_every_conflicting_row(self):
        module = load_validator()
        for field, divergent in (
            ("price_brl", "99999"),
            ("year", "2024"),
            ("power_cv", "99"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmpdir:
                rows = pilot_rows(module)
                rows[2][field] = divergent
                path = Path(tmpdir) / f"{field}.csv"
                with path.open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=sorted(module.REQUIRED_COLUMNS))
                    writer.writeheader()
                    writer.writerows(rows)
                report, _ = module.validate_pilot_file(path)
                self.assertFalse(report["valid"])
                inconsistency = next(
                    item for item in report["record_consistency"]["inconsistencies"]
                    if item["field"] == field
                )
                self.assertEqual(inconsistency["code"], "inconsistent_record_data")
                self.assertEqual(
                    [item["row"] for item in inconsistency["values"]],
                    [2, 3, 4, 5],
                )

    def test_missing_consumption_source_blocks_pilot_but_maintenance_does_not(self):
        module = load_validator()
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_consumption = pilot_rows(module)[:-1]
            path = Path(tmpdir) / "missing-consumption.csv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=sorted(module.REQUIRED_COLUMNS))
                writer.writeheader()
                writer.writerows(missing_consumption)
            report, _ = module.validate_pilot_file(path)
        self.assertFalse(report["valid"])
        self.assertIn("consumption", report["coverage"][0]["missing_pilot_source_groups"])
        self.assertFalse(any(
            item["code"] == "missing_primary_source" and "maintenance" in item["message"]
            for item in report["errors"]
        ))

    def test_importer_rejects_inconsistent_file_before_database_access(self):
        module = load_validator()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "inconsistent.csv"
            rows = pilot_rows(module)
            rows[3]["price_brl"] = "99999"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=sorted(module.REQUIRED_COLUMNS))
                writer.writeheader()
                writer.writerows(rows)
            database_path = Path(tmpdir) / "must-not-exist.db"
            environment = {**os.environ, "DATABASE_URL": f"sqlite:///{database_path.as_posix()}"}
            result = subprocess.run(
                [sys.executable, str(IMPORTER_PATH), str(path), "--dry-run"],
                cwd=PROJECT_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn('"records_with_inconsistency": 1', result.stdout)
        self.assertFalse(database_path.exists())


if __name__ == "__main__":
    unittest.main()
