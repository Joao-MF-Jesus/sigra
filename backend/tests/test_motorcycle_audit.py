import copy
import unittest

from app.motorcycle_audit import audit_motorcycle_record


def valid_record() -> dict:
    return {
        "id": 1,
        "brand": "Honda",
        "model": "CB 300F",
        "year": 2025,
        "price": 25000.0,
        "city_consumption": 30.0,
        "road_consumption": 34.0,
        "annual_maintenance_cost": 2200.0,
        "reliability_score": 80.0,
        "parts_availability_score": 85.0,
        "depreciation_rate": 10.0,
        "data_source": "demonstration",
        "data_confidence": 35.0,
        "source_name": None,
        "source_reference": None,
        "source_url": None,
        "source_collected_at": None,
        "source_reference_date": None,
        "last_verified_at": None,
        "vehicle_type": "motorcycle",
        "image_url": "",
        "specifications": {
            "engine_displacement_cc": 293.5,
            "motorcycle_category": "naked",
            "wet_weight_kg": 153.0,
            "seat_height_mm": 789.0,
            "tank_capacity_l": 13.8,
            "has_abs": 1,
            "recommended_experience": "intermediate",
            "urban_score": 80.0,
            "road_score": 72.0,
            "passenger_comfort_score": 60.0,
            "luggage_score": 40.0,
        },
    }


class MotorcycleAuditTest(unittest.TestCase):
    def test_valid_record_passes_without_mutation(self):
        record = valid_record()
        original = copy.deepcopy(record)
        audit = audit_motorcycle_record(record)
        self.assertTrue(audit["is_valid"])
        self.assertTrue(audit["is_complete"])
        self.assertEqual(record, original)

    def test_all_persisted_corruption_classes_are_reported(self):
        cases = {
            "confidence_above": ("data_confidence", 101, "data_confidence"),
            "confidence_below": ("data_confidence", -1, "data_confidence"),
            "invalid_source": ("data_source", "qualquer", "data_source"),
            "official_without_identification": ("data_source", "official", "source_name"),
            "invalid_url": ("source_url", "fonte-invalida", "source_url"),
            "invalid_date": ("source_collected_at", "ontem", "source_collected_at"),
            "infinite_price": ("price", float("inf"), "price"),
        }
        for name, (field, value, expected_field) in cases.items():
            with self.subTest(case=name):
                record = valid_record()
                record[field] = value
                audit = audit_motorcycle_record(record)
                self.assertFalse(audit["is_valid"])
                self.assertIn(expected_field, {issue["field"] for issue in audit["issues"]})

        specification_cases = {
            "invalid_category": ("motorcycle_category", "livre"),
            "invalid_boolean": ("has_abs", 2),
        }
        for name, (field, value) in specification_cases.items():
            with self.subTest(case=name):
                record = valid_record()
                record["specifications"][field] = value
                audit = audit_motorcycle_record(record)
                self.assertFalse(audit["is_valid"])
                self.assertIn(
                    f"specifications.{field}",
                    {issue["field"] for issue in audit["issues"]},
                )

    def test_legacy_derived_fields_do_not_define_objective_validity(self):
        record = valid_record()
        record["specifications"]["recommended_experience"] = None
        record["specifications"]["urban_score"] = None
        record["specifications"]["road_score"] = None
        record["specifications"]["passenger_comfort_score"] = None
        record["specifications"]["luggage_score"] = None
        record["reliability_score"] = None
        record["parts_availability_score"] = None
        audit = audit_motorcycle_record(record)
        self.assertTrue(audit["is_valid"])
        self.assertTrue(audit["is_complete"])

    def test_missing_specification_and_traceability_rules(self):
        record = valid_record()
        record["specifications"] = None
        audit = audit_motorcycle_record(record)
        self.assertFalse(audit["is_valid"])
        self.assertFalse(audit["is_complete"])
        self.assertIn("missing_relationship", {issue["code"] for issue in audit["issues"]})

        reported = valid_record()
        reported.update(
            data_source="user_reported",
            source_collected_at="2026-07-21T10:00:00-03:00",
            source_name="pessoa@example.com",
        )
        reported_audit = audit_motorcycle_record(reported)
        self.assertIn("personal_data_exposed", {issue["code"] for issue in reported_audit["issues"]})
