"""Seven criteria on explicitly synthetic evidence; no database connections."""
from copy import deepcopy
from decimal import Decimal

import pytest

from backend.tests.test_academic_recommendation import service, request, synthetic_vehicle
from backend.tests.test_academic_personalization import personalization
from app.academic_cohort.personalization import personalized_fuel
from app.academic_cohort.recommendation import recommend_academic
from app.academic_cohort.seven_criteria import criterion_calculations, VERSION
from app.multifactor_recommendation import apply_multifactor_ranking, MULTIFACTOR_COMPONENTS
from app.multifactor_schemas import MultifactorRecommendationProfile, DEFAULT_MULTIFACTOR_WEIGHTS
from types import SimpleNamespace


def test_default_missing_criteria_keep_null_and_supported_contributions(service):
    result = recommend_academic(service, request(service, multifactor_profile=personalization()))
    assert result["eligible_count"] == 60
    assert result["multifactor_profile"]["ranked_count"] == 0
    for row in result["recommendations"]:
        diagnostic = row["multifactor"]["criterion_calculations"]
        assert diagnostic["version"] == VERSION
        assert diagnostic["final_score"] is diagnostic["partial_total"] is None
        assert diagnostic["weights_redistributed"] is False
        assert diagnostic["weighted_coverage"] == "0.35"
        assert diagnostic["calculated_requested_count"] == 2
        assert diagnostic["requested_count"] == 7
        criteria = {r["criterion"]: r for r in diagnostic["criteria"]}
        assert set(criteria) == set(MULTIFACTOR_COMPONENTS)
        for key in ("usage_fit", "comfort", "safety", "performance", "legacy_quality"):
            assert criteria[key]["raw_score"] is criteria[key]["contribution"] is None
            assert criteria[key]["missing_reason"] == "original_method_inputs_unavailable"
            assert criteria[key]["requirement_message"]
        for key, maximum in (("total_cost", 25), ("efficiency", 10)):
            assert Decimal(criteria[key]["contribution"]) <= maximum
            assert criteria[key]["calculation_scope"] == "diagnostic_only"
            assert not criteria[key]["used_in_final_score"]
        quality = criteria["legacy_quality"]
        assert set(quality["calculated_subcriteria"]) == {"maintenance_score", "resale_score"}
        assert all(c["nature"] == "scenario_estimate" for c in quality["calculated_subcriteria"].values())
        assert quality["inputs_used"]["score_components.maintenance_score"]["nature"] == "scenario_estimate"
        assert quality["inputs_used"]["score_components.resale_score"]["nature"] == "scenario_estimate"
        assert row["vehicle"]["technical_fields"]["consumption_city"]["sources"][0]["provider"] == "pbev"


def test_ranked_diagnostics_copy_motor_values_exactly_and_do_not_impute(service):
    profile = personalization()
    profile["weights"] = {key: "0" for key in DEFAULT_MULTIFACTOR_WEIGHTS}
    profile["weights"].update(total_cost="75", efficiency="25")
    result = recommend_academic(service, request(service, multifactor_profile=profile))
    for row in result["recommendations"]:
        motor = row["multifactor"]
        diagnostics = motor["criterion_calculations"]
        assert diagnostics["final_score"] == motor["final_score"]
        assert diagnostics["weights_redistributed"] is False
        components = {c["component"]: c for c in motor["components"]}
        for c in diagnostics["criteria"]:
            if c["available"]:
                assert c["raw_score"] == components[c["criterion"]]["raw_score"]
                assert c["contribution"] == components[c["criterion"]]["contribution"]
            else:
                assert c["raw_score"] is None
                assert Decimal(c["contribution"]) == 0
                assert c["status"] == "not_requested"
        assert sum(Decimal(c["contribution"]) for c in diagnostics["criteria"]) == Decimal(motor["final_score"])


def test_partial_weight_change_changes_contribution_without_final_score(service):
    first = recommend_academic(service, request(service, multifactor_profile=personalization()))
    changed = personalization()
    changed["weights"] = {**DEFAULT_MULTIFACTOR_WEIGHTS, "total_cost": "20", "efficiency": "15"}
    second = recommend_academic(service, request(service, multifactor_profile=changed))
    a = {r["vehicle"]["catalog_id"]: r for r in first["recommendations"]}
    b = {r["vehicle"]["catalog_id"]: r for r in second["recommendations"]}
    assert list(a) == list(b)
    assert any(a[i]["multifactor"]["criterion_calculations"]["criteria"] != b[i]["multifactor"]["criterion_calculations"]["criteria"] for i in a)
    for i in a:
        assert a[i]["multifactor"]["final_score"] is b[i]["multifactor"]["final_score"] is None
        assert a[i]["score"] == b[i]["score"]


