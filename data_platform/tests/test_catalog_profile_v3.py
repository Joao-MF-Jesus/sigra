"""Offline synthetic regression data only; never published or used as pilot facts."""
from decimal import Decimal as D
from fractions import Fraction
import hashlib
import json

import pytest

from data_platform.catalog.profile_contracts_v3 import Citation, ProfileVehicle, Observation, VERSION, blank_fields, observed, unavailable
from data_platform.catalog.profile_costs_v3 import cost_evidence
from data_platform.catalog.profile_scoring_v3 import configuration, score_cohort, score_vehicle, utility
from data_platform.catalog.profile_analysis_v3 import analyze_cohort, combined_preview
from data_platform.catalog.profile_evidence_v3 import canonical_month, augment_technical


def citation(provider):
    return Citation(provider=provider, url="https://example.org/source", sha256="a"*64,
                    document="SYNTHETIC UNIT TEST ONLY", locator="row=1", collected_at="2026-09-09T00:00:00Z")


def vehicle(identifier=1, **values):
    fields = blank_fields()
    values = {"price_brl": "50000", "reference_month": "2026-09", "fipe_code": "TEST-001",
              "year_code": "2021-5", "commercial_identity": "Synthetic fixture", "fuel": "flex",
              "transmission": "manual", "consumption_city": "12", "consumption_highway": "15", **values}
    for name, value in values.items():
        provider = "fipe" if name in {"price_brl", "reference_month", "fipe_code", "year_code", "commercial_identity"} else (
            "pbev" if name in {"fuel", "transmission", "consumption_city", "consumption_highway"} else
            "anp" if name == "gasoline_brl_per_l" else "manufacturer")
        fields[name] = unavailable(name) if value is None else observed(name, value, (citation(provider),))
    return ProfileVehicle(id=identifier, label="Synthetic fixture", identity_status="identity_approved", fields=fields)


def changed(v, **values):
    return ProfileVehicle.model_validate({**v.model_dump(), **values})


def test_absolute_utilities_and_independent_fraction_oracle():
    config = configuration()
    for name, scale in config["scales"].items():
        if "lower" not in scale:
            continue
        low, high = D(scale["lower"]), D(scale["upper"])
        assert utility(low, scale) == (100 if scale["direction"] == "lower" else 0)
        assert utility(high, scale) == (0 if scale["direction"] == "lower" else 100)
        assert utility((low+high)/2, scale) == 50
        assert 0 <= utility(high*100, scale) <= 100
        assert utility(None, scale) is None
    row = score_vehicle(vehicle(length_mm="4000", width_with_mirrors_mm="1800"), "cidade", "2026-09")
    oracle = (Fraction(100)*(1500-500)/1250*Fraction(45,100) +
              Fraction(100)*(11-Fraction(72,10))/6*Fraction(25,100) +
              Fraction(100)*(160000-50000)/140000*Fraction(30,100))
    assert abs(row["preview_score"] - D(oracle.numerator)/D(oracle.denominator)) < D("0.000002")


@pytest.mark.parametrize("profile", list(configuration()["profiles"]))
def test_cohort_addition_and_display_labels_never_change_existing_scores(profile):
    a, b = vehicle(1), vehicle(2, price_brl="60000", consumption_city="10")
    dominated = vehicle(3, price_brl="1000000", consumption_city="1", consumption_highway="1")
    first = score_cohort([a,b], profile, "2026-09")
    after = score_cohort([changed(a, label="Desired winner brand collection SUV", provenance={"group":"SUV"}), b, dominated], profile, "2026-09")
    assert [r["preview_score"] for r in first["records"]] == [r["preview_score"] for r in after["records"][:2]]
    assert [r["id"] for r in first["ranking"]] == [r["id"] for r in after["ranking"] if r["id"] != 3]
    for r in after["records"]:
        assert r["preview_score"] == (sum(v for v in r["contributions"].values() if v is not None) if r["used_criteria"] else None)
        if r["used_criteria"]:
            assert sum(r["effective_weights"].values()) == 1


def test_absent_weight_changes_coverage_not_score_and_never_imputes_neutral():
    v = vehicle()
    before = score_vehicle(v,"cidade","2026-09")
    weights = {"urban_fuel":"0.45", "footprint":"8", "price":"0.30"}
    after = score_vehicle(v,"cidade","2026-09",weights=weights)
    assert before["preview_score"] == after["preview_score"]
    assert after["weighted_coverage"] < before["weighted_coverage"]
    assert after["utilities"]["footprint"] is None
    assert after["contributions"]["footprint"] is None
    assert after["confidence"]["value"] is None


