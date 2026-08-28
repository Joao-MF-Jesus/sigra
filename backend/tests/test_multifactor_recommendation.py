from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.main import RecommendationRequest
from app.multifactor_recommendation import (
    LEGACY_QUALITY_COMPONENTS,
    MULTIFACTOR_COMPONENTS,
    apply_multifactor_ranking,
)
from app.multifactor_schemas import MultifactorWeights
from data_platform.contracts.integrated_vehicle_cost import FuelScenarioCode
from data_platform.integrated_vehicle_cost.simulation_contracts import (
    FuelStrategy,
    SimulationEvidenceOrigin,
    SimulationSourceVersions,
    VehicleCostSimulationBatch,
    VehicleCostSimulationResult,
    VehicleCostSimulationScenario,
)


def _scenario() -> VehicleCostSimulationScenario:
    return VehicleCostSimulationScenario(
        monthly_distance_km=Decimal("1250.00"),
        city_percentage=Decimal("60.00"),
        highway_percentage=Decimal("40.00"),
        state_code="SP",
        municipality="Sao Paulo",
        reference_week_start=date(2026, 8, 17),
        fuel_strategy=FuelStrategy.GASOLINE_C_COMMON,
        horizon_months=18,
    )


def _gold_result(
    vehicle_sk: int,
    brand: str,
    model: str,
    year: int,
    *,
    monthly_cost: str,
    efficiency: str,
) -> VehicleCostSimulationResult:
    monthly = Decimal(monthly_cost)
    return VehicleCostSimulationResult(
        rank=vehicle_sk,
        vehicle_sk=vehicle_sk,
        brand_name=brand,
        model_name=model,
        version_name=None,
        model_year=year,
        fuel_code=FuelScenarioCode.GASOLINE_C_COMMON,
        city_consumption_km_l=Decimal("10.0000"),
        highway_consumption_km_l=Decimal("14.0000"),
        weighted_consumption_km_l=Decimal(efficiency),
        estimated_monthly_liters=Decimal("100.0000"),
        estimated_annual_liters=Decimal("1200.0000"),
        monthly_fuel_cost_brl=monthly,
        annual_fuel_cost_brl=monthly * Decimal("12"),
        fuel_cost_per_km_brl=monthly / Decimal("1250"),
        fuel_price_per_liter_brl=Decimal("6.0000"),
        fuel_price_origin=SimulationEvidenceOrigin.ANP_GOLD,
        city_consumption_origin=SimulationEvidenceOrigin.PBEV_GOLD,
        highway_consumption_origin=SimulationEvidenceOrigin.PBEV_GOLD,
        canonical_comparison_origin=SimulationEvidenceOrigin.CANONICAL_POLICY,
        horizon_months=18,
        projected_horizon_cost_brl=monthly * Decimal("18"),
        canonical_scenario_code="mixed_1000_v1",
        canonical_monthly_distance_km=Decimal("1000.00"),
        canonical_monthly_fuel_cost_brl=Decimal("500.0000"),
        canonical_annual_fuel_cost_brl=Decimal("6000.0000"),
        monthly_cost_difference_brl=monthly - Decimal("500.0000"),
        monthly_cost_difference_percentage=Decimal("0.00"),
        state_code="SP",
        municipality="Sao Paulo",
        anp_week_start=date(2026, 8, 17),
        anp_week_end=date(2026, 8, 23),
        sources=SimulationSourceVersions("integrated-v1", "fipe-v1", "pbev-v1", "anp-v1"),
        simulation_policy_version="user-configurable-vehicle-cost-v1",
        warnings=(),
        limitations=("FUEL_COST_ONLY",),
    )


def _batch(*results: VehicleCostSimulationResult) -> VehicleCostSimulationBatch:
    return VehicleCostSimulationBatch(
        scenario=_scenario(),
        results=tuple(results),
        exclusions=(),
        evaluated_vehicle_count=len(results),
        eligible_vehicle_count=len(results),
        excluded_vehicle_count=0,
        returned_vehicle_count=len(results),
        fingerprint="f" * 64,
    )


