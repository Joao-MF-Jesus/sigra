"""Fictitious observations only; no database, credentials or external source."""
from copy import deepcopy
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.academic_cohort import derived_personalization as method
from app.academic_cohort.personalization import personalized_fuel
from app.academic_cohort.recommendation import live_evaluation, recommend_academic, validated_weights, recommendation_method
from app.multifactor_schemas import DEFAULT_MULTIFACTOR_WEIGHTS, MultifactorRecommendationProfile
from backend.tests.test_academic_recommendation import synthetic_vehicle, service, request
from backend.tests.test_academic_personalization import personalization
from data_platform.catalog.profile_contracts_v3 import observed, unavailable
from data_platform.catalog.profile_scoring_v3 import criterion_values


@pytest.fixture(autouse=True)
def enable_only_this_test_process(monkeypatch):
    monkeypatch.setenv("SIGRA_DERIVED_PERSONALIZATION_ENABLED", "true")


def profile(weights=None, **changes):
    value = personalization(**changes)
    value["policy_version"] = method.VERSION
    if weights is not None:
        value["weights"] = weights
    return value


def metrics(vehicle=None, **changes):
    vehicle = vehicle or synthetic_vehicle(1)
    scenario = MultifactorRecommendationProfile.model_validate(profile(**changes)).scenario.to_contract()
    simulated, error = personalized_fuel(vehicle, scenario)
    assert error is None
    evaluation = live_evaluation(vehicle, "app", "base", Decimal(1000), Decimal(6), validated_weights("app", None))
    return method.measurements(vehicle, evaluation, simulated, scenario, documentary_eligible=True), scenario, evaluation


def row(identifier, score=50):
    return {"vehicle": {"catalog_id": identifier}, "score": Decimal(score), "comparison_group": "same"}


def only(key):
    return {k: "100" if k == key else "0" for k in DEFAULT_MULTIFACTOR_WEIGHTS}


def test_disabled_by_default_and_explicit_selection_required(service, monkeypatch):
    monkeypatch.delenv("SIGRA_DERIVED_PERSONALIZATION_ENABLED")
    assert not method.enabled() and not recommendation_method()["alternative_personalization"]["available"]
    with pytest.raises(ValidationError, match="desabilitada"):
        request(service, multifactor_profile=profile())
    monkeypatch.setenv("SIGRA_DERIVED_PERSONALIZATION_ENABLED", "true")
    with pytest.raises(ValueError):
        method.validate_selection(method.VERSION, "operational")
    with pytest.raises(ValueError):
        method.validate_selection("invented-version", "academic_v6")
    assert request(service, multifactor_profile=personalization()).multifactor_profile.policy_version == method.REFERENCE


def test_transparent_inputs_and_expected_formulas():
    values, scenario, evaluation = metrics()
    city = Decimal(11)
    fuel = ((Decimal(500) / city + Decimal(500) / 15) * 6).quantize(Decimal("0.0001"))
    assert values["total_cost"]["value"] == fuel * 12
    assert abs(values["efficiency"]["value"] - 1 / (Decimal("0.5") / city + Decimal("0.5") / 15)) < Decimal("0.0001")
    assert values["performance"]["value"] == Decimal(1200) / 110
    assert values["comfort"]["value"] == 255
    assert values["usage_fit"]["value"] == 100
    assert values["safety"]["value"] == 100
    rates = evaluation["scenario_costs"]["components"]
    expected = sum(Decimal(rates[key]["inputs"]["annual_rate"]["value"]) * Decimal(41000)
                   for key in ("maintenance", "depreciation")) / 12
    assert values["legacy_quality"]["value"] == expected
    assert values["legacy_quality"]["nature"] == "scenario_estimate"
    annual = values["legacy_quality"]["inputs_used"]["maintenance"]
    assert annual["unit"] == "BRL/year" and annual["formula"] == "annual_rate * observed_FIPE_price"
    assert annual["source_monthly_component"]["unit"] == "BRL/month"
    assert annual["sources"] == annual["source_monthly_component"]["source_evidence"]
    assert values["performance"]["inputs_used"]["weight_kg"]["sources"]


