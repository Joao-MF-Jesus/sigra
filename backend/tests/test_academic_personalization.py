"""Regression: legacy opt-in criteria are not replaced by academic utilities."""
from copy import deepcopy
from decimal import Decimal

import pytest

from backend.tests.test_academic_recommendation import service, request, synthetic_vehicle
from app.academic_cohort.recommendation import recommend_academic
from app.multifactor_schemas import DEFAULT_MULTIFACTOR_WEIGHTS
from data_platform.catalog.profile_pilot_v4 import fingerprint
from app.academic_cohort.evidence_diagnostics import documentary_evidence, personalization_evidence
from app.academic_cohort.recommendation import live_evaluation, validated_weights
from data_platform.catalog.profile_contracts_v3 import blank_fields


def personalization(**changes):
    scenario = {"monthly_distance_km": "1000", "city_percentage": "50", "highway_percentage": "50",
                "state_code": "SP", "municipality": None, "reference_week_start": "2026-09-01",
                "fuel_strategy": "gasoline_c_common", "horizon_months": 12,
                "manual_fuel_price_brl": "6"}
    scenario.update(changes)
    return {"enabled": True, "scenario": scenario, "weights": DEFAULT_MULTIFACTOR_WEIGHTS}


def test_original_criteria_defaults_and_unavailable_scores_are_preserved(service):
    result = recommend_academic(service, request(service, multifactor_profile=personalization()))
    assert result["considered_count"] == result["eligible_count"] == 60
    assert result["multifactor_profile"]["ranked_count"] == 0
    assert result["multifactor_profile"]["original_count"] == 60
    for row in result["recommendations"]:
        assert row["multifactor"]["final_score"] is None
        assert row["multifactor"]["policy_version"] == "user-profile-multifactor-v1"
        assert row["multifactor"]["reason_code"] == "MULTIFACTOR_EVIDENCE_UNAVAILABLE"
        assert "comfort" in row["multifactor"]["detail"]
        assert row["vehicle"]["operational_vehicle_id"] is None
        assert "safety_score" not in row["vehicle"]


def test_mixed_route_formula_updates_tco_and_preserves_cost_composition(service):
    mf = personalization(city_percentage="25", highway_percentage="75", monthly_distance_km="2000", horizon_months=24)
    result = recommend_academic(service, request(service, multifactor_profile=mf))
    for row in result["recommendations"]:
        i = row["vehicle"]["catalog_id"]
        city = Decimal(service.repository.rows[i - 1].payload["fields"]["consumption_city"]["value"])
        fuel = ((Decimal(500) / city + Decimal(1500) / 15) * 6).quantize(Decimal("0.0001"))
        evaluation = row["evaluation"]
        components = evaluation["scenario_costs"]["components"]
        assert Decimal(components["fuel"]["value"]) == fuel
        assert Decimal(row["monthly_total_cost"]) == sum(Decimal(c["value"]) for c in components.values()).quantize(Decimal("0.01"))
        assert evaluation["scenario_costs"]["scenario_total"]["value"] == row["monthly_total_cost"]
        assert row["multifactor"]["scenario"]["horizon_months"] == 24
        assert evaluation["observed_tco_complete"] is False


def test_original_normalization_ranks_only_supported_positive_weight_evidence(service):
    mf = personalization()
    mf["weights"] = {key: "0" for key in DEFAULT_MULTIFACTOR_WEIGHTS}
    mf["weights"].update(total_cost="75", efficiency="25")
    result = recommend_academic(service, request(service, multifactor_profile=mf))
    assert result["multifactor_profile"]["ranked_count"] == 60
    for row in result["recommendations"]:
        personalized = row["multifactor"]
        assert personalized["status"] == "ranked"
        assert {c["component"] for c in personalized["components"]} == set(DEFAULT_MULTIFACTOR_WEIGHTS)
        assert Decimal(personalized["final_score"]) == sum(Decimal(c["contribution"]) for c in personalized["components"])
        assert all(c["available"] is False for c in personalized["components"] if c["component"] in {"comfort", "safety", "performance", "legacy_quality", "usage_fit"})
        assert personalized["cost"]["vehicle_sk"] is None
        assert all("published_gold" not in c["source"] and "pbev_gold" not in c["source"] for c in personalized["components"] if c["component"] in {"total_cost", "efficiency"})