def test_costs_manual_fuel_and_explicit_rates_are_not_observed_or_complete_tco():
    config = configuration(); scenario = config["scenario"]
    scenario["annual_estimate_rates"] = {"maintenance":"0.06", "insurance":"0.03", "depreciation":"0.10", "ipva":"0.04"}
    result = cost_evidence(vehicle(), scenario)
    assert result["observed_monthly_fuel_cost"] is None
    assert result["derived_monthly_fuel_cost"] is None
    assert result["known_monthly_cost"] is None
    assert result["estimated_components"]["fuel"] == D("500.00")
    assert result["estimated_components"]["maintenance"] == D("250.00")
    assert len(result["missing_cost_components"]) == 5
    assert result["monthly_tco"] is None and not result["is_complete_tco"]
    assert result["proven_operating_cost"] is None
    assert result["monthly_budget_eligible"] is None
    assert result["component_evidence"]["fuel"]["status"] == "scenario_estimate"
    assert result["component_evidence"]["fuel"]["origin"] == "PBEV consumption plus explicit user scenario"
    assert result["component_evidence"]["ipva"]["status"] == "scenario_estimate"
    assert result["total_evidence"]["status"] == "unavailable"


def test_anp_no_silent_fallback_and_annual_conversion_exactly_once():
    scenario = {**configuration()["scenario"], "fuel_price_mode":"anp"}
    assert cost_evidence(vehicle(), scenario)["estimated_monthly_cost"] is None
    v = vehicle(gasoline_brl_per_l="6", maintenance_annual_brl="3200")
    with pytest.raises(ValueError, match="ANP week"):
        cost_evidence(v,scenario)
    v = changed(v,provenance={"anp_context":{"week_start":"2026-09-07","geography":"SP","fuel":"gasoline"}})
    costs = cost_evidence(v, scenario)
    assert costs["known_components"]["maintenance"] == D("266.67")
    assert costs["known_monthly_cost"] == D("766.67")
    assert costs["observed_monthly_fuel_cost"] == D("500")
    assert costs["derived_monthly_fuel_cost"] == D("500")
    assert costs["component_evidence"]["fuel"]["status"] == "derived_from_observed_inputs"
    assert costs["component_evidence"]["maintenance"]["method"] == "maintenance_annual_brl / 12 exactly once"
    assert not costs["is_complete_tco"]


def test_complete_cost_requires_each_component_not_estimates():
    v = vehicle(gasoline_brl_per_l="6", maintenance_annual_brl="1200", ipva_annual_brl="1200", insurance_annual_brl="1200", depreciation_annual_brl="1200")
    v = changed(v,provenance={"anp_context":{"week_start":"2026-09-07","geography":"SP","fuel":"gasoline"}})
    result = cost_evidence(v,{**configuration()["scenario"],"fuel_price_mode":"anp"})
    assert result["monthly_tco"] == 900 and result["is_complete_tco"]
    assert result["estimated_monthly_cost"] is None


def test_complete_tco_makes_a_ready_vehicle_recommendable_but_does_not_execute_recommendation():
    v = vehicle(
        length_mm="4000", width_with_mirrors_mm="1800", gasoline_brl_per_l="6",
        maintenance_annual_brl="1200", ipva_annual_brl="1200",
        insurance_annual_brl="1200", depreciation_annual_brl="1200",
    )
    v = changed(v, provenance={"anp_context":{"week_start":"2026-09-07","geography":"SP","fuel":"gasoline"}})
    scenario = {**configuration()["scenario"], "fuel_price_mode":"anp"}
    row = score_vehicle(v, "cidade", "2026-09", scenario=scenario)
    assert row["methodology_ready"] and row["tco_complete"] and row["recommendable"]
    assert not row["recommended"]
    cohort = score_cohort([v], "cidade", "2026-09", scenario=scenario)
    assert cohort["recommendable_ids"] == [1]
    assert cohort["recommended_ids"] == [] and not cohort["recommendation_executed"]


@pytest.mark.parametrize("fuel",["diesel","ethanol","electric"])
def test_gasoline_scenario_does_not_relabel_other_fuels(fuel):
    assert cost_evidence(vehicle(fuel=fuel),configuration()["scenario"])["urban_fuel_for_scenario"] is None


