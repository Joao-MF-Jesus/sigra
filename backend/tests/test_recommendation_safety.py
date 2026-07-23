import os
import subprocess
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.recommender import (
    RecommendationProfile,
    Vehicle,
    recommend,
    select_primary_factors,
    validate_vehicle_data,
)
from app.tco import TCOValidationError, calculate_tco


VALID_TCO = {
    "vehicle_price": 60000,
    "fuel_efficiency_km_l": 12,
    "monthly_mileage": 1000,
    "fuel_price": 6,
    "annual_maintenance_cost": 2400,
    "annual_depreciation_rate": 10,
}


class RecommendationSafetyTest(unittest.TestCase):
    def setUp(self):
        self.vehicle = Vehicle(
            1, "Marca", "Modelo", 2020, 60000, 12, 2400, 85, 80, 10, ("cidade",), ()
        )
        self.profile = RecommendationProfile(80000, 2000, "cidade")

    def test_zero_consumption_is_rejected(self):
        with self.assertRaisesRegex(TCOValidationError, "fuel_efficiency_km_l"):
            calculate_tco(**{**VALID_TCO, "fuel_efficiency_km_l": 0})

    def test_negative_consumption_is_rejected(self):
        with self.assertRaisesRegex(TCOValidationError, "fuel_efficiency_km_l"):
            calculate_tco(**{**VALID_TCO, "fuel_efficiency_km_l": -1})

    def test_missing_and_negative_price_are_rejected(self):
        with self.assertRaisesRegex(TCOValidationError, "vehicle_price"):
            calculate_tco(**{**VALID_TCO, "vehicle_price": None})
        with self.assertRaisesRegex(TCOValidationError, "vehicle_price"):
            calculate_tco(**{**VALID_TCO, "vehicle_price": -1})

    def test_missing_financial_fields_are_rejected(self):
        for field in ("annual_maintenance_cost", "annual_depreciation_rate"):
            with self.subTest(field=field):
                with self.assertRaises(TCOValidationError):
                    calculate_tco(**{**VALID_TCO, field: None})

    def test_negative_financial_rates_and_mileage_are_rejected(self):
        for field, value in (
            ("annual_maintenance_cost", -1),
            ("annual_depreciation_rate", -1),
            ("monthly_mileage", -1),
            ("fuel_price", -1),
            ("ipva_rate", -0.01),
            ("insurance_rate", -0.01),
        ):
            with self.subTest(field=field):
                with self.assertRaises(TCOValidationError):
                    calculate_tco(**{**VALID_TCO, field: value})

    def test_non_numeric_values_are_rejected(self):
        with self.assertRaises(TCOValidationError):
            calculate_tco(**{**VALID_TCO, "vehicle_price": "sessenta mil"})
        invalid = replace(self.vehicle, annual_maintenance_cost="desconhecida")
        self.assertIn("annual_maintenance_cost invalido", validate_vehicle_data(invalid))

    def test_secondary_scores_outside_range_are_rejected(self):
        for field, value in (("comfort_score", -1), ("safety_score", 101), ("app_score", float("inf"))):
            with self.subTest(field=field):
                errors = validate_vehicle_data(replace(self.vehicle, **{field: value}))
                self.assertTrue(any(field in error for error in errors))

    def test_invalid_year_segment_category_and_use_cases_are_rejected(self):
        invalid = replace(
            self.vehicle,
            year=1980,
            segment_level=7,
            category="caminhao",
            use_cases=("voo",),
            price_is_fipe="sim",
        )
        errors = validate_vehicle_data(invalid)

        self.assertIn("year invalido", errors)
        self.assertIn("segment_level invalido", errors)
        self.assertIn("category invalida", errors)
        self.assertIn("use_cases invalido", errors)
        self.assertIn("price_is_fipe invalido", errors)

    def test_no_valid_vehicle_returns_empty_result_and_processing_counts(self):
        processing = {}
        invalid = replace(self.vehicle, fuel_efficiency_km_l=0)

        self.assertEqual(recommend([invalid], self.profile, processing_metadata=processing), [])
        self.assertEqual(processing["total_found"], 1)
        self.assertEqual(processing["evaluated"], 0)
        self.assertEqual(processing["ignored"], 1)
        self.assertIn("fuel_efficiency_km_l invalido", processing["ignored_reasons"])

    def test_complete_tie_is_independent_from_input_order(self):
        first = replace(self.vehicle, id=1)
        second = replace(self.vehicle, id=2)

        normal = recommend([first, second], self.profile)
        reversed_input = recommend([second, first], self.profile)

        self.assertEqual([item["vehicle"].id for item in normal], [1, 2])
        self.assertEqual([item["vehicle"].id for item in reversed_input], [1, 2])

    def test_single_vehicle_and_equal_values_are_supported(self):
        single = recommend([self.vehicle], self.profile)
        equal = recommend([self.vehicle, replace(self.vehicle, id=2)], self.profile)

        self.assertEqual(len(single), 1)
        self.assertEqual(single[0]["components"]["price"], 100)
        self.assertTrue(all(item["components"]["price"] == 100 for item in equal))

    def test_extreme_outliers_keep_scores_finite_and_bounded(self):
        high = replace(self.vehicle, id=2, model="Outlier alto", price=1_000_000_000)
        low = replace(self.vehicle, id=3, model="Outlier baixo", price=1)
        results = recommend([self.vehicle, high, low], self.profile)

        self.assertEqual(len(results), 3)
        self.assertTrue(all(0 <= item["score"] <= 100 for item in results))
        self.assertTrue(all(item["score"] == item["score"] for item in results))

    def test_multiple_invalid_values_exclude_only_invalid_vehicle(self):
        invalid = replace(
            self.vehicle,
            id=2,
            model="Invalido",
            price=None,
            fuel_efficiency_km_l=0,
            annual_maintenance_cost=-1,
            depreciation_rate=float("nan"),
        )
        errors = validate_vehicle_data(invalid)
        results = recommend([invalid, self.vehicle], self.profile)

        self.assertGreaterEqual(len(errors), 4)
        self.assertEqual([item["vehicle"].id for item in results], [self.vehicle.id])

    def test_missing_required_identity_is_reported(self):
        invalid = replace(self.vehicle, brand=None, model="")
        errors = validate_vehicle_data(invalid)

        self.assertIn("brand ausente", errors)
        self.assertIn("model ausente", errors)

    def test_missing_database_fields_reach_domain_validation(self):
        from app.repository import model_to_recommendation_vehicle

        database_row = SimpleNamespace(
            id=99999,
            brand=None,
            model=None,
            year=2020,
            price=None,
            fuel_efficiency_km_l=None,
            annual_maintenance_cost=None,
            reliability_score=80,
            parts_availability_score=80,
            depreciation_rate=None,
            use_cases=None,
            chronic_issues=None,
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
        )
        converted = model_to_recommendation_vehicle(database_row)

        self.assertEqual(recommend([converted], self.profile), [])
        self.assertGreaterEqual(len(validate_vehicle_data(converted)), 5)

    def test_absence_of_reports_is_neutral(self):
        from app.vehicle_history import build_recommendation_feedback

        statistics = {
            1: {
                "report_count": 0,
                "risk_index": 0,
                "average_repair_cost": None,
                "consumption_gap_percent": None,
            }
        }
        with patch("app.vehicle_history.calculate_model_statistics", return_value=statistics):
            feedback = build_recommendation_feedback(object())[1]

        self.assertEqual(feedback["bonus"], 0)
        self.assertEqual(feedback["net_adjustment"], 0)
        self.assertFalse(any("ausencia" in reason for reason in feedback["reasons"]))

    def test_main_advantage_uses_largest_weighted_contribution(self):
        result = recommend([self.vehicle], self.profile)[0]
        expected = max(
            result["score_breakdown"]["criteria"],
            key=lambda row: row["contribution"],
        )

        self.assertEqual(result["recommendation_summary"]["main_advantage"], expected["label"])
        self.assertEqual(result["recommendation_summary"]["main_advantage_source"], "weighted_criterion")
        self.assertEqual(
            result["recommendation_summary"]["main_advantage_impact"],
            expected["contribution"],
        )

    def test_unweighted_indicator_cannot_be_primary_advantage(self):
        breakdown = {
            "criteria": [
                {"criterion": "usage_score", "label": "aderencia ao uso", "score": 70, "weight": 60, "contribution": 42},
                {"criterion": "financial_score", "label": "aderencia financeira", "score": 60, "weight": 40, "contribution": 24},
            ],
            "base_score": 66,
            "context_adjustment": 0,
            "evidence_adjustment": 0,
            "final_score": 66,
            "guardrails": [],
        }
        factors = select_primary_factors(breakdown, [])

        self.assertEqual(factors["advantage"], "aderencia ao uso")
        self.assertNotIn(factors["advantage"], {"baixo risco geral", "menor desvalorizacao"})

    def test_larger_adjustments_override_weighted_primary_factors(self):
        breakdown = {
            "criteria": [
                {"criterion": "usage_score", "label": "aderencia ao uso", "score": 80, "weight": 10, "contribution": 8},
                {"criterion": "financial_score", "label": "aderencia financeira", "score": 70, "weight": 10, "contribution": 7},
            ],
            "base_score": 15,
            "context_adjustment": -12,
            "evidence_adjustment": 0,
            "final_score": 3,
            "guardrails": [],
        }
        factors = select_primary_factors(breakdown, ["TCO mensal acima do limite."])

        self.assertEqual(factors["risk_source"], "context_adjustment")
        self.assertEqual(factors["risk"], "TCO mensal acima do limite.")
        self.assertEqual(factors["risk_impact"], 12)


    def test_invalid_internal_strategy_is_rejected_without_fallback(self):
        invalid = replace(self.profile, recommendation_strategy="qualquer_coisa")
        with self.assertRaisesRegex(ValueError, "recommendation_strategy"):
            recommend([self.vehicle], invalid)