def test_existing_safety_formula_explicit_false_and_zero_are_not_unknown():
    vehicle = synthetic_vehicle(1)
    fields = dict(vehicle.fields)
    for name, value in (("airbags", "2"), ("abs", True), ("esc", False)):
        fields[name] = observed(name, value, fields[name].sources)
    vehicle = vehicle.model_copy(update={"fields": fields})
    values, scenario, _ = metrics(vehicle)
    inherited = criterion_values(vehicle, {"urban_fuel_for_scenario": None, "proven_operating_cost": None}, {"transmission_preference": None})
    assert values["safety"]["value"] == inherited["safety"]
    assert values["safety"]["value"].quantize(Decimal("0.0001")) == (Decimal(400) / 9).quantize(Decimal("0.0001"))
    result = method.score_group([row(1)], {1: values}, only("safety"), scenario)[0]
    assert result["multifactor"]["final_score"] == Decimal("44.4444")
    fields["airbags"] = observed("airbags", "0", fields["airbags"].sources)
    fields["abs"] = observed("abs", False, fields["abs"].sources)
    values, scenario, _ = metrics(vehicle.model_copy(update={"fields": fields}))
    assert values["safety"]["value"] == 0
    fields["esc"] = unavailable("esc")
    values, _, _ = metrics(vehicle.model_copy(update={"fields": fields}))
    assert values["safety"]["value"] is None


@pytest.mark.parametrize("field,unit", [("cargo_l", "mm"), ("weight_kg", "cv"), ("power_gasoline_cv", "kg")])
def test_wrong_units_fail_closed(field, unit):
    vehicle = synthetic_vehicle(1)
    fields = dict(vehicle.fields)
    fields[field] = fields[field].model_copy(update={"unit": unit})
    assert method.observation(vehicle.model_copy(update={"fields": fields}), field, {"cargo_l": "l", "weight_kg": "kg", "power_gasoline_cv": "cv"}[field], exact=True) is None


@pytest.mark.parametrize("invalid", [None, True, "NaN", "Infinity", "-1", "0"])
def test_invalid_measurement_never_becomes_score(invalid):
    assert method.number(invalid) is None


def test_nominal_or_other_powertrain_not_exact_performance():
    vehicle = synthetic_vehicle(1)
    fields = dict(vehicle.fields)
    fields["power_gasoline_cv"] = fields["power_gasoline_cv"].model_copy(update={"applicability": "shared_powertrain"})
    values, _, _ = metrics(vehicle.model_copy(update={"fields": fields}))
    assert values["performance"]["value"] is None
    values, _, _ = metrics(city_consumption_km_l="8", highway_consumption_km_l="10", fuel_strategy="ethanol_hydrated")
    assert values["performance"]["value"] is None  # do not reuse gasoline power for ethanol.


@pytest.mark.parametrize("criterion", DEFAULT_MULTIFACTOR_WEIGHTS)
def test_positive_unknown_blocks_total_zero_weight_explicitly_excludes(criterion):
    values, scenario, _ = metrics()
    values[criterion].update(value=None, available=False, missing_inputs=["explicit test absence"])
    before = deepcopy(values)
    result = method.score_group([row(1)], {1: values}, DEFAULT_MULTIFACTOR_WEIGHTS, scenario)[0]
    assert result["multifactor"]["final_score"] is None and result["score"] == 50
    weights = {**DEFAULT_MULTIFACTOR_WEIGHTS, criterion: 0}
    result = method.score_group([row(1)], {1: values}, weights, scenario)[0]
    assert result["multifactor"]["final_score"] is not None
    entry = next(c for c in result["multifactor"]["components"] if c["component"] == criterion)
    assert entry["raw_score"] is None and entry["contribution"] == 0 and not entry["available"]
    assert criterion in [c["criterion"] for c in result["multifactor"]["excluded_dimensions"]]
    assert values == before


@pytest.mark.parametrize("criterion,a,b,winner", [
    ("total_cost", "400", "600", 1), ("efficiency", "10", "15", 2),
    ("comfort", "250", "500", 2), ("performance", "8", "20", 1),
    ("legacy_quality", "500", "300", 2), ("safety", "44.4444", "100", 2)])
def test_preference_direction_and_contributions(criterion, a, b, winner):
    values, scenario, _ = metrics()
    other = deepcopy(values)
    values[criterion]["value"], other[criterion]["value"] = Decimal(a), Decimal(b)
    result = method.score_group([row(1), row(2)], {1: values, 2: other}, only(criterion), scenario)
    assert result[0]["vehicle"]["catalog_id"] == winner
    assert result[0]["multifactor"]["final_score"] > result[1]["multifactor"]["final_score"]
    for item in result:
        assert item["multifactor"]["final_score"] == sum(c["contribution"] for c in item["multifactor"]["components"])


def test_compatibility_and_equal_inputs_do_not_invent_distinctions():
    values, scenario, _ = metrics()
    for criterion in ("usage_fit", "total_cost", "efficiency", "legacy_quality", "comfort"):
        result = method.score_group([row(2), row(1)], {1: values, 2: values}, only(criterion), scenario)
        assert [r["vehicle"]["catalog_id"] for r in result] == [2, 1]
        assert result[0]["score"] == result[1]["score"]


