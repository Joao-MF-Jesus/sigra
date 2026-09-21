"""Synthetic offline fixtures only; no real Latin NCAP applicability is asserted."""
from copy import deepcopy
from decimal import Decimal as D
import hashlib

import pytest

from data_platform.catalog.academic_cost_scenario import configuration as cost_configuration
from data_platform.catalog.profile_contracts_v3 import Citation, ProfileVehicle, blank_fields, observed
from data_platform.catalog.profile_pilot_v4 import (
    compare_groups, configuration, evaluate_cohort, evaluate_vehicle, fingerprint,
    habitability_evidence, rankings,
)
from data_platform.catalog.profile_safety_v4 import safety_evidence, validate_record
from data_platform.catalog.profile_scoring_v3 import score_cohort


def citation(provider="manufacturer", **changes):
    values = dict(provider=provider, url="https://example.org/synthetic-fixture", sha256="a" * 64,
                  document="SYNTHETIC UNIT TEST ONLY", locator="fixture row 1",
                  collected_at="2026-09-21T00:00:00Z")
    values.update(changes)
    return Citation(**values)


def vehicle(identifier=36, **changes):
    fields = blank_fields()
    values = {
        "fipe_code": "001234-5", "year_code": "2020-5", "commercial_identity": "Synthetic exact trim",
        "reference_month": "2026-09", "price_brl": "60000", "consumption_city": "12",
        "consumption_highway": "15", "fuel": "flex", "transmission": "manual", "seats": "5",
        "wheelbase_mm": "2500", "width_mm": "1800", "length_mm": "4000",
        "width_with_mirrors_mm": "2000", "cargo_l": "400", "payload_kg": "500",
        "weight_kg": "1000", "power_gasoline_cv": "100", "ground_clearance_mm": "180",
    }
    values.update(changes)
    for key, value in values.items():
        if value is None:
            continue
        provider = "fipe" if key in {"fipe_code", "year_code", "commercial_identity", "reference_month", "price_brl"} else (
            "pbev" if key in {"consumption_city", "consumption_highway", "fuel", "transmission"} else "manufacturer")
        fields[key] = observed(key, value, (citation(provider),))
    return ProfileVehicle(id=identifier, label="Synthetic exact trim", identity_status="identity_approved", fields=fields)


def record(tmp_path, candidate=36):
    content = b"SYNTHETIC RESULT, APPLICABILITY AND PROTOCOL - NOT REAL EVIDENCE"
    (tmp_path / "test.txt").write_bytes(content)
    source = citation("latinncap", url="https://www.latinncap.com/test-only-fixture",
                      sha256=hashlib.sha256(content).hexdigest()).model_dump(mode="json")
    scope = dict(generation="Synthetic generation", body="sedan", configuration="Synthetic exact trim", model_year=2020)
    return dict(candidate_id=candidate,
                identity={key: vehicle(candidate).fields[key].value for key in ("fipe_code", "year_code", "commercial_identity", "fuel")},
                target_scope=scope, tested_scope=deepcopy(scope), covered_model_years=[2020], test_year=2020,
                protocol_id="SYNTHETIC-protocol-2020", protocol_period_start="2020-01-01", protocol_period_end="2025-12-31",
                metric="adult_occupant_points", result="24", maximum="32",
                review_status="exact_configuration_reviewed", review_note="Synthetic exact applicability for regression tests only.",
                result_source=source, applicability_source=deepcopy(source), protocol_source=deepcopy(source),
                result_file="test.txt", applicability_file="test.txt", protocol_file="test.txt")


def test_contract_is_additive_explicit_and_has_no_admitted_ncap_record():
    config = configuration()
    assert config["version"] == "academic-profile-pilot-v4"
    assert config["safety"]["records"] == []
    assert config["safety"]["equipment_inference_allowed"] is False
    assert config["operational_activation_allowed"] is False
    assert config["recommendation_allowed"] is False
    assert config["academic_habitability_proxy"]["inputs"]["width_mm"] == "mm"