def test_safety_requires_all_evidence_zero_is_distinct_from_missing():
    incomplete = score_vehicle(vehicle(airbags="4",abs=True),"familia","2026-09")
    explicit_zero = score_vehicle(vehicle(airbags="0",abs=False,esc=False),"familia","2026-09")
    assert incomplete["criteria_values"]["safety"] is None
    assert explicit_zero["criteria_values"]["safety"] == 0
    assert explicit_zero["utilities"]["safety"] == 0


def test_readiness_requires_identity_month_coverage_required_sources_and_approval():
    v = vehicle(length_mm="4000",width_with_mirrors_mm="1800")
    ready = score_vehicle(v,"cidade","2026-09")
    assert ready["identity_resolved"] and ready["partial_coverage_candidate"]
    assert ready["profile_scoreable"] and ready["profile_eligible"] and ready["methodology_ready"]
    assert not ready["tco_complete"] and not ready["recommendable"] and not ready["recommended"]
    cases = [changed(v,identity_status="legacy_binding_not_reaudited"), changed(v,source_conflicts=("unresolved",)),
             changed(v,human_approval_required=True,human_approval_status="pending"), vehicle()]
    for candidate in cases:
        assert not score_vehicle(candidate,"cidade","2026-09")["methodology_ready"]
    row = score_vehicle(v,"cidade","2026-07")
    assert row["preview_score"] is None and row["profile_scoreable"] and not row["profile_eligible"]
    assert not row["methodology_ready"]
    assert not row["operationally_active"]


def test_footprint_is_versioned_and_passenger_space_is_never_inferred_from_exterior_data():
    row = score_vehicle(
        vehicle(length_mm="4000", width_mm="1700", width_with_mirrors_mm="1900", wheelbase_mm="2500", seats="5"),
        "cidade", "2026-09",
    )
    footprint = row["criterion_derivations"]["footprint"]
    assert footprint["value"] == D("7.6")
    assert footprint["unit"] == "m2"
    assert footprint["method_version"] == "catalog-profile-evidence-v3"
    app = score_vehicle(
        vehicle(length_mm="4000", width_mm="1700", width_with_mirrors_mm="1900", wheelbase_mm="2500", seats="5", cargo_l="400"),
        "app", "2026-09",
    )
    assert app["criteria_values"]["passenger_space"] is None
    assert "Rear legroom" in app["criterion_derivations"]["passenger_space"]["reason"]
    assert not app["profile_scoreable"]


def test_profile_key_suv_is_documented_as_space_capacity_without_body_style_elimination():
    config = configuration()
    definition = config["profiles"]["suv"]
    assert definition["display_name"] == "Espaço/capacidade"
    assert definition["eligibility"] == {"categorical_rules": [], "eliminatory_rules": []}
    hatch = vehicle(seats="5", cargo_l="400", ground_clearance_mm="180", wheelbase_mm="2500", width_mm="1700")
    row = score_vehicle(hatch, "suv", "2026-09")
    assert row["profile_eligible"] and row["methodology_ready"]
    assert not row["recommendable"] and not row["recommended"]


def test_cohort_preserves_diagnostic_order_but_never_labels_it_recommendation_without_complete_tco():
    report = score_cohort(
        [vehicle(1, length_mm="4000", width_with_mirrors_mm="1800")],
        "cidade", "2026-09",
    )
    assert report["ranking"] == report["diagnostic_preview_ranking"]
    assert report["methodology_ready_ids"] == [1]
    assert report["recommendable_ids"] == []
    assert report["recommended_ids"] == []
    assert report["recommendation_ranking"] == []
    assert report["recommendation_executed"] is False


def test_no_joint_preview_for_mixed_or_missing_months():
    with pytest.raises(ValueError,match="FIPE month"):
        score_cohort([vehicle(),vehicle(2,reference_month="2026-07")],"cidade","2026-09")
    assert combined_preview([vehicle(2,reference_month="2026-07")],[vehicle()],"2026-09")["profiles"] is None
    assert combined_preview([vehicle(2,price_brl=None)],[vehicle()],"2026-09")["profiles"] is None


def test_duplicates_and_invalid_weights_rejected():
    with pytest.raises(ValueError,match="Duplicate"):
        score_cohort([vehicle(),vehicle()],"cidade","2026-09")
    for weights in ({"price":"1"},{"urban_fuel":"0","footprint":"0","price":"0"}, {"urban_fuel":"-1","footprint":"1","price":"1"}):
        with pytest.raises(ValueError):
            score_vehicle(vehicle(),"cidade","2026-09",weights=weights)


