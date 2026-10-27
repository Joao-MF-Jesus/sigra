"""Synthetic-only tests for the offline academic cost scenario."""
from copy import deepcopy
from decimal import Decimal as D

import pytest

from data_platform.catalog.academic_cost_scenario import (
    VERSION, body_footprint_evidence, configuration, evaluate_cohort, evaluate_vehicle,
    scenario_cost_evidence, validate_configuration,
)
from data_platform.catalog.profile_contracts_v3 import Citation, ProfileVehicle, blank_fields, observed
from data_platform.catalog.profile_scoring_v3 import score_cohort


def citation(provider):
    return Citation(provider=provider, url="https://example.org/synthetic", sha256="a" * 64,
                    document="SYNTHETIC UNIT TEST ONLY", locator="row=1",
                    collected_at="2026-09-14T00:00:00Z")


def vehicle(identifier=36, **overrides):
    fields = blank_fields()
    values = {
        "fipe_code": "001234-5", "year_code": "2020-5",
        "commercial_identity": "Synthetic exact trim", "reference_month": "2026-09",
        "price_brl": "60000", "consumption_city": "12", "consumption_highway": "15",
        "fuel": "flex", "transmission": "manual", "length_mm": "4000",
        "width_with_mirrors_mm": "1800", "cargo_l": "400", "seats": "5",
        "ground_clearance_mm": "180",
    }
    values.update(overrides)
    for name, value in values.items():
        if value is None:
            continue
        provider = "fipe" if name in {"fipe_code", "year_code", "commercial_identity", "reference_month", "price_brl"} else (
            "pbev" if name in {"consumption_city", "consumption_highway", "fuel", "transmission"} else "manufacturer")
        fields[name] = observed(name, value, (citation(provider),))
    return ProfileVehicle(id=identifier, label="Synthetic exact trim", identity_status="identity_approved", fields=fields)


def test_contract_has_visible_uniform_parameters_and_locked_guardrails():
    config = configuration()
    assert config["version"] == VERSION
    assert set(config["scenarios"]) == {"low", "base", "high"}
    assert config["common_inputs"]["monthly_km"]["value"] == "1000"
    assert config["common_inputs"]["fuel_price_brl_per_l"]["value"] == "6"
    assert all(method["nature"] == "scenario_estimate" for method in config["methods"].values())
    assert not any((config["guardrails"][key] for key in (
        "operational_activation_allowed", "publication_allowed", "recommendation_ranking_executed",
        "safety_estimation_allowed", "missing_is_zero", "parameters_calibrated_to_desired_order",
        "legacy_vehicle_values_modified",
    )))


def test_exact_decimal_tco_rounding_and_component_natures():
    result = scenario_cost_evidence(vehicle(), "base")
    assert result["scenario_tco_complete"]
    assert result["components"]["fuel"]["value"] == D("500.00")
    assert result["components"]["ipva"]["value"] == D("200.00")
    assert result["components"]["maintenance"]["value"] == D("300.00")
    assert result["components"]["insurance"]["value"] == D("150.00")
    assert result["components"]["depreciation"]["value"] == D("500.00")
    assert result["scenario_monthly_tco_brl"] == D("1650.00")
    assert {component["nature"] for component in result["components"].values()} == {"scenario_estimate"}
    assert not result["observed_value_claimed"] and not result["operational_activation_allowed"]
    half_up = scenario_cost_evidence(vehicle(price_brl="1", consumption_city="11.2"), "base")
    assert half_up["components"]["maintenance"]["value"] == D("0.01")


def test_fixed_annual_parameter_is_supported_without_vehicle_imputation():
    config = configuration()
    config["scenarios"]["base"]["maintenance"] = {
        "mode": "fixed_annual_brl", "value": "2400", "unit": "BRL/year",
    }
    result = scenario_cost_evidence(vehicle(), "base", config=config)
    assert result["components"]["maintenance"]["value"] == D("200.00")
    assert result["components"]["maintenance"]["inputs"] == {
        "fixed_annual_brl": {"value": D("2400"), "unit": "BRL/year", "nature": "scenario_parameter"},
    }


