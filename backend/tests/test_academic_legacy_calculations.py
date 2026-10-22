"""Original formula parity; partial scenario notes never fill historical gaps."""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.academic_cohort.legacy_calculations import calculate_legacy_subcriteria
from app.academic_cohort.recommendation import recommend_academic
from app.recommender import build_score_components, normalize_cost
from backend.tests.test_academic_recommendation import service, request
from backend.tests.test_academic_personalization import personalization


def evaluation(price, rate, maintenance=1500):
    def component(inputs):
        return {"value": "1", "unit": "BRL/month", "nature": "scenario_estimate",
                "method_version": "academic_cost_scenario_v1", "inputs": inputs,
                "source_evidence": [{"provider": "fipe", "sha256": "a" * 64}]}
    return {"scenario_costs": {"components": {
        "maintenance": component({"fixed_annual_brl": {"value": maintenance, "unit": "BRL/year", "nature": "scenario_parameter"}}),
        "depreciation": component({"price_brl": {"value": price, "unit": "BRL", "nature": "observed"},
                                    "annual_rate": {"value": rate, "unit": "fraction/year", "nature": "scenario_parameter"}})}}}


@pytest.mark.parametrize("annual", [0, 1500, 3200, 7000, 9000])
def test_exact_parity_with_original_score_components(annual):
    inputs = {1: evaluation(70000, .10, annual), 2: evaluation(40000, .06, 2600)}
    recovered = calculate_legacy_subcriteria(inputs)[1]
    vehicle = SimpleNamespace(annual_maintenance_cost=annual, depreciation_rate=.10,
                              price=70000, reliability_score=70, parts_availability_score=80,
                              use_cases={"app"}, app_score=75, urban_score=70,
                              family_score=70, space_score=70, road_score=70, comfort_score=70)
    profile = SimpleNamespace(use_case="app", monthly_limit=1800, budget=70000)
    original = build_score_components({"maintenance_cost": normalize_cost(annual, min(annual, 2600), max(annual, 2600)),
        "depreciation": normalize_cost(.10, .06, .10), "tco": 70, "reliability": 70, "profile_fit": 100},
        60, 60, vehicle, profile, {"total_monthly_cost": 1600})
    for key in ("maintenance_score", "resale_score"):
        assert recovered["score_components"][key] == Decimal(str(original[key]))
        assert recovered["calculations"][key]["nature"] == "scenario_estimate"
        assert recovered["calculations"][key]["historical_observation_claimed"] is False
    assert recovered["score_components"]["reliability_score"] is None
    assert recovered["score_components"]["parts_score"] is None


def test_equal_range_original_rule_idempotence_and_no_input_mutation():
    inputs = {1: evaluation(70000, .10), 2: evaluation(40000, .10)}
    before = deepcopy(inputs)
    result = calculate_legacy_subcriteria(inputs)
    assert result == calculate_legacy_subcriteria(inputs)
    assert inputs == before
    assert result[1]["score_components"]["resale_score"] == 100
    assert result[1]["calculations"]["resale_score"]["normalization_range"] == (.1, .1)


@pytest.mark.parametrize("field,value", [("unit", "BRL/year"), ("nature", "observed"), ("method_version", "invented")])
def test_invalid_component_contract_fails_closed(field, value):
    inputs = {1: evaluation(70000, .10)}
    inputs[1]["scenario_costs"]["components"]["maintenance"][field] = value
    with pytest.raises(ValueError):
        calculate_legacy_subcriteria(inputs)


@pytest.mark.parametrize("rate", [-1, "NaN", "Infinity", 10, True])
def test_invalid_rate_fails_closed(rate):
    with pytest.raises(ValueError):
        calculate_legacy_subcriteria({1: evaluation(70000, rate)})


def test_absence_not_zero_and_annual_not_reconstructed_from_rounded_month():
    inputs = {1: evaluation(70000, .10)}
    inputs[1]["scenario_costs"]["components"]["maintenance"]["value"] = None
    result = calculate_legacy_subcriteria(inputs)[1]
    assert result["score_components"]["maintenance_score"] is None
    assert "maintenance_score" in result["missing_quality_inputs"]
    assert result["calculations"]["resale_score"]["inputs"]["annual_brl"] == 7000


def test_filters_do_not_change_subcriterion_normalization_or_create_quality(service):
    mf = personalization()
    full = recommend_academic(service, request(service, multifactor_profile=mf))
    filtered = recommend_academic(service, request(service, budget=43000, multifactor_profile=mf))
    origin = {row["vehicle"]["catalog_id"]: row for row in full["recommendations"]}
    for row in filtered["recommendations"]:
        assert row["score_components"] == origin[row["vehicle"]["catalog_id"]]["score_components"]
        assert row["multifactor"]["final_score"] is None
        assert row["quality_complete"] is False
        assert row["evaluation"]["observed_tco_complete"] is False
        assert row["calculations"]["maintenance_score"]["normalization_population"] == list(range(1, 61))
    assert full["operationally_active"] is full["recommended"] is False