def test_transmission_requires_explicit_preference_without_universal_ranking():
    weights = {**configuration()["profiles"]["estrada"]["weights"],"transmission":"1"}
    with pytest.raises(ValueError,match="explicit preference"):
        score_vehicle(vehicle(),"estrada","2026-09",weights=weights)
    scenario = {**configuration()["scenario"],"transmission_preference":"manual"}
    assert score_vehicle(vehicle(),"estrada","2026-09",weights=weights,scenario=scenario)["utilities"]["transmission"] == 100


@pytest.mark.parametrize("value",[1.2,True,"NaN","Infinity","-1"])
def test_numeric_evidence_rejects_inexact_nonfinite_or_negative(value):
    with pytest.raises(ValueError):
        vehicle(price_brl=value)


def test_contract_forbids_extra_wrong_units_official_override_and_fabricated_missing():
    v = vehicle(); data = v.model_dump()
    with pytest.raises(ValueError):
        ProfileVehicle.model_validate({**data,"made_up":50})
    data["fields"]["price_brl"]["sources"] = [citation("manufacturer").model_dump()]
    with pytest.raises(ValueError,match="precedence"):
        ProfileVehicle.model_validate(data)
    data = v.model_dump(); data["fields"]["price_brl"]["unit"] = "mm"
    with pytest.raises(ValueError,match="unit mismatch"):
        ProfileVehicle.model_validate(data)
    with pytest.raises(ValueError,match="null"):
        Observation(unit="count",value=50,reason="missing")
    with pytest.raises(ValueError,match="Derivation"):
        Observation(unit="count",value=5,kind="derived",sources=(citation("manufacturer"),),applicability="exact_variant")


def test_month_normalization_and_geometry_not_passenger_comfort():
    assert canonical_month("setembro de 2026") == "2026-09"
    assert canonical_month("julho de 2026") == "2026-07"
    row = score_vehicle(vehicle(seats="5",width_mm="1800",wheelbase_mm="2500"),"app","2026-09")
    assert row["criteria_values"]["passenger_space"] is None


def test_analysis_sensitivity_stability_and_empty_rankings():
    before = configuration()
    report = analyze_cohort([vehicle(),vehicle(2,price_brl="60000")],"2026-09")
    assert report["cohort_stability"]["checks"] == 12
    assert report["cohort_stability"]["all_passed"]
    assert report["profiles"]["trabalho"]["top10"] == []
    assert report["similarity_matrix"]["trabalho"]["cidade"]["jaccard_top10"] is None
    assert configuration() == before
    missing = [r for r in report["sensitivity"]["cidade"] if r["criterion"] == "footprint"]
    assert all(d["delta"] == 0 for r in missing for d in r["score_deltas"])


def test_technical_adapter_hash_identity_and_overwrite_fail_closed(tmp_path,monkeypatch):
    import data_platform.catalog.profile_evidence_v3 as module
    raw = b"synthetic fixture not a real PDF"; (tmp_path/"fixture.pdf").write_bytes(raw)
    citation_data = {"url":"https://example.org/source","sha256":hashlib.sha256(raw).hexdigest(),"document":"fixture","cache_file":"fixture.pdf","collected_at":"2026-09-09T00:00:00Z"}
    fact = {"value":"5","document_id":"fixture","locator":"test row","page":1,"applicability":"exact_variant","limitations":[]}
    records = [{"id":i,"fipe_code":"TEST-001","year_code":"2021-5","expected_fipe_description":"Synthetic fixture",
                "fields":{"seats":fact},"unavailable":{},"source_conflicts":[],"binding_rationale":"unit fixture","limitations":[]} for i in (35,36,37)]
    specification = {"version":VERSION,"sources":{"fixture":citation_data},"vehicles":records}
    path=tmp_path/"facts.json"; path.write_text(json.dumps(specification),encoding="utf-8")
    monkeypatch.setattr(module,"TECHNICAL_PATH",path)
    assert augment_technical([vehicle(35)],tmp_path)[0].fields["seats"].value == 5
    with pytest.raises(ValueError,match="identity mismatch"):
        augment_technical([vehicle(35,year_code="2020-5")],tmp_path)
    with pytest.raises(ValueError,match="overwrite"):
        augment_technical([vehicle(35,seats="5")],tmp_path)
    (tmp_path/"fixture.pdf").write_bytes(b"tampered")
    with pytest.raises(ValueError,match="snapshot changed"):
        augment_technical([vehicle(35)],tmp_path)