def test_absent_parameter_or_input_stays_unavailable_and_never_zero():
    config = configuration()
    del config["scenarios"]["base"]["insurance"]
    missing_parameter = scenario_cost_evidence(vehicle(), "base", config=config)
    assert not missing_parameter["scenario_tco_complete"]
    assert missing_parameter["components"]["insurance"]["value"] is None
    assert "parameter is absent" in missing_parameter["components"]["insurance"]["reason"]
    no_consumption = vehicle(consumption_city=None)
    result = scenario_cost_evidence(no_consumption, "base")
    assert not result["scenario_tco_complete"]
    assert result["components"]["fuel"]["value"] is None
    assert result["components"]["fuel"]["nature"] == "unavailable"
    assert result["scenario_monthly_tco_brl"] is None


@pytest.mark.parametrize("mutator", [
    lambda c: c["scenarios"]["base"]["insurance"].update(value="-0.01"),
    lambda c: c["scenarios"]["base"]["insurance"].update(value=0.03),
    lambda c: c["scenarios"]["base"]["insurance"].update(unit="percent/year"),
    lambda c: c["scenarios"]["base"]["insurance"].update(value="1.01"),
])
def test_invalid_values_and_units_fail_closed(mutator):
    config = configuration()
    mutator(config)
    with pytest.raises(ValueError):
        validate_configuration(config)


def test_academic_readiness_never_changes_operational_or_recommendation_gates():
    row = evaluate_vehicle(vehicle(), "cidade", "base", "2026-09")
    assert row["academic_test_ready"]
    assert row["scenario_tco_complete"] and not row["observed_tco_complete"]
    assert not row["operationally_active"] and not row["recommended"]
    assert not row["recommendation_ranking_executed"]
    assert row["confidence"]["presented"] and row["coverage"]["presented"]


@pytest.mark.parametrize("identifier", range(36, 45))
def test_body_footprint_is_idempotent_traceable_and_never_claims_mirror_width(identifier):
    candidate = vehicle(identifier, width_with_mirrors_mm=None, length_mm="4000", width_mm="1700")
    first = body_footprint_evidence(candidate)
    second = body_footprint_evidence(candidate)
    assert first == second
    assert first["value"] == D("6.8") and first["unit"] == "m2"
    assert first["formula"] == "length_mm * body_width_mm / 1000000"
    assert first["method_version"] == VERSION and first["nature"] == "derived"
    assert first["accepted_for_profile_criteria"] == []
    assert set(first["input_evidence_hashes"]) == {"length_mm", "body_width_mm"}
    assert first["inputs"]["body_width_mm"]["unit"] == "mm"
    city = evaluate_vehicle(candidate, "cidade", "base", "2026-09")
    assert city["academic_derived_evidence"]["body_footprint_m2"] == first
    assert city["academic_criteria_values"]["footprint"] is None
    assert "footprint" in city["academic_coverage"]["required_missing"]
    assert not city["academic_test_ready"]


def test_academic_tco_completes_only_the_academic_work_operating_cost_gate():
    candidate = vehicle(36, maintenance_annual_brl=None)
    work = evaluate_vehicle(candidate, "trabalho", "base", "2026-09")
    assert not work["profile_scoreable"]
    assert work["academic_profile_scoreable"] and work["academic_test_ready"]
    assert work["academic_criteria_values"]["operating_cost"] == work["scenario_monthly_tco_brl"]
    assert work["academic_criteria_natures"]["operating_cost"] == "scenario_estimate"
    assert work["academic_criterion_overrides"]["operating_cost"]["allowed_gate"] == "academic_test_ready"
    assert not work["academic_criterion_overrides"]["operating_cost"]["operational_gate_used"]
    assert work["observed_tco_complete"] is False
    assert work["methodology_ready"] is False
    assert work["operationally_active"] is False and work["recommended"] is False


def test_academic_tco_does_not_override_non_work_profiles():
    city = evaluate_vehicle(vehicle(width_with_mirrors_mm=None), "cidade", "base", "2026-09")
    assert city["academic_criterion_overrides"] == {}
    assert city["academic_criteria_values"]["footprint"] is None
    assert not city["academic_profile_scoreable"]


@pytest.mark.parametrize("profile", ["familia", "estrada"])
def test_complete_academic_tco_never_estimates_safety_or_unblocks_safety_profiles(profile):
    row = evaluate_vehicle(vehicle(), profile, "base", "2026-09")
    assert row["scenario_tco_complete"]
    assert not row["profile_scoreable"] and not row["academic_test_ready"]
    assert "safety" in row["coverage"]["required_missing"]
    assert "PROFILE_REQUIRED_EVIDENCE_MISSING" in row["blockers"]