def test_proxy_dimension_provenance_and_unknown_observations():
    v = vehicle()
    item = habitability_evidence(v)
    assert item["value"] == D("0.9")
    assert item["unit"] == "m2/nominal_place"
    assert item["nature"] == "derived_academic"
    assert not item["measured_interior_space"]
    assert item["input_coverage"] == 1
    assert item["confidence"]["value"] is None
    assert set(item["inputs"]) == {"wheelbase_mm", "width_mm", "seats"}
    assert all(x["sources"][0]["sha256"] == "a" * 64 for x in item["inputs"].values())
    assert v.fields["interior_width_mm"].value is None
    assert v.fields["rear_legroom_mm"].value is None
    assert habitability_evidence(vehicle(width_with_mirrors_mm="9999")) == item


def test_direct_inputs_take_precedence_and_are_not_pooled_with_proxy():
    direct = vehicle(37, rear_legroom_mm="800", interior_width_mm="1400")
    item = habitability_evidence(direct)
    assert item["value"] == D("1.12") and item["path"] == "measured_interior_inputs"
    rows = [evaluate_vehicle(v, "app", "base", "2026-09") for v in (vehicle(), direct)]
    assert len(rankings(rows)) == 2


@pytest.mark.parametrize("field", ["seats", "width_mm", "wheelbase_mm"])
@pytest.mark.parametrize("value", [None, "0"])
def test_missing_or_zero_proxy_inputs_fail_closed(field, value):
    if field == "width_mm" and value == "0":
        # The unchanged academic v1 body-footprint guard rejects this first.
        with pytest.raises(ValueError, match="positive millimetre"):
            evaluate_vehicle(vehicle(**{field: value}), "app", "base", "2026-09")
        assert habitability_evidence(vehicle(**{field: value}))["value"] is None
        return
    row = evaluate_vehicle(vehicle(**{field: value}), "app", "base", "2026-09")
    assert not row["academic_test_ready"]
    assert row["criteria"]["passenger_space"]["value"] is None


@pytest.mark.parametrize("value", ["-1", "NaN", "Infinity", 1.5, True])
def test_invalid_proxy_input_rejected(value):
    with pytest.raises(ValueError):
        vehicle(width_mm=value)


def test_invalid_unit_and_derived_input_not_accepted_as_observed():
    v = vehicle()
    bad = v.model_copy(update={"fields": {**v.fields, "width_mm": v.fields["width_mm"].model_copy(update={"unit": "m"})}})
    with pytest.raises(ValueError):
        evaluate_vehicle(bad, "app", "base", "2026-09")
    nominal = v.model_copy(update={"fields": {**v.fields, "width_mm": v.fields["width_mm"].model_copy(update={"applicability": "model_nominal"})}})
    assert habitability_evidence(nominal)["value"] == D("0.9")
    derived = v.model_copy(update={"fields": {**v.fields, "width_mm": v.fields["width_mm"].model_copy(update={"kind": "derived"})}})
    assert habitability_evidence(derived)["value"] is None


def test_academic_ready_never_promotes_operational_or_observed_tco():
    row = evaluate_vehicle(vehicle(), "app", "base", "2026-09")
    assert row["academic_test_ready"] and row["scenario_tco_complete"]
    assert not row["methodology_ready"] and not row["observed_tco_complete"]
    assert not row["operationally_active"] and not row["recommended"]
    assert row["operational_ranking"] == []
    assert row["criteria"]["urban_fuel"]["nature"] == "scenario_estimate"
    assert row["criteria"]["cargo"]["nature"] == "observed"
    assert row["criteria"]["passenger_space"]["nature"] == "derived_academic"
    assert sum(row["coverage"]["original_weight_by_nature"].values()) == 1
    assert row["coverage"]["original_weight_by_nature"]["derived_academic"] == D("0.25")


def test_missing_scenario_parameter_blocks_even_with_proxy():
    config = cost_configuration()
    del config["scenarios"]["base"]["insurance"]
    row = evaluate_vehicle(vehicle(), "app", "base", "2026-09", scenario_config=config)
    assert not row["scenario_tco_complete"] and not row["academic_test_ready"]