def _baseline(
    vehicle_id: int,
    brand: str,
    model: str,
    year: int,
    score: str,
    *,
    comfort=70,
) -> dict:
    return {
        "vehicle": {
            "id": vehicle_id,
            "brand": brand,
            "model": model,
            "year": year,
            "comfort_score": comfort,
            "safety_score": 80,
            "road_score": 75,
        },
        "score": Decimal(score),
        "final_score": Decimal(score),
        "is_best_choice": vehicle_id == 1,
        "is_best_available_reference": False,
        "score_components": {
            "financial_score": 60,
            "tco_score": 55,
            "usage_score": 85 if vehicle_id == 1 else 75,
            "maintenance_score": 80,
            "reliability_score": 82,
            "parts_score": 78,
            "resale_score": 76,
            "segment_score": 79,
            "purchase_intent_score": 77,
        },
    }


def _weights(**changes) -> dict[str, Decimal]:
    values = {code: Decimal("1") for code in MULTIFACTOR_COMPONENTS}
    values.update({key: Decimal(str(value)) for key, value in changes.items()})
    return values


def test_equal_weights_are_deterministic_and_reconcile_exactly():
    baseline = [
        _baseline(1, "Volkswagen", "Polo", 2024, "81.00"),
        _baseline(2, "Toyota", "Corolla", 2024, "80.00"),
    ]
    simulation = _batch(
        _gold_result(101, "VW - Volkswagen", "Polo", 2024, monthly_cost="600.0000", efficiency="12.0000"),
        _gold_result(102, "Toyota", "Corolla", 2024, monthly_cost="500.0000", efficiency="11.0000"),
    )
    first = apply_multifactor_ranking(baseline, simulation, _weights())
    second = apply_multifactor_ranking(baseline, simulation, _weights())

    assert first == second
    assert [item["multifactor"]["position"] for item in first] == [1, 2]
    for item in first:
        components = item["multifactor"]["components"]
        assert sum(row["contribution"] for row in components) == item["multifactor"]["final_score"]
        assert sum(row["normalized_weight_percentage"] for row in components) == Decimal("100.0000")
        assert item["multifactor"]["scenario_fingerprint"] == "f" * 64


def test_cost_weight_changes_only_weighting_not_raw_evidence_or_scenario():
    baseline = [
        _baseline(1, "A", "One", 2024, "81"),
        _baseline(2, "B", "Two", 2024, "80"),
    ]
    simulation = _batch(
        _gold_result(1, "A", "One", 2024, monthly_cost="700", efficiency="10"),
        _gold_result(2, "B", "Two", 2024, monthly_cost="500", efficiency="13"),
    )
    equal = apply_multifactor_ranking(baseline, simulation, _weights())
    cost_heavy = apply_multifactor_ranking(baseline, simulation, _weights(total_cost=Decimal("50")))

    equal_by_id = {item["vehicle"]["id"]: item for item in equal}
    cost_by_id = {item["vehicle"]["id"]: item for item in cost_heavy}
    for vehicle_id in equal_by_id:
        left = equal_by_id[vehicle_id]["multifactor"]
        right = cost_by_id[vehicle_id]["multifactor"]
        assert [row["raw_score"] for row in left["components"]] == [
            row["raw_score"] for row in right["components"]
        ]
        assert left["cost"] == right["cost"]
        assert left["scenario_fingerprint"] == right["scenario_fingerprint"]


def test_financial_fields_are_not_double_counted_in_legacy_quality():
    assert "financial_score" not in LEGACY_QUALITY_COMPONENTS
    assert "tco_score" not in LEGACY_QUALITY_COMPONENTS
    assert "usage_score" not in LEGACY_QUALITY_COMPONENTS
    assert "segment_score" not in LEGACY_QUALITY_COMPONENTS
    assert "purchase_intent_score" not in LEGACY_QUALITY_COMPONENTS


def test_tie_breaker_is_stable_by_baseline_position_then_vehicle_id():
    baseline = [
        _baseline(2, "B", "Two", 2024, "80"),
        _baseline(1, "A", "One", 2024, "80"),
    ]
    simulation = _batch(
        _gold_result(1, "A", "One", 2024, monthly_cost="500", efficiency="12"),
        _gold_result(2, "B", "Two", 2024, monthly_cost="500", efficiency="12"),
    )
    baseline[0]["score_components"]["usage_score"] = 80
    baseline[1]["score_components"]["usage_score"] = 80
    ranked = apply_multifactor_ranking(baseline, simulation, _weights())
    assert [item["vehicle"]["id"] for item in ranked] == [2, 1]
    assert ranked[0]["multifactor"]["tie_breakers"] == (
        "higher_multifactor_score",
        "better_baseline_position",
        "lower_vehicle_id",
    )