def test_two_exact_safety_inventories_unblock_only_those_two_family_and_road_rows():
    unsupported = vehicle(36)
    cruze = vehicle(46, airbags="6", abs=True, esc=True)
    focus = vehicle(80, airbags="6", abs=True, esc=True)
    report = evaluate_cohort([unsupported, cruze, focus], "2026-09")["scenarios"]["base"]
    for profile in ("familia", "estrada"):
        rows = report[profile]["rows"]
        assert report[profile]["counts"]["academic_test_ready"] == 2
        assert [row["id"] for row in rows if row["academic_test_ready"]] == [46, 80]
        missing = next(row for row in rows if row["id"] == 36)
        assert "safety" in missing["academic_coverage"]["required_missing"]
    assert all(
        details["counts"]["operationally_active"] == 0
        and details["counts"]["recommended"] == 0
        and not details["recommendation_executed"]
        for details in report.values()
    )


def test_duplicate_ids_and_thresholds_cannot_promote_readiness():
    one = vehicle()
    with pytest.raises(ValueError, match="Duplicate"):
        evaluate_cohort([one, one], "2026-09")
    report = evaluate_cohort([one], "2026-09")
    family = report["scenarios"]["base"]["familia"]
    assert family["coverage_thresholds_do_not_promote_readiness"]
    assert family["counts"]["academic_test_ready"] == 0
    assert family["recommendation_ranking"] == [] and not family["recommendation_executed"]


def test_idempotence_v3_stability_and_legacy_ranking_preservation():
    vehicles = [vehicle(36), vehicle(37, price_brl="70000", consumption_city="10")]
    before_models = deepcopy(vehicles)
    before_ranking = score_cohort(vehicles, "cidade", "2026-09")
    first = evaluate_cohort(vehicles, "2026-09")
    second = evaluate_cohort(vehicles, "2026-09")
    after_ranking = score_cohort(vehicles, "cidade", "2026-09")
    assert first == second
    assert vehicles == before_models
    assert before_ranking == after_ranking
    assert first["sensitivity"]["cidade"]["academic_preview_score_orders"]
    assert set(first["cost_sensitivity_all_scenario_complete_vehicles"]["scenario_tco_orders"]) == {"low", "base", "high"}
    assert first["cost_sensitivity_all_scenario_complete_vehicles"]["is_cost_sensitivity_not_recommendation"]
    assert not first["operational_publication_authorized"]
    assert not first["operational_activation_authorized"]
    assert not first["recommendation_ranking_executed"]


def test_wrong_fuel_preserves_missing_semantics():
    result = scenario_cost_evidence(vehicle(fuel="diesel"), "base")
    assert not result["scenario_tco_complete"]
    assert result["components"]["fuel"]["value"] is None
    assert "incompatible" in result["components"]["fuel"]["reason"]


def test_invalid_diagnostic_units_and_zero_distance_fail_closed():
    wrong_unit = configuration()
    wrong_unit["diagnostic_derivations"]["body_footprint_m2"]["unit"] = "cm2"
    with pytest.raises(ValueError, match="Body footprint"):
        validate_configuration(wrong_unit)
    zero_distance = configuration()
    zero_distance["common_inputs"]["monthly_km"]["value"] = "0"
    with pytest.raises(ValueError, match="must be positive"):
        validate_configuration(zero_distance)


def test_eight_exact_mirror_widths_raise_only_city_and_work_academic_readiness_to_ten():
    identifiers = tuple(range(36, 55))
    before_vehicles = tuple(
        vehicle(identifier, width_with_mirrors_mm="1900" if index < 2 else None)
        for index, identifier in enumerate(identifiers)
    )
    after_vehicles = tuple(
        vehicle(identifier, width_with_mirrors_mm="1900" if index < 10 else None)
        for index, identifier in enumerate(identifiers)
    )
    before = evaluate_cohort(before_vehicles, "2026-09")["scenarios"]["base"]
    after = evaluate_cohort(after_vehicles, "2026-09")["scenarios"]["base"]
    assert before["cidade"]["counts"]["academic_test_ready"] == 2
    assert before["trabalho"]["counts"]["academic_test_ready"] == 2
    assert after["cidade"]["counts"]["academic_test_ready"] == 10
    assert after["trabalho"]["counts"]["academic_test_ready"] == 10
    for profile in ("app", "familia", "estrada", "suv"):
        assert (after[profile]["counts"]["academic_test_ready"]
                == before[profile]["counts"]["academic_test_ready"])
    assert all(
        details["counts"]["operationally_active"] == 0
        and details["counts"]["recommended"] == 0
        and not details["recommendation_executed"]
        for details in after.values()
    )