@pytest.mark.parametrize("change", [
    {"identity_status": "legacy_binding_not_reaudited"},
    {"human_approval_required": True, "human_approval_status": "pending"},
    {"source_conflicts": ("Unresolved exact trim",)},
])
def test_identity_conflicts_and_pending_review_never_bypassed(change):
    row = evaluate_vehicle(vehicle().model_copy(update=change), "app", "base", "2026-09")
    assert not row["academic_test_ready"]


def test_inventory_requires_three_exact_fields_and_does_not_infer_false():
    assert safety_evidence(vehicle(abs=True, esc=True))["value"] is None
    zero = safety_evidence(vehicle(airbags="0", abs=False, esc=False))
    assert zero["value"] == 0 and zero["path"] == "exact_inventory"
    full = safety_evidence(vehicle(airbags="6", abs=True, esc=True))
    assert full["value"] == 100
    v = vehicle(airbags="6", abs=True, esc=True)
    v = v.model_copy(update={"fields": {**v.fields, "airbags": v.fields["airbags"].model_copy(update={"applicability": "model_nominal"})}})
    assert safety_evidence(v)["value"] is None


def test_exact_ncap_path_preserves_missing_equipment_and_protocol(tmp_path):
    v = vehicle()
    data = record(tmp_path)
    assert validate_record(data, v, tmp_path).candidate_id == 36
    result = safety_evidence(v, [data], tmp_path)
    assert result["value"] == 75 and result["path"] == "latin_ncap_configuration_test"
    assert result["inputs"]["protocol_id"] == "SYNTHETIC-protocol-2020"
    assert all(item["value"] is None for item in result["equipment_observations"].values())
    row = evaluate_vehicle(v, "familia", "base", "2026-09", records=[data], document_directory=tmp_path)
    assert row["academic_test_ready"] and not row["methodology_ready"]


@pytest.mark.parametrize("mutate", [
    lambda d: d["identity"].update(fipe_code="999999-9"),
    lambda d: d["identity"].update(fuel="diesel"),
    lambda d: d["identity"].update(year_code="2019-5"),
    lambda d: d["identity"].update(commercial_identity="Different trim"),
    lambda d: d["tested_scope"].update(configuration="Other trim"),
    lambda d: d["tested_scope"].update(generation="Other generation"),
    lambda d: d["tested_scope"].update(body="hatch"),
    lambda d: d.update(covered_model_years=[2019]),
    lambda d: d.update(unresolved_restrictions=["From a VIN not bound to target"]),
    lambda d: d.update(test_year=2019),
    lambda d: d.update(protocol_id=""),
    lambda d: d.update(result="33"),
    lambda d: d.update(result_file="../escape.pdf"),
    lambda d: d["result_source"].update(url="https://example.org/unofficial"),
    lambda d: d["protocol_source"].update(sha256="b" * 64),
])
def test_ambiguous_or_invalid_ncap_rejected(tmp_path, mutate):
    data = record(tmp_path)
    mutate(data)
    result = safety_evidence(vehicle(), [data], tmp_path)
    assert result["value"] is None and result["nature"] == "unavailable"


def test_tampered_missing_and_duplicate_documents_fail_closed(tmp_path):
    data = record(tmp_path)
    assert safety_evidence(vehicle(), [data, data], tmp_path)["reason"] == "AMBIGUOUS_LATIN_NCAP_RECORDS"
    (tmp_path / "test.txt").write_bytes(b"tampered")
    assert safety_evidence(vehicle(), [data], tmp_path)["value"] is None
    (tmp_path / "test.txt").unlink()
    assert safety_evidence(vehicle(), [data], tmp_path)["value"] is None
    assert safety_evidence(vehicle(), [data])["value"] is None