def test_input_nature_sources_and_user_override_are_distinct(service):
    baseline = recommend_academic(service, request(service, multifactor_profile=personalization()))
    manual = recommend_academic(service, request(service, multifactor_profile=personalization(city_consumption_km_l="20", highway_consumption_km_l="25")))
    before = baseline["recommendations"][0]["multifactor"]["criterion_calculations"]["criteria"][0]["inputs_used"]
    after = manual["recommendations"][0]["multifactor"]["criterion_calculations"]["criteria"][0]["inputs_used"]
    assert before["city_consumption_km_l"]["nature"] == "observed"
    assert before["city_consumption_km_l"]["sources"][0]["provider"] == "pbev"
    assert after["city_consumption_km_l"]["nature"] == "user_input"
    assert after["city_consumption_km_l"]["sources"] == []
    assert after["monthly_fuel_cost_brl"]["nature"] == "scenario_estimate"
    assert after["weighted_consumption_km_l"]["nature"] == "derived"
    assert Decimal(after["monthly_fuel_cost_brl"]["value"]) == Decimal("270")


@pytest.mark.parametrize("changes", [{"manual_fuel_price_brl": None}, {"fuel_strategy": "ethanol_hydrated"}])
def test_no_simulation_never_produces_diagnostic_fuel_score(service, changes):
    result = recommend_academic(service, request(service, multifactor_profile=personalization(**changes)))
    for row in result["recommendations"]:
        assert row["multifactor"]["criterion_calculations"]["weighted_coverage"] == "0"
        for c in row["multifactor"]["criterion_calculations"]["criteria"]:
            assert c["raw_score"] is c["contribution"] is None


def complete_synthetic_rows():
    """Original scores are invented ONLY for this unit fixture, never catalog."""
    profile = MultifactorRecommendationProfile.model_validate(personalization())
    scenario = profile.scenario.to_contract()
    simulations, rows = {}, []
    for i in (1, 2, 3):
        simulation, error = personalized_fuel(synthetic_vehicle(i), scenario)
        assert error is None
        simulations[i] = simulation
        rows.append({"vehicle": {"catalog_id": i, "comfort_score": 50 + i,
                                "safety_score": 60 + i, "road_score": 40 + i},
                     "score_components": {"usage_score": 70 + i, "maintenance_score": 50 + i,
                         "reliability_score": 40 + i, "parts_score": 60 + i, "resale_score": 80 + i},
                     "score": 30 + i})
    return profile, scenario, simulations, rows


@pytest.mark.parametrize("key", MULTIFACTOR_COMPONENTS)
def test_each_of_seven_weights_reaches_original_motor_and_contributions(key):
    profile, scenario, simulations, rows = complete_synthetic_rows()
    def calculate(weights):
        transformed = apply_multifactor_ranking(deepcopy(rows), SimpleNamespace(results=(), fingerprint="synthetic"),
            weights, evidence_resolver=lambda row: (simulations[row["vehicle"]["catalog_id"]], {"fixture": "synthetic"}))
        return {r["vehicle"]["catalog_id"]: criterion_calculations(r, transformed, simulations, scenario, weights) for r in transformed}
    first = calculate(profile.weights.as_mapping())
    changed = profile.weights.as_mapping()
    changed[key] *= 2
    second = calculate(changed)
    assert any(a["final_score"] != second[i]["final_score"] for i, a in first.items())
    for i in first:
        a = next(c for c in first[i]["criteria"] if c["criterion"] == key)
        b = next(c for c in second[i]["criteria"] if c["criterion"] == key)
        assert a["raw_score"] == b["raw_score"]
        assert b["normalized_weight_percentage"] > a["normalized_weight_percentage"]
        if a["raw_score"] > 0:
            assert b["contribution"] > a["contribution"]
        else:
            assert a["contribution"] == b["contribution"] == 0
        assert b["calculation_scope"] == "original_motor_ranking"
        assert second[i]["final_score"] == sum(c["contribution"] for c in second[i]["criteria"])


