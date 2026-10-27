import copy
import inspect
import unittest
from decimal import Decimal

from pydantic import ValidationError

from app.financing.calculator import (
    effective_monthly_rate_percent,
    installment_schedule,
    maximum_price_principal_for_schedule,
    money,
    price_installment,
)
from app.financing.comparison import compare_results
from app.financing.domain import EffectiveCostRatePeriod
from app.financing.schemas import DirectFinancingRequest, FinancingComparisonRequest, ReverseFinancingRequest
from app.financing.service import simulate_direct, simulate_reverse


DIRECT_PAYLOAD = {
    "vehicle_type": "car",
    "vehicle_price": 30000,
    "down_payment": 10000,
    "term_months": 36,
    "monthly_interest_rate_percent": 1.8,
    "upfront_fees": 0,
    "financed_fees": 500,
    "financed_insurance": 0,
    "financed_services": 0,
    "desired_max_installment": 900,
    "available_monthly_budget": 1600,
    "estimated_monthly_vehicle_cost": 620,
    "offer_name": "Banco A",
}


def direct_result(overrides=None):
    values = copy.deepcopy(DIRECT_PAYLOAD)
    values.update(overrides or {})
    payload = DirectFinancingRequest.model_validate(values)
    price = payload.negotiated_price or payload.vehicle_price
    return simulate_direct(
        payload,
        {
            "used_price": price,
            "catalog_price": None,
            "manual_price": price,
            "negotiated_price": None,
            "price_source": "manual",
            "vehicle": None,
            "is_demonstration_data": False,
            "warnings": [],
        },
    )


class PriceCalculatorTest(unittest.TestCase):
    def test_price_formula_with_positive_rate(self):
        installment = price_installment(Decimal("20500"), Decimal("1.8"), 36)
        self.assertEqual(money(installment), Decimal("778.67"))

    def test_price_formula_with_zero_rate(self):
        self.assertEqual(
            money(price_installment(Decimal("12000"), Decimal("0"), 12)),
            Decimal("1000.00"),
        )

    def test_rounding_is_half_up_only_at_result_boundary(self):
        self.assertEqual(money(Decimal("1.005")), Decimal("1.01"))

    def test_installment_schedule_reconciles_displayed_values(self):
        precise = price_installment(Decimal("20500"), Decimal("1.8"), 36)
        schedule = installment_schedule(precise, 36)
        self.assertEqual(schedule["regular_installment"], Decimal("778.67"))
        self.assertEqual(schedule["number_of_regular_installments"], 35)
        self.assertEqual(schedule["final_installment"], Decimal("778.62"))
        self.assertEqual(schedule["total_installments"], Decimal("28032.07"))
        reconciled = (
            schedule["regular_installment"] * schedule["number_of_regular_installments"]
            + schedule["final_installment"]
        )
        self.assertEqual(reconciled, schedule["total_installments"])

    def test_schedule_exposes_the_largest_displayed_installment(self):
        schedule = installment_schedule(
            price_installment(Decimal("100.05"), Decimal("1.8"), 36),
            36,
        )
        self.assertEqual(schedule["regular_installment"], Decimal("3.80"))
        self.assertEqual(schedule["final_installment"], Decimal("3.81"))
        self.assertEqual(
            schedule["maximum_installment_in_schedule"], Decimal("3.81")
        )

    def test_reverse_capacity_respects_the_largest_displayed_installment(self):
        principal, schedule = maximum_price_principal_for_schedule(
            Decimal("3.80"), Decimal("1.8"), 36
        )
        self.assertLessEqual(
            schedule["maximum_installment_in_schedule"], Decimal("3.80")
        )
        next_schedule = installment_schedule(
            price_installment(principal + Decimal("0.01"), Decimal("1.8"), 36),
            36,
        )
        self.assertGreater(
            next_schedule["maximum_installment_in_schedule"], Decimal("3.80")
        )

    def test_annual_cet_uses_effective_conversion_not_division_by_twelve(self):
        monthly = effective_monthly_rate_percent(
            monthly_rate_percent=None,
            effective_cost_rate_percent=Decimal("24"),
            effective_cost_rate_period=EffectiveCostRatePeriod.ANNUAL,
        )
        self.assertNotEqual(money(monthly), Decimal("2.00"))
        self.assertAlmostEqual(float(monthly), 1.808758, places=5)