def test_ambiguous_and_missing_gold_identity_never_use_fallback():
    baseline = [
        _baseline(1, "A", "One", 2024, "80"),
        _baseline(2, "B", "Missing", 2024, "79"),
    ]
    simulation = _batch(
        _gold_result(10, "A", "One", 2024, monthly_cost="500", efficiency="12"),
        _gold_result(11, "A", "One", 2024, monthly_cost="510", efficiency="12"),
    )
    ranked = apply_multifactor_ranking(baseline, simulation, _weights())
    reasons = {item["vehicle"]["id"]: item["multifactor"]["reason_code"] for item in ranked}
    assert reasons == {1: "GOLD_IDENTITY_AMBIGUOUS", 2: "GOLD_IDENTITY_NOT_FOUND"}
    assert all(item["multifactor"]["final_score"] is None for item in ranked)


def test_missing_comfort_is_unavailable_instead_of_becoming_zero():
    baseline = [_baseline(1, "A", "One", 2024, "80", comfort=None)]
    simulation = _batch(
        _gold_result(1, "A", "One", 2024, monthly_cost="500", efficiency="12")
    )
    ranked = apply_multifactor_ranking(baseline, simulation, _weights())
    assert ranked[0]["multifactor"]["status"] == "unavailable"
    assert ranked[0]["multifactor"]["reason_code"] == "MULTIFACTOR_EVIDENCE_UNAVAILABLE"
    assert "comfort" in ranked[0]["multifactor"]["detail"]


@pytest.mark.parametrize(
    "value",
    [-1, "NaN", "Infinity", True, 1.5, 101],
)
def test_invalid_weights_are_rejected(value):
    payload = {code: "1" for code in MULTIFACTOR_COMPONENTS}
    payload["comfort"] = value
    with pytest.raises(ValidationError):
        MultifactorWeights.model_validate(payload)


def test_all_zero_weights_are_rejected():
    with pytest.raises(ValidationError):
        MultifactorWeights.model_validate({code: "0" for code in MULTIFACTOR_COMPONENTS})


def test_zero_weights_remain_zero_after_percentage_reconciliation():
    baseline = [_baseline(1, "A", "One", 2024, "80")]
    simulation = _batch(
        _gold_result(1, "A", "One", 2024, monthly_cost="500", efficiency="12")
    )
    weights = {code: Decimal("0") for code in MULTIFACTOR_COMPONENTS}
    weights["total_cost"] = Decimal("1")
    ranked = apply_multifactor_ranking(baseline, simulation, weights)
    percentages = {
        row["component"]: row["normalized_weight_percentage"]
        for row in ranked[0]["multifactor"]["components"]
    }
    assert percentages["total_cost"] == Decimal("100.0000")
    assert all(
        percentages[code] == Decimal("0.0000")
        for code in MULTIFACTOR_COMPONENTS
        if code != "total_cost"
    )


def _request_payload(budget=200_000, allow=False):
    return {
        "budget": budget,
        "monthly_limit": 3000,
        "use_case": "cidade",
        "multifactor_profile": {
            "enabled": True,
            "allow_budget_above_200k": allow,
            "scenario": {
                "monthly_distance_km": "1250.00",
                "city_percentage": "60.00",
                "highway_percentage": "40.00",
                "state_code": "SP",
                "municipality": "Sao Paulo",
                "reference_week_start": "2026-08-17",
                "fuel_strategy": "gasoline_c_common",
                "horizon_months": 18,
            },
            "weights": {code: "1" for code in MULTIFACTOR_COMPONENTS},
        },
    }


def test_budget_above_200k_requires_explicit_authorization():
    with pytest.raises(ValidationError):
        RecommendationRequest.model_validate(_request_payload(250_000, allow=False))
    accepted = RecommendationRequest.model_validate(_request_payload(250_000, allow=True))
    assert accepted.budget == 250_000


def test_legacy_request_remains_unchanged_without_opt_in():
    request = RecommendationRequest.model_validate(
        {"budget": 70_000, "monthly_limit": 1200, "use_case": "cidade"}
    )
    assert request.multifactor_profile is None
    assert request.model_dump(exclude_none=True) == {
        "vehicle_type": "car",
        "budget": 70_000.0,
        "monthly_limit": 1200.0,
        "use_case": "cidade",
        "monthly_mileage": 1000.0,
        "fuel_price": 6.0,
        "recommendation_strategy": "cost_benefit",
    }