def test_anp_or_ethanol_absence_is_explained_not_fabricated(service):
    for mf in (personalization(manual_fuel_price_brl=None), personalization(fuel_strategy="ethanol_hydrated")):
        result = recommend_academic(service, request(service, multifactor_profile=mf))
        assert result["multifactor_profile"]["scenario_applied_count"] == 0
        assert result["multifactor_profile"]["unavailable_messages"]
        assert all(row["multifactor"]["final_score"] is None for row in result["recommendations"])


def test_documentary_eligibility_and_inputs_are_never_mutated(service):
    before = fingerprint([row.payload for row in service.repository.rows])
    mf = personalization(city_consumption_km_l="12", highway_consumption_km_l="18")
    result = recommend_academic(service, request(service, use_case="familia", multifactor_profile=mf))
    assert result["eligible_count"] == 1
    assert result["operationally_active"] is result["recommended"] is False
    assert before == fingerprint([row.payload for row in service.repository.rows])
    assert result["recommendations"][0]["evaluation"]["scenario_costs"]["components"]["fuel"]["nature"] == "scenario_estimate"


def test_personalization_idempotence_and_effect_of_fuel_price(service):
    mf = personalization()
    first = recommend_academic(service, request(service, multifactor_profile=mf))
    repeat = recommend_academic(service, request(service, multifactor_profile=mf))
    assert first["recommendations"] == repeat["recommendations"]
    changed = recommend_academic(service, request(service, multifactor_profile=personalization(manual_fuel_price_brl="9")))
    costs = {r["vehicle"]["catalog_id"]: Decimal(r["monthly_total_cost"]) for r in first["recommendations"]}
    assert all(Decimal(r["monthly_total_cost"]) > costs[r["vehicle"]["catalog_id"]] for r in changed["recommendations"])


def test_requested_coverage_is_not_the_reference_profile_coverage(service):
    result = recommend_academic(service, request(service, multifactor_profile=personalization()))
    assert len(result["candidate_diagnostics"]) == 60
    assert {r["criterion"]: r["affected_origin_count"] for r in result["multifactor_profile"]["missing_criteria"]} == {
        key: 60 for key in ("usage_fit", "comfort", "safety", "performance", "legacy_quality")}
    for row in result["recommendations"]:
        coverage = row["multifactor"]["evidence_coverage"]
        assert coverage["requested_count"] == 7 and coverage["evaluated_count"] == 2
        assert Decimal(coverage["weighted"]) == Decimal("0.35")
        assert len(coverage["missing"]) == 5 and coverage["complete"] is False
        assert len(coverage["criteria"]) == 7
        assert all(all(value is None for value in c["inputs"].values()) for c in coverage["criteria"]
                   if not c["available"] and c["criterion"] != "legacy_quality")
        quality = next(c for c in coverage["criteria"] if c["criterion"] == "legacy_quality")
        assert quality["inputs"]["score_components.maintenance_score"] is not None
        assert quality["inputs"]["score_components.resale_score"] is not None
        assert quality["missing_inputs"] == ["score_components.reliability_score", "score_components.parts_score"]
        assert row["multifactor"]["final_score"] is None
        assert Decimal(row["evaluation"]["coverage"]["weighted"]) == 1


def test_supported_weight_change_changes_real_contributions_not_frozen_scores(service):
    mf = personalization()
    mf["weights"] = dict.fromkeys(DEFAULT_MULTIFACTOR_WEIGHTS, "0")
    mf["weights"].update(total_cost="75", efficiency="25")
    first = recommend_academic(service, request(service, multifactor_profile=mf))
    mf["weights"].update(total_cost="25", efficiency="75")
    second = recommend_academic(service, request(service, multifactor_profile=mf))
    a = {r["vehicle"]["catalog_id"]: r for r in first["recommendations"]}
    b = {r["vehicle"]["catalog_id"]: r for r in second["recommendations"]}
    assert a.keys() == b.keys()
    assert any(a[i]["score"] != b[i]["score"] for i in a)
    for row in first["recommendations"]:
        coverage = row["multifactor"]["evidence_coverage"]
        assert coverage["requested_count"] == coverage["evaluated_count"] == 2
        assert Decimal(coverage["weighted"]) == 1 and coverage["missing"] == []
        assert coverage["complete"] is True
        assert Decimal(row["score"]) == sum(Decimal(c["contribution"]) for c in row["multifactor"]["components"])