class FinancingSchemaTest(unittest.TestCase):
    def test_invalid_direct_inputs_are_rejected(self):
        invalid_cases = (
            {"vehicle_price": 0},
            {"vehicle_price": -1},
            {"down_payment": -1},
            {"down_payment": 31000},
            {"term_months": 0},
            {"term_months": 121},
            {"monthly_interest_rate_percent": -1},
            {"monthly_interest_rate_percent": "Infinity"},
            {"financed_fees": -1},
            {"desired_max_installment": -1},
            {"available_monthly_budget": -1},
            {"estimated_monthly_vehicle_cost": -1},
            {"amortization_method": "sac"},
            {"vehicle_type": "truck"},
            {"offer_date": "31/12/2026"},
        )
        for changes in invalid_cases:
            with self.subTest(changes=changes):
                values = copy.deepcopy(DIRECT_PAYLOAD)
                values.update(changes)
                with self.assertRaises(ValidationError):
                    DirectFinancingRequest.model_validate(values)

    def test_rate_is_required_and_ambiguous_rate_is_rejected(self):
        missing = copy.deepcopy(DIRECT_PAYLOAD)
        missing.pop("monthly_interest_rate_percent")
        with self.assertRaises(ValidationError):
            DirectFinancingRequest.model_validate(missing)

        ambiguous = copy.deepcopy(DIRECT_PAYLOAD)
        ambiguous.update(
            {
                "effective_cost_rate_percent": 24,
                "effective_cost_rate_period": "annual",
                "effective_rate_includes_additional_costs": True,
            }
        )
        with self.assertRaises(ValidationError):
            DirectFinancingRequest.model_validate(ambiguous)

    def test_cet_requires_period_and_boolean(self):
        values = copy.deepcopy(DIRECT_PAYLOAD)
        values.pop("monthly_interest_rate_percent")
        values["effective_cost_rate_percent"] = 24
        with self.assertRaises(ValidationError):
            DirectFinancingRequest.model_validate(values)

        values.update(
            {
                "effective_cost_rate_period": "annual",
                "effective_rate_includes_additional_costs": "sim",
            }
        )
        with self.assertRaises(ValidationError):
            DirectFinancingRequest.model_validate(values)

    def test_manual_price_and_vehicle_id_cannot_be_ambiguous(self):
        values = copy.deepcopy(DIRECT_PAYLOAD)
        values["vehicle_id"] = 1
        with self.assertRaises(ValidationError):
            DirectFinancingRequest.model_validate(values)

        manual_and_negotiated = copy.deepcopy(DIRECT_PAYLOAD)
        manual_and_negotiated["negotiated_price"] = 25000
        with self.assertRaises(ValidationError):
            DirectFinancingRequest.model_validate(manual_and_negotiated)

        negotiated_without_catalog = copy.deepcopy(DIRECT_PAYLOAD)
        negotiated_without_catalog.pop("vehicle_price")
        negotiated_without_catalog["negotiated_price"] = 25000
        with self.assertRaises(ValidationError):
            DirectFinancingRequest.model_validate(negotiated_without_catalog)

    def test_cet_included_costs_reject_double_counting(self):
        values = copy.deepcopy(DIRECT_PAYLOAD)
        values.update(
            {
                "monthly_interest_rate_percent": None,
                "effective_cost_rate_percent": 24,
                "effective_cost_rate_period": "annual",
                "effective_rate_includes_additional_costs": True,
            }
        )
        with self.assertRaises(ValidationError):
            DirectFinancingRequest.model_validate(values)

        values["financed_fees"] = 0
        included = DirectFinancingRequest.model_validate(values)
        self.assertTrue(included.effective_rate_includes_additional_costs)

        values["effective_rate_includes_additional_costs"] = False
        values["financed_fees"] = 500
        separate = DirectFinancingRequest.model_validate(values)
        self.assertEqual(separate.financed_fees, Decimal("500"))

    def test_comparison_requires_two_and_accepts_at_most_ten(self):
        scenario = DirectFinancingRequest.model_validate(DIRECT_PAYLOAD)
        with self.assertRaises(ValidationError):
            FinancingComparisonRequest.model_validate({"scenarios": [scenario]})
        self.assertEqual(
            len(FinancingComparisonRequest.model_validate({"scenarios": [scenario] * 10}).scenarios),
            10,
        )
        with self.assertRaises(ValidationError):
            FinancingComparisonRequest.model_validate({"scenarios": [scenario] * 11})