def test_decimal_rounding_and_positive_weights_are_not_redistributed():
    values, scenario, _ = metrics()
    weighted = {key: "1" for key in DEFAULT_MULTIFACTOR_WEIGHTS}
    result = method.score_group([row(1)], {1: values}, weighted, scenario)[0]["multifactor"]
    assert result["final_score"] == sum(c["contribution"] for c in result["components"])
    assert all(c["contribution"].as_tuple().exponent == -4 for c in result["components"])
    assert 0 <= result["final_score"] <= 100
    values["safety"].update(value=None, available=False)
    missing = method.score_group([row(1)], {1: values}, weighted, scenario)[0]["multifactor"]
    assert missing["final_score"] is None
    assert not missing["criterion_calculations"]["weights_redistributed"]
    assert missing["components"][0]["normalized_weight"] == Decimal(1) / 7


def test_scenario_absence_and_tampering_do_not_create_quality():
    values, scenario, evaluation = metrics()
    vehicle = synthetic_vehicle(1)
    sim, _ = personalized_fuel(vehicle, scenario)
    for change in ("absence", "unit", "nature"):
        bad = deepcopy(evaluation)
        component = bad["scenario_costs"]["components"]["maintenance"]
        component.update({"value": None} if change == "absence" else {"unit": "BRL/year"} if change == "unit" else {"nature": "observed"})
        result = method.measurements(vehicle, bad, sim, scenario, documentary_eligible=True)
        assert result["legacy_quality"]["value"] is None
    result = method.measurements(vehicle, evaluation, None, scenario, documentary_eligible=False)
    assert result["usage_fit"]["value"] is result["total_cost"]["value"] is result["efficiency"]["value"] is None


def test_all_sixty_origin_original_and_gates_unchanged(service):
    original = recommend_academic(service, request(service, multifactor_profile=personalization()))
    assert original["multifactor_profile"]["ranked_count"] == 0
    default = recommend_academic(service, request(service, multifactor_profile=profile()))
    assert default["algorithm_version"] == default["weights_version"] == method.VERSION
    assert default["baseline_algorithm"] == "academic-v4-live-v1"
    assert default["considered_count"] == 60 and default["multifactor_profile"]["ranked_count"] == 1
    assert default["recommendations"][0]["vehicle"]["catalog_id"] == 1
    explicit = recommend_academic(service, request(service, multifactor_profile=profile({**DEFAULT_MULTIFACTOR_WEIGHTS, "safety": "0"})))
    assert explicit["multifactor_profile"]["ranked_count"] == 60
    assert not explicit["operationally_active"] and not explicit["recommended"]
    assert all(not r["evaluation"]["observed_tco_complete"] for r in explicit["recommendations"])
    assert {r["vehicle"]["catalog_id"]: r["monthly_total_cost"] for r in original["recommendations"]} == {r["vehicle"]["catalog_id"]: r["monthly_total_cost"] for r in default["recommendations"]}
    family = recommend_academic(service, request(service, use_case="familia", multifactor_profile=profile({**DEFAULT_MULTIFACTOR_WEIGHTS, "safety": "0"})))
    assert family["documentary_eligible_count"] == family["eligible_count"] == 1
    # Explicit zero safety never bypasses the Family documentary gate.
    assert recommend_academic(service, request(service, multifactor_profile=personalization()))["recommendations"] == original["recommendations"]


def test_weight_tradeoff_changes_the_calculation_not_observations(service):
    fuel = recommend_academic(service, request(service, multifactor_profile=profile(only("total_cost"))))
    cargo = recommend_academic(service, request(service, multifactor_profile=profile(only("comfort"))))
    assert [r["vehicle"]["catalog_id"] for r in fuel["recommendations"]] != [r["vehicle"]["catalog_id"] for r in cargo["recommendations"]]
    assert all("not independent" in r["multifactor"]["dependencies"][0] for r in fuel["recommendations"])


def test_http_derived_contract_and_disabled_gate(service, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setenv("ACADEMIC_COHORT_ENABLED", "true")
    monkeypatch.setattr(main, "get_academic_service", lambda _: service)
    main.app.dependency_overrides[main.get_db] = lambda: object()
    try:
        client = TestClient(main.app)  # No lifespan: no startup database/bootstrap.
        body = request(service, multifactor_profile=profile()).model_dump(mode="json")
        response = client.post("/recommendations?envelope=true", json=body)
        assert response.status_code == 200 and response.json()["multifactor_profile"]["ranked_count"] == 1
        assert response.json()["algorithm_version"] == response.json()["weights_version"] == method.VERSION
        entry = response.json()["recommendations"][0]["multifactor"]
        assert entry["policy_version"] == method.VERSION and len(entry["components"]) == 7
        monkeypatch.delenv("SIGRA_DERIVED_PERSONALIZATION_ENABLED")
        assert client.post("/recommendations?envelope=true", json=body).status_code == 422
    finally:
        main.app.dependency_overrides.clear()