def test_incompatible_protocols_and_inventory_are_never_pooled(tmp_path):
    a, b = record(tmp_path, 36), record(tmp_path, 37)
    b["protocol_id"] = "SYNTHETIC-other-protocol"
    rows = [evaluate_vehicle(vehicle(i), "familia", "base", "2026-09", records=[a, b], document_directory=tmp_path) for i in (36, 37)]
    rows.append(evaluate_vehicle(vehicle(38, airbags="6", abs=True, esc=True), "familia", "base", "2026-09"))
    assert len(rankings(rows)) == 3
    assert all(len(g["ranking"]) == 1 for g in rankings(rows).values())


def test_replay_idempotent_v3_unchanged_and_decimal_ties():
    vehicles = (vehicle(), vehicle(37))
    original = [v.model_dump(mode="json") for v in vehicles]
    v3 = fingerprint(score_cohort(vehicles, "app", "2026-09"))
    result = evaluate_cohort(vehicles, "2026-09")
    assert fingerprint(evaluate_cohort(vehicles, "2026-09")) == fingerprint(result)
    assert fingerprint(score_cohort(vehicles, "app", "2026-09")) == v3
    assert original == [v.model_dump(mode="json") for v in vehicles]
    base = result["scenario_reports"]["base"]["app"]
    ranking = next(iter(base["diagnostic_rankings"].values()))
    assert ranking["ties"][0]["ids"] == [36, 37]
    assert all(row["preview_score"].as_tuple().exponent == -6 for row in base["rows"])
    assert all(not r["recommended"] for p in result["scenario_reports"]["base"].values() for r in p["rows"])
    assert result["operational_ranking"] == []
    assert result["habitability_sensitivity"]["reference=1"]["ready_ids"] == [36, 37]


def test_duplicate_ids_and_mixed_months_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        evaluate_cohort([vehicle(), vehicle()], "2026-09")
    with pytest.raises(ValueError, match="month"):
        evaluate_cohort([vehicle(reference_month="2026-08")], "2026-09")


def test_unavailable_rankings_are_not_zero_similarity():
    assert compare_groups({}, {}) == {}
    ranks = rankings([evaluate_vehicle(vehicle(), "app", "base", "2026-09")])
    assert next(iter(compare_groups({}, ranks).values()))["jaccard_top10"] is None


@pytest.mark.parametrize("reference", ["0", "-1", "NaN", True, 1.5])
def test_invalid_utility_reference_rejected(reference):
    with pytest.raises(ValueError):
        evaluate_vehicle(vehicle(), "app", "base", "2026-09", proxy_reference=reference)


@pytest.mark.parametrize("profile", ["cidade", "trabalho", "suv"])
@pytest.mark.parametrize("scenario", ["low", "base", "high"])
def test_unaffected_profile_scores_identical_to_academic_v1(profile, scenario):
    from data_platform.catalog.academic_cost_scenario import evaluate_vehicle as v1
    prior = v1(vehicle(), profile, scenario, "2026-09")
    result = evaluate_vehicle(vehicle(), profile, scenario, "2026-09")
    assert result["preview_score"] == prior["academic_preview_score"]
    assert result["academic_test_ready"] == prior["academic_test_ready"]
    assert result["methodology_ready"] == prior["methodology_ready"]


def test_boundary_ties_and_cohort_independence():
    vehicles = [vehicle(i) for i in range(36, 47)]
    rows = [evaluate_vehicle(v, "app", "base", "2026-09") for v in vehicles]
    report = next(iter(rankings(rows).values()))
    assert len(report["top10_boundary_ids"]) == 11
    assert rows[0] == evaluate_vehicle(vehicles[0], "app", "base", "2026-09")
    assert next(iter(compare_groups(rankings(rows), rankings(rows[:-1])).values()))["jaccard_top10"] == D(10) / D(11)


def test_undivided_envelope_is_explicitly_sensitivity_only():
    row = evaluate_vehicle(vehicle(), "app", "base", "2026-09", divide_by_places=False)
    evidence = row["criteria"]["passenger_space"]
    assert evidence["value"] == D("4.5") and evidence["unit"] == "m2"
    assert evidence["sensitivity_only"] and evidence["utility_reference_unit"] == "m2"
    assert not evidence["measured_interior_space"]
