"""Closure regression tests use synthetic inputs, never new source approvals."""
from copy import deepcopy
import hashlib

import pytest

from data_platform.catalog.adapter import SourceArchive
from data_platform.catalog.legacy_remaining_v4 import DISPOSITIONS, ready_ids
from data_platform.catalog import legacy_technical_v4 as technical
from data_platform.catalog.profile_contracts_v3 import Observation
from data_platform.catalog.profile_pilot_v4 import evaluate_vehicle
from data_platform.tests.test_catalog_profile_v4 import vehicle as academic_vehicle
from data_platform.tests.test_catalog_legacy_technical_v4 import vehicle, source_fields, source_case
from data_platform.tests.test_catalog_legacy_academic_v4 import (
    review, price_payload, pbev_payload, validate_pbev, _price,
)


def replay(ids=(1, 2)):
    return {s: {"app": [dict(id=i, academic_test_ready=True, scenario_tco_complete=True,
                            operationally_active=False, recommended=False) for i in ids]}
            for s in ("low", "base", "high")}


def test_readiness_requires_three_scenarios_for_same_profile():
    result = replay()
    assert ready_ids(result) == [1, 2]
    result["high"]["app"][0]["academic_test_ready"] = False
    assert ready_ids(result) == [2]


@pytest.mark.parametrize("mutation", ["missing_scenario", "missing_profile", "duplicate", "missing_id",
                                      "operational", "recommended", "incomplete_tco"])
def test_inconsistent_or_operational_replays_are_rejected(mutation):
    result = replay()
    if mutation == "missing_scenario": del result["high"]
    elif mutation == "missing_profile": result["high"] = {}
    elif mutation == "duplicate": result["base"]["app"] *= 2
    elif mutation == "missing_id": result["high"]["app"].pop()
    elif mutation == "operational": result["base"]["app"][0]["operationally_active"] = True
    elif mutation == "recommended": result["base"]["app"][0]["recommended"] = True
    else: result["base"]["app"][0]["scenario_tco_complete"] = False
    with pytest.raises(ValueError): ready_ids(result)


def test_logical_removal_reinsertion_and_order_are_idempotent():
    original = replay()
    reduced = replay((2,))
    assert ready_ids(reduced) == [2]
    for scenario in reduced:
        reduced[scenario]["app"].append(deepcopy(original[scenario]["app"][0]))
    assert ready_ids(reduced) == ready_ids(original)
    assert original == replay()


@pytest.mark.parametrize("identifier,transmission,blocker", [
    (9, "Automático", "CARPEDIA_TRANSMISSION_NOT_EXACT"),
    (33, "Manual", "CARPEDIA_SE_SE_PLUS_SCOPE_NOT_INDIVIDUALIZED"),
])
def test_remaining_technical_holds_are_not_identity_approvals(identifier, transmission, blocker):
    v, row = vehicle(identifier)
    assert blocker in technical.identity_blockers(v, row, source_fields(transmission))
    assert DISPOSITIONS[identifier] == "MISSING_TECHNICAL_EVIDENCE"


def test_divergent_fuel_rejected_for_corolla():
    v, row = vehicle(9)
    assert "CARPEDIA_FUEL_NOT_EXACT" in technical.identity_blockers(v, row, source_fields("CVT", "Diesel"))


def test_off_month_price_cannot_replace_september():
    row = review(9)
    payload = price_payload(row)
    payload["referenceMonth"] = "2026-08"
    with pytest.raises(ValueError): _price(row, payload)


def test_wrong_pbev_version_is_not_a_fuzzy_candidate():
    row = review(9)
    payload = pbev_payload(row)
    payload["rows"][0]["version_name"] = "ALTIS"
    with pytest.raises(ValueError): validate_pbev(row, payload)


@pytest.mark.parametrize("missing", ["wheelbase_mm", "width_mm", "seats"])
def test_complete_tco_does_not_supply_missing_habitability(missing):
    v = academic_vehicle(9, **{missing: None})
    result = evaluate_vehicle(v, "app", "base", "2026-09")
    assert result["scenario_tco_complete"]
    assert not result["academic_test_ready"]
    assert not result["operationally_active"] and not result["recommended"]


@pytest.mark.parametrize("suffix", [".pdf", ".json"])
def test_tampered_document_and_cache_fail_hash_check(tmp_path, suffix):
    path = tmp_path / ("synthetic" + suffix)
    expected = hashlib.sha256(b"original").hexdigest()
    path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        SourceArchive((tmp_path,)).bytes({"cache_file": path.name, "sha256": expected})


def test_unknown_safety_cannot_become_false():
    v = academic_vehicle(9)
    for field in ("airbags", "abs", "esc"):
        original = v.fields[field].model_dump()
        assert original["value"] is None
        with pytest.raises(ValueError): Observation.model_validate({**original, "value": False})


def test_existing_source_parser_still_rejects_altered_trim(source_case):
    _, _, fiche, write = source_case
    fiche["versao"]["nome"] += " / UNPROVEN TRIM"
    with pytest.raises(ValueError): technical.parse_record(*write())


def test_no_remaining_disposition_claims_promotion():
    assert len(DISPOSITIONS) == 18
    assert "READY_FROM_LOCAL_EVIDENCE" not in DISPOSITIONS.values()
    for identifier in (6, 7, 13, 17, 21, 23):
        assert review(identifier)["status"] == "blocked"