class DatabasePathTest(unittest.TestCase):
    PROJECT_ROOT = Path(__file__).resolve().parents[2]
    BACKEND_ROOT = PROJECT_ROOT / "backend"

    def resolved_database_from(self, working_directory: Path) -> str:
        environment = os.environ.copy()
        environment.pop("DATABASE_URL", None)
        environment["PYTHONPATH"] = str(self.BACKEND_ROOT)
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "from app.database import engine; print(engine.url.database)",
            ],
            cwd=working_directory,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        return str(Path(completed.stdout.strip()).resolve())

    def test_starting_from_project_root_uses_backend_database(self):
        self.assertEqual(
            self.resolved_database_from(self.PROJECT_ROOT),
            str((self.BACKEND_ROOT / "sigra.db").resolve()),
        )

    def test_starting_from_backend_uses_same_database(self):
        self.assertEqual(
            self.resolved_database_from(self.BACKEND_ROOT),
            str((self.BACKEND_ROOT / "sigra.db").resolve()),
        )

    def test_legacy_root_relative_database_url_remains_compatible(self):
        environment = os.environ.copy()
        environment["DATABASE_URL"] = "sqlite:///./backend/sigra.db"
        environment["PYTHONPATH"] = str(self.BACKEND_ROOT)
        completed = subprocess.run(
            [sys.executable, "-c", "from app.database import engine; print(engine.url.database)"],
            cwd=self.PROJECT_ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            str(Path(completed.stdout.strip()).resolve()),
            str((self.BACKEND_ROOT / "sigra.db").resolve()),
        )


if __name__ == "__main__":
    unittest.main()