class FinancingServiceTest(unittest.TestCase):
    def test_direct_result_separates_principal_costs_and_outflows(self):
        result = direct_result()
        self.assertEqual(result["financed_principal"], 20000.0)
        self.assertEqual(result["financed_additional_costs"], 500.0)
        self.assertEqual(result["total_financed_amount"], 20500.0)
        self.assertEqual(result["estimated_installment"], 778.67)
        self.assertEqual(result["regular_installment"], 778.67)
        self.assertEqual(result["maximum_installment_in_schedule"], 778.67)
        self.assertEqual(result["number_of_regular_installments"], 35)
        self.assertEqual(result["final_installment"], 778.62)
        self.assertEqual(result["total_installments"], 28032.07)
        self.assertEqual(result["total_acquisition_outflow"], 38032.07)
        self.assertEqual(result["total_interest_and_financed_costs"], 8032.07)
        self.assertEqual(result["difference_from_cash_price"], 8032.07)
        self.assertEqual(result["total_financing_addition"], 8032.07)
        self.assertEqual(result["interest_estimate"], 7532.07)
        self.assertEqual(result["total_monthly_outflow"], 1398.67)
        self.assertEqual(result["monthly_budget_remaining"], 201.33)
        self.assertEqual(result["compatibility_status"], "near_limit")
        self.assertEqual(result["overall_status"], "near_limit")
        self.assertEqual(result["price_source"], "manual")
        self.assertEqual(result["manual_price"], 30000.0)
        self.assertIsNone(result["catalog_price"])

    def test_upfront_and_financed_costs_have_different_effects(self):
        result = direct_result(
            {"upfront_fees": 300, "financed_fees": 200, "financed_insurance": 100, "financed_services": 50}
        )
        self.assertEqual(result["upfront_cost"], 10300.0)
        self.assertEqual(result["financed_additional_costs"], 350.0)
        self.assertEqual(result["total_financed_amount"], 20350.0)

    def test_equal_down_payment_requires_no_financing(self):
        result = direct_result(
            {
                "down_payment": 30000,
                "financed_fees": 0,
                "desired_max_installment": 0,
                "estimated_monthly_vehicle_cost": 500,
            }
        )
        self.assertEqual(result["estimated_installment"], 0.0)
        self.assertEqual(result["financing_status"], "zero_financing_required")
        self.assertEqual(result["monthly_budget_status"], "within_budget")
        self.assertEqual(result["overall_status"], "compatible")

        over_budget = direct_result(
            {
                "down_payment": 30000,
                "financed_fees": 0,
                "desired_max_installment": 0,
                "estimated_monthly_vehicle_cost": 1800,
                "available_monthly_budget": 1600,
            }
        )
        self.assertEqual(over_budget["financing_status"], "zero_financing_required")
        self.assertEqual(over_budget["monthly_budget_status"], "over_monthly_budget")
        self.assertEqual(over_budget["overall_status"], "over_monthly_budget")

    def test_compatibility_states(self):
        compatible = direct_result({"available_monthly_budget": 2500, "desired_max_installment": 1200})
        self.assertEqual(compatible["compatibility_status"], "compatible")
        installment = direct_result({"available_monthly_budget": 3000, "desired_max_installment": 700})
        self.assertEqual(installment["compatibility_status"], "over_installment_limit")
        monthly = direct_result({"available_monthly_budget": 1300, "desired_max_installment": 1200})
        self.assertEqual(monthly["compatibility_status"], "over_monthly_budget")
        incomplete = direct_result({"available_monthly_budget": None, "desired_max_installment": None})
        self.assertEqual(incomplete["compatibility_status"], "insufficient_input")
        self.assertIsNotNone(incomplete["total_monthly_outflow"])
        self.assertIsNone(incomplete["monthly_budget_remaining"])

    def test_cet_annual_is_converted_without_decomposition(self):
        result = direct_result(
            {
                "monthly_interest_rate_percent": None,
                "effective_cost_rate_percent": 21.6,
                "effective_cost_rate_period": "annual",
                "effective_rate_includes_additional_costs": True,
                "financed_fees": 0,
            }
        )
        self.assertEqual(result["rate"]["input_mode"], "informed_effective_cost_rate")
        self.assertGreater(result["rate"]["effective_monthly_rate_percent"], 1.6)
        self.assertIn("não foi decomposto", result["rate"]["note"])
        self.assertFalse(result["additional_costs_considered_separately"])
        self.assertIsNone(result["interest_estimate"])

    def test_reverse_simulation_and_insufficient_installment(self):
        payload = ReverseFinancingRequest.model_validate(
            {
                "vehicle_type": "car",
                "down_payment": 8000,
                "maximum_installment": 900,
                "term_months": 36,
                "monthly_interest_rate_percent": 1.8,
                "upfront_fees": 0,
                "financed_fees": 500,
                "financed_insurance": 0,
                "financed_services": 0,
                "available_monthly_budget": 1600,
                "estimated_monthly_vehicle_cost": 600,
            }
        )
        result = simulate_reverse(payload)
        self.assertEqual(result["estimated_installment"], 899.97)
        self.assertEqual(result["maximum_installment_in_schedule"], 899.99)
        self.assertEqual(result["maximum_vehicle_price"], 31193.52)
        self.assertEqual(result["total_monthly_outflow"], 1499.99)
        self.assertTrue(result["installment_within_user_limit"])
        self.assertEqual(result["compatibility_status"], "near_limit")
        self.assertEqual(result["regular_installment"], 899.97)
        self.assertEqual(result["final_installment"], 899.99)
        self.assertAlmostEqual(
            result["regular_installment"] * result["number_of_regular_installments"] + result["final_installment"],
            result["total_installments"],
            places=2,
        )

        low = payload.model_copy(
            update={"maximum_installment": Decimal("10"), "financed_fees": Decimal("1000")}
        )
        low_result = simulate_reverse(low)
        self.assertEqual(low_result["maximum_vehicle_price"], 8000.0)
        self.assertEqual(low_result["required_financed_additional_costs"], 1000.0)
        self.assertEqual(low_result["available_vehicle_principal"], 0.0)
        self.assertEqual(low_result["financed_additional_costs"], 0.0)
        self.assertEqual(low_result["total_financed_amount"], 0.0)
        self.assertEqual(low_result["financing_status"], "insufficient_for_financed_costs")
        self.assertEqual(low_result["overall_status"], "insufficient_for_financed_costs")
        self.assertTrue(any("custos adicionais" in item for item in low_result["warnings"]))

    def test_direct_uses_largest_displayed_installment_for_limit(self):
        result = direct_result(
            {
                "vehicle_price": 100.05,
                "down_payment": 0,
                "financed_fees": 0,
                "desired_max_installment": 3.80,
                "available_monthly_budget": 1000,
                "estimated_monthly_vehicle_cost": 0,
            }
        )
        self.assertEqual(result["regular_installment"], 3.80)
        self.assertEqual(result["final_installment"], 3.81)
        self.assertEqual(result["maximum_installment_in_schedule"], 3.81)
        self.assertFalse(result["installment_within_user_limit"])
        self.assertEqual(result["financing_status"], "over_installment_limit")

    def test_comparison_uses_neutral_criteria_labels(self):
        first = direct_result({"offer_name": "Banco A"})
        first["scenario_name"] = "Banco A"
        second = direct_result({"offer_name": "Banco B", "term_months": 48})
        second["scenario_name"] = "Banco B"
        comparison = compare_results([first, second])
        self.assertEqual(comparison["scenario_count"], 2)
        self.assertIn("Banco B", comparison["highlights"]["lowest_installment"])
        self.assertIn("Banco A", comparison["highlights"]["shortest_term"])
        self.assertEqual(len(comparison["highlights"]), 7)
        self.assertIn("lowest_total_installments", comparison["highlights"])
        self.assertNotIn("lowest_interest_and_financed_costs", comparison["highlights"])
        self.assertIn("lowest_interest_and_financed_costs", comparison["legacy_highlights"])
        self.assertIn("value", comparison["highlight_details"]["lowest_installment"])
        self.assertIn("difference_to_next", comparison["highlight_details"]["lowest_installment"])
        self.assertNotIn("best", comparison)
        self.assertIn("não elegem", comparison["warnings"][0])

    def _results_for_context(self, first_updates=None, second_updates=None):
        first = direct_result({"offer_name": "A"})
        second = direct_result({"offer_name": "B"})
        first["scenario_name"] = "A"
        second["scenario_name"] = "B"
        first.update(first_updates or {})
        second.update(second_updates or {})
        return first, second

    def test_financial_context_comparability_statuses(self):
        cases = (
            ({}, {}, True, True, "comparable"),
            (
                {},
                {"available_monthly_budget": 3200.0, "budget_commitment_percentage": 43.71},
                False,
                True,
                "different_monthly_budgets",
            ),
            (
                {},
                {
                    "estimated_monthly_vehicle_cost": 700.0,
                    "total_monthly_outflow": 1478.67,
                    "budget_commitment_percentage": 92.42,
                },
                True,
                False,
                "different_vehicle_cost_bases",
            ),
            (
                {},
                {
                    "available_monthly_budget": 3200.0,
                    "estimated_monthly_vehicle_cost": 700.0,
                    "total_monthly_outflow": 1478.67,
                    "budget_commitment_percentage": 46.21,
                },
                False,
                False,
                "different_budget_and_vehicle_cost",
            ),
            (
                {},
                {"available_monthly_budget": None, "budget_commitment_percentage": None},
                None,
                True,
                "insufficient_budget_data",
            ),
            (
                {},
                {
                    "estimated_monthly_vehicle_cost": None,
                    "total_monthly_outflow": None,
                    "budget_commitment_percentage": None,
                },
                True,
                None,
                "insufficient_vehicle_cost_data",
            ),
            (
                {
                    "available_monthly_budget": None,
                    "estimated_monthly_vehicle_cost": None,
                    "total_monthly_outflow": None,
                    "budget_commitment_percentage": None,
                },
                {
                    "available_monthly_budget": None,
                    "estimated_monthly_vehicle_cost": None,
                    "total_monthly_outflow": None,
                    "budget_commitment_percentage": None,
                },
                None,
                None,
                "insufficient_financial_context",
            ),
        )
        for first_updates, second_updates, same_budget, same_cost, status in cases:
            with self.subTest(status=status):
                comparison = compare_results(
                    list(self._results_for_context(first_updates, second_updates))
                )
                context = comparison["comparison_context"]
                self.assertIs(context["same_monthly_budget_basis"], same_budget)
                self.assertIs(context["same_vehicle_cost_basis"], same_cost)
                self.assertEqual(context["monthly_commitment_comparison_status"], status)
                self.assertEqual(
                    context["financial_context_comparable"], status == "comparable"
                )

    def test_monthly_commitment_is_suppressed_only_when_context_differs(self):
        equivalent = compare_results(list(self._results_for_context()))
        self.assertIn("lowest_budget_commitment", equivalent["highlights"])
        self.assertEqual(equivalent["suppressed_highlights"], [])

        first, second = self._results_for_context(
            second_updates={
                "available_monthly_budget": 3200.0,
                "budget_commitment_percentage": 43.71,
            }
        )
        different = compare_results([first, second])
        self.assertNotIn("lowest_budget_commitment", different["highlights"])
        self.assertEqual(
            different["suppressed_highlights"],
            [
                {
                    "criterion": "lowest_budget_commitment",
                    "reason": "different_monthly_budgets",
                }
            ],
        )
        self.assertEqual(
            [item["budget_commitment_percentage"] for item in different["scenarios"]],
            [87.42, 43.71],
        )
        self.assertTrue(any("orçamentos mensais diferentes" in item for item in different["warnings"]))

    def test_explicit_zero_vehicle_cost_is_not_treated_as_missing(self):
        first = direct_result({"offer_name": "A", "estimated_monthly_vehicle_cost": 0})
        second = direct_result({"offer_name": "B", "estimated_monthly_vehicle_cost": 0})
        first["scenario_name"] = "A"
        second["scenario_name"] = "B"
        context = compare_results([first, second])["comparison_context"]
        self.assertIs(context["same_vehicle_cost_basis"], True)
        self.assertTrue(context["financial_context_comparable"])

    def test_comparison_uses_canonical_financing_addition_internally(self):
        first, second = self._results_for_context(
            second_updates={"total_financing_addition": 9000.0}
        )
        comparison = compare_results([first, second])
        difference = comparison["differences_from_first_scenario"][0]
        self.assertEqual(
            difference["interest_and_costs_difference"],
            difference["total_financing_addition_difference"],
        )
        self.assertIn("lowest_interest_and_financed_costs", comparison["legacy_highlights"])
        self.assertNotIn(
            'result["total_interest_and_financed_costs"]',
            inspect.getsource(compare_results),
        )

    def test_comparison_describes_vehicle_and_price_scope(self):
        first = direct_result({"offer_name": "A"})
        second = direct_result({"offer_name": "B"})
        first.update({"scenario_name": "A", "vehicle": {"id": 1, "vehicle_type": "car"}, "price_source": "catalog"})
        second.update({"scenario_name": "B", "vehicle": {"id": 1, "vehicle_type": "car"}, "price_source": "catalog"})
        self.assertEqual(compare_results([first, second])["comparison_scope"], "same_vehicle_same_price")

        second["price_used"] = second["price_used"] - 1000
        second["price_source"] = "negotiated"
        different_price = compare_results([first, second])
        self.assertEqual(different_price["comparison_scope"], "same_vehicle_different_price")
        self.assertGreaterEqual(len(different_price["warnings"]), 2)

        second.update({"vehicle": {"id": 2, "vehicle_type": "car"}, "price_source": "catalog"})
        self.assertEqual(compare_results([first, second])["comparison_scope"], "different_vehicles")

        second.update({"vehicle": None, "price_source": "manual"})
        self.assertEqual(compare_results([first, second])["comparison_scope"], "mixed_manual_and_catalog")

    def test_comparison_exposes_ties_without_collapsing_winners(self):
        first = direct_result({"offer_name": "A"})
        second = direct_result({"offer_name": "B"})
        first["scenario_name"] = "A"
        second["scenario_name"] = "B"
        detail = compare_results([first, second])["highlight_details"]["highest_down_payment"]
        self.assertTrue(detail["is_tie"])
        self.assertEqual(detail["scenario_names"], ["A", "B"])
        self.assertIsNone(detail["difference_to_next"])

    def test_additional_cost_flags_distinguish_zero_separate_and_cet(self):
        no_cost = direct_result({"financed_fees": 0})
        self.assertFalse(no_cost["has_financed_additional_costs"])

        separate = direct_result({"financed_fees": 500})
        self.assertTrue(separate["has_financed_additional_costs"])
        self.assertTrue(separate["additional_costs_considered_separately"])

        cet = direct_result(
            {
                "monthly_interest_rate_percent": None,
                "effective_cost_rate_percent": 24,
                "effective_cost_rate_period": "annual",
                "effective_rate_includes_additional_costs": True,
                "financed_fees": 0,
            }
        )
        self.assertFalse(cet["has_financed_additional_costs"])
        self.assertFalse(cet["additional_costs_considered_separately"])