def test_profile_requirements_are_not_personalization_or_financial_filters(service):
    from data_platform.catalog.academic_cohort_v6 import V6ProfileVehicle
    vehicle = synthetic_vehicle(2)
    data = vehicle.model_dump()
    data["fields"]["width_with_mirrors_mm"] = blank_fields()["width_with_mirrors_mm"]
    vehicle = V6ProfileVehicle.model_validate(data)
    city = live_evaluation(vehicle, "cidade", "base", Decimal(1000), Decimal(6), validated_weights("cidade", None))
    explanation = documentary_evidence(vehicle, "cidade", city, False)
    assert {r["field"] for r in explanation["missing_fields"]} == {"width_with_mirrors_mm"}
    assert "retrovisores abertos" in explanation["message"]
    app = live_evaluation(vehicle, "app", "base", Decimal(1000), Decimal(6), validated_weights("app", None))
    assert documentary_evidence(vehicle, "app", app, True)["missing_fields"] == []
    assert app["academic_test_ready"] is True
    # Body width cannot replace mirror width; safety is not required for Cidade.
    assert vehicle.fields["width_mm"].value is not None
    assert all(vehicle.fields[k].value is None for k in ("airbags", "abs", "esc"))
    result = recommend_academic(service, request(service, monthly_limit=1, multifactor_profile=personalization()))
    assert result["eligible_count"] == 0
    assert result["exclusion_counts"]["MONTHLY_BUDGET"] == 60
    assert result["exclusion_counts"]["PROFILE_DOCUMENTARY_REQUIREMENTS"] == 0
    assert result["multifactor_profile"]["ranked_count"] == 0


def test_no_v4_proxy_or_equipment_index_becomes_original_comfort_or_safety_score(service):
    result = recommend_academic(service, request(service, use_case="familia", multifactor_profile=personalization()))
    row = result["recommendations"][0]
    assert row["evaluation"]["criteria"]["safety"]["value"] is not None
    coverage = row["multifactor"]["evidence_coverage"]
    assert next(c for c in coverage["criteria"] if c["criterion"] == "safety")["available"] is False
    assert row["multifactor"]["final_score"] is None
    assert result["operationally_active"] is result["recommended"] is False


def test_no_scenario_evidence_means_zero_requested_coverage(service):
    result = recommend_academic(service, request(service, multifactor_profile=personalization(manual_fuel_price_brl=None)))
    assert all(Decimal(r["multifactor"]["evidence_coverage"]["weighted"]) == 0 for r in result["recommendations"])
    assert all(len(r["multifactor"]["evidence_coverage"]["missing"]) == 7 for r in result["recommendations"])


def test_http_gate_checks_personalization_not_only_endpoint_availability(service, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setenv("ACADEMIC_COHORT_ENABLED", "true")
    monkeypatch.setattr(main, "get_academic_service", lambda db: service)
    monkeypatch.setattr(main, "ensure_fipe_prices_current", lambda: pytest.fail("No external collection"))
    snapshot = service.repository.snapshot(None)
    snapshot.cohort_version = "academic-cohort-v6"
    snapshot.inventory_summary["outside_selection"] = [{"id": i} for i in range(70, 91)]
    monkeypatch.setattr(service.repository, "snapshot", lambda _: snapshot)
    main.app.dependency_overrides[main.get_db] = lambda: object()
    try:
        client = TestClient(main.app)
        metadata = client.get("/recommendations/metadata")
        assert metadata.status_code == 200
        assert metadata.json()["evidence_diagnostics_version"] == "recommendation-evidence-v1"
        mf = personalization()
        response = client.post("/recommendations?envelope=true", json=request(service, multifactor_profile=mf).model_dump(mode="json"))
        assert response.status_code == 200
        data = response.json()
        assert data["considered_count"] == 60 and data["multifactor_profile"]["ranked_count"] == 0
        assert len(data["candidate_diagnostics"]) == 60
        assert len(data["multifactor_profile"]["missing_criteria"]) == 5
        mf["weights"] = dict.fromkeys(DEFAULT_MULTIFACTOR_WEIGHTS, "0")
        mf["weights"].update(total_cost="75", efficiency="25")
        response = client.post("/recommendations?envelope=true", json=request(service, multifactor_profile=mf).model_dump(mode="json"))
        assert response.status_code == 200
        data = response.json()
        assert data["multifactor_profile"]["ranked_count"] == 60
        assert all(Decimal(r["multifactor"]["evidence_coverage"]["weighted"]) == 1 for r in data["recommendations"])
    finally:
        main.app.dependency_overrides.pop(main.get_db, None)