def test_ranked_normalization_excludes_unscorable_member():
    profile, scenario, simulations, rows = complete_synthetic_rows()
    rows[0]["vehicle"]["comfort_score"] = None
    transformed = apply_multifactor_ranking(rows, SimpleNamespace(results=(), fingerprint="synthetic"),
        profile.weights.as_mapping(), evidence_resolver=lambda row: (simulations[row["vehicle"]["catalog_id"]], {}))
    for row in transformed:
        c = criterion_calculations(row, transformed, simulations, scenario, profile.weights.as_mapping())["criteria"][0]
        assert c["normalization"]["population_ids"] == ([2, 3] if row["multifactor"]["status"] == "ranked" else [1, 2, 3])


@pytest.mark.parametrize("invalid", [None, -1, 101, "NaN", True])
def test_invalid_original_score_stays_unavailable(invalid):
    profile, scenario, simulations, rows = complete_synthetic_rows()
    rows[0]["vehicle"]["comfort_score"] = invalid
    result = criterion_calculations(rows[0], rows, simulations, scenario, profile.weights.as_mapping())
    comfort = next(c for c in result["criteria"] if c["criterion"] == "comfort")
    assert comfort["raw_score"] is comfort["contribution"] is None


def test_repeated_diagnostics_preserve_payloads_order_and_finances(service):
    before = deepcopy([row.payload for row in service.repository.rows])
    args = request(service, multifactor_profile=personalization())
    a = recommend_academic(service, args)
    b = recommend_academic(service, args)
    assert [r["multifactor"]["criterion_calculations"] for r in a["recommendations"]] == [r["multifactor"]["criterion_calculations"] for r in b["recommendations"]]
    assert before == [row.payload for row in service.repository.rows]
    assert a["operationally_active"] is a["recommended"] is False


def test_http_seven_criteria_payload_parameters_and_diagnostics(service, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setenv("ACADEMIC_COHORT_ENABLED", "true")
    monkeypatch.setattr(main, "get_academic_service", lambda db: service)
    monkeypatch.setattr(main, "ensure_fipe_prices_current", lambda: pytest.fail("External collection forbidden"))
    snapshot = service.repository.snapshot(None)
    snapshot.cohort_version = "academic-cohort-v6"
    snapshot.inventory_summary["outside_selection"] = [{"id": i} for i in range(70, 91)]
    monkeypatch.setattr(service.repository, "snapshot", lambda _: snapshot)
    main.app.dependency_overrides[main.get_db] = lambda: object()
    try:
        # The HTTP transport is in memory. Do not run lifespan/startup, whose
        # database audit is explicitly outside this isolated test's scope.
        client = TestClient(main.app)
        profile = personalization(monthly_distance_km="2000", manual_fuel_price_brl="7")
        profile["weights"] = {**DEFAULT_MULTIFACTOR_WEIGHTS, "total_cost": "20", "efficiency": "15"}
        payload = request(service, multifactor_profile=profile).model_dump(mode="json")
        response = client.post("/recommendations?envelope=true", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["considered_count"] == 60
        assert data["preferences_applied"]["multifactor_profile"]["weights"] == payload["multifactor_profile"]["weights"]
        for row in data["recommendations"]:
            diagnostic = row["multifactor"]["criterion_calculations"]
            assert diagnostic["final_score"] is None
            assert len(diagnostic["criteria"]) == 7
            cost = diagnostic["criteria"][0]
            assert Decimal(cost["input_weight"]) == 20
            assert Decimal(cost["normalized_weight_percentage"]) == 20
            assert Decimal(cost["inputs_used"]["monthly_distance_km"]["value"]) == 2000
            assert Decimal(cost["inputs_used"]["fuel_price_brl_l"]["value"]) == 7
            assert Decimal(cost["contribution"]) <= 20
            assert not cost["used_in_final_score"]
        # A positive criterion lacking evidence remains a block. Selecting
        # only supported criteria is explicit, never an automatic fallback.
        profile["weights"] = dict.fromkeys(DEFAULT_MULTIFACTOR_WEIGHTS, "0")
        profile["weights"].update(total_cost="75", efficiency="25")
        response = client.post("/recommendations?envelope=true", json=request(service, multifactor_profile=profile).model_dump(mode="json"))
        assert response.status_code == 200
        assert response.json()["multifactor_profile"]["ranked_count"] == 60
    finally:
        main.app.dependency_overrides.pop(main.get_db, None)