class FinancingInvariantTest(unittest.TestCase):
    def test_direct_monotonic_invariants(self):
        lower_entry = direct_result({"down_payment": 5000})
        higher_entry = direct_result({"down_payment": 10000})
        self.assertLessEqual(higher_entry["regular_installment"], lower_entry["regular_installment"])

        lower_rate = direct_result({"monthly_interest_rate_percent": 1})
        higher_rate = direct_result({"monthly_interest_rate_percent": 2})
        self.assertGreaterEqual(higher_rate["regular_installment"], lower_rate["regular_installment"])

        shorter = direct_result({"term_months": 24})
        longer = direct_result({"term_months": 48})
        self.assertLessEqual(longer["regular_installment"], shorter["regular_installment"])

        no_cost = direct_result({"financed_fees": 0})
        with_cost = direct_result({"financed_fees": 1000})
        self.assertGreaterEqual(with_cost["regular_installment"], no_cost["regular_installment"])

    def test_zero_rate_divides_principal_by_term(self):
        result = direct_result(
            {"monthly_interest_rate_percent": 0, "financed_fees": 0, "term_months": 20}
        )
        self.assertEqual(result["regular_installment"], 1000.0)
        self.assertEqual(result["total_installments"], 20000.0)

    def _reverse(self, **overrides):
        values = {
            "vehicle_type": "car",
            "down_payment": 8000,
            "maximum_installment": 900,
            "term_months": 36,
            "monthly_interest_rate_percent": 1.8,
            "upfront_fees": 0,
            "financed_fees": 500,
            "financed_insurance": 0,
            "financed_services": 0,
            "available_monthly_budget": 1600,
            "estimated_monthly_vehicle_cost": 600,
        }
        values.update(overrides)
        return simulate_reverse(ReverseFinancingRequest.model_validate(values))

    def test_reverse_monotonic_invariants(self):
        self.assertGreaterEqual(
            self._reverse(down_payment=12000)["maximum_vehicle_price"],
            self._reverse(down_payment=8000)["maximum_vehicle_price"],
        )
        self.assertLessEqual(
            self._reverse(monthly_interest_rate_percent=2.5)["maximum_financed_amount"],
            self._reverse(monthly_interest_rate_percent=1)["maximum_financed_amount"],
        )
        self.assertGreaterEqual(
            self._reverse(term_months=48)["maximum_financed_amount"],
            self._reverse(term_months=24)["maximum_financed_amount"],
        )
        self.assertLessEqual(
            self._reverse(financed_fees=1000)["maximum_vehicle_price"],
            self._reverse(financed_fees=0)["maximum_vehicle_price"],
        )
        self.assertLessEqual(
            self._reverse(maximum_installment=600)["maximum_vehicle_price"],
            self._reverse(maximum_installment=900)["maximum_vehicle_price"],
        )

    def test_reverse_zero_installment_is_controlled_and_non_negative(self):
        result = self._reverse(maximum_installment=0, financed_fees=500)
        self.assertEqual(result["maximum_financed_amount"], 0.0)
        self.assertEqual(result["maximum_vehicle_price"], 8000.0)
        self.assertGreaterEqual(result["maximum_vehicle_price"], 0)
        self.assertEqual(result["financing_status"], "insufficient_for_financed_costs")
        self.assertEqual(result["regular_installment"], 0.0)

        no_cost = self._reverse(maximum_installment=0, financed_fees=0)
        self.assertEqual(no_cost["financing_status"], "zero_financing_required")


if __name__ == "__main__":
    unittest.main()
