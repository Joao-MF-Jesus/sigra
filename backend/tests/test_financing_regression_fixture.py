import json
import unittest
from decimal import Decimal
from pathlib import Path

from app.financing.calculator import installment_schedule, price_installment
from app.financing.comparison import compare_results
from app.financing.schemas import DirectFinancingRequest, ReverseFinancingRequest
from app.financing.service import simulate_direct, simulate_reverse


FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "financing_regression_v1.json"
)


def _decimalize_price_context(context: dict) -> dict:
    monetary_fields = {
        "used_price",
        "catalog_price",
        "manual_price",
        "negotiated_price",
    }
    return {
        key: Decimal(str(value)) if key in monetary_fields and value is not None else value
        for key, value in context.items()
    }


def _value_at_path(data: dict, path: str):
    value = data
    for part in path.split("."):
        value = value[part]
    return value


class FinancingRegressionFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.tolerance = cls.fixture["money_tolerance"]

    def assert_expected_values(self, actual: dict, expected: dict):
        for path, expected_value in expected.items():
            with self.subTest(field=path):
                actual_value = _value_at_path(actual, path)
                if isinstance(expected_value, (int, float)) and not isinstance(
                    expected_value, bool
                ):
                    self.assertAlmostEqual(
                        float(actual_value),
                        float(expected_value),
                        delta=self.tolerance,
                    )
                else:
                    self.assertEqual(actual_value, expected_value)

    def test_fixture_metadata_is_frozen(self):
        self.assertTrue(self.fixture["immutable"])
        self.assertEqual(self.fixture["fixture_version"], "financing-regression-v1")
        self.assertEqual(self.fixture["module_version"], "1.0.3")
        self.assertEqual(
            self.fixture["calculation_method_version"], "price-v1.2"
        )
        self.assertEqual(self.fixture["currency"], "BRL")

    def test_price_formula_and_displayed_schedule_regression(self):
        for scenario in self.fixture["calculator_scenarios"]:
            with self.subTest(scenario=scenario["name"]):
                precise = price_installment(
                    Decimal(str(scenario["principal"])),
                    Decimal(str(scenario["monthly_rate_percent"])),
                    scenario["term_months"],
                )
                schedule = installment_schedule(precise, scenario["term_months"])
                self.assert_expected_values(schedule, scenario["expected"])

    def test_direct_and_reverse_simulation_regression(self):
        for scenario in self.fixture["direct_scenarios"]:
            with self.subTest(kind="direct", scenario=scenario["name"]):
                payload = DirectFinancingRequest.model_validate(scenario["payload"])
                result = simulate_direct(
                    payload,
                    _decimalize_price_context(scenario["price_context"]),
                )
                self.assertEqual(result["module_version"], "1.0.3")
                self.assertEqual(result["calculation_method_version"], "price-v1.2")
                self.assert_expected_values(result, scenario["expected"])
                self.assertEqual(
                    result["total_interest_and_financed_costs"],
                    result["total_financing_addition"],
                )

        for scenario in self.fixture["reverse_scenarios"]:
            with self.subTest(kind="reverse", scenario=scenario["name"]):
                payload = ReverseFinancingRequest.model_validate(scenario["payload"])
                result = simulate_reverse(payload)
                self.assertEqual(result["module_version"], "1.0.3")
                self.assertEqual(result["calculation_method_version"], "price-v1.2")
                self.assert_expected_values(result, scenario["expected"])

    def test_comparison_context_and_highlights_regression(self):
        templates = self.fixture["comparison_templates"]
        for scenario in self.fixture["comparison_scenarios"]:
            results = []
            for scenario_input in scenario["scenarios"]:
                template = templates[scenario_input["template"]]
                payload = DirectFinancingRequest.model_validate(
                    {
                        "vehicle_type": "car",
                        "vehicle_id": template["vehicle_id"],
                        "down_payment": 20000,
                        "term_months": template["term_months"],
                        "monthly_interest_rate_percent": 1.5,
                        "upfront_fees": 0,
                        "financed_fees": 0,
                        "financed_insurance": 0,
                        "financed_services": 0,
                        "desired_max_installment": 2500,
                        "available_monthly_budget": template[
                            "available_monthly_budget"
                        ],
                        "estimated_monthly_vehicle_cost": template[
                            "estimated_monthly_vehicle_cost"
                        ],
                        "offer_name": scenario_input["name"],
                    }
                )
                result = simulate_direct(
                    payload,
                    {
                        "used_price": Decimal(str(template["price"])),
                        "catalog_price": Decimal(str(template["price"])),
                        "manual_price": None,
                        "negotiated_price": None,
                        "price_source": "catalog",
                        "vehicle": {
                            "id": template["vehicle_id"],
                            "vehicle_type": "car",
                            "brand": "Fixture",
                            "model": "Controlado",
                            "year": 2024,
                        },
                        "is_demonstration_data": False,
                        "warnings": [],
                    },
                )
                result["scenario_name"] = scenario_input["name"]
                results.append(result)

            with self.subTest(scenario=scenario["name"]):
                comparison = compare_results(results)
                self.assert_expected_values(
                    comparison["comparison_context"], scenario["expected_context"]
                )
                self.assertEqual(
                    comparison["suppressed_highlights"],
                    scenario["expected_suppressed_highlights"],
                )
                if "expected_highlights" in scenario:
                    self.assertEqual(
                        comparison["highlights"], scenario["expected_highlights"]
                    )
                for criterion, expected_value in scenario.get(
                    "expected_highlight_values", {}
                ).items():
                    self.assertAlmostEqual(
                        comparison["highlight_details"][criterion]["value"],
                        expected_value,
                        delta=self.tolerance,
                    )


if __name__ == "__main__":
    unittest.main()
