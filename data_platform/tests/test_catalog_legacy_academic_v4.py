"""Synthetic unit payloads validate the adapter, not real-world source admission.

Real evidence is replayed separately against hash-pinned, external local archives.
"""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json

import pytest

from data_platform.catalog.adapter import SourceArchive
from data_platform.catalog.legacy_academic_v4 import (
    _pbev, _price, legacy_matrix_v4, load_manifest, replay_legacy_v4,
)


APPROVED = (2, 3, 4, 5, 8, 9, 10, 14, 15, 16, 20, 22, 29, 30, 31, 32, 33, 34)


def review(vehicle_id=2):
    return next(r for r in load_manifest()["reviews"] if r["id"] == vehicle_id)


def price_payload(row):
    target = row["fipe"]
    if target["legacy_price_cache"]:
        return [{"vehicle_id": row["id"], "retrieval_status": "live", "year_code": target["year_code"],
                 "model": target["expected_identity"]["model"], "code": target["expected_identity"]["codeFipe"],
                 "price": 50000, "reference_month": target["reference_month"]}]
    return {**target["expected_identity"], "vehicleType": 1, "price": "R$ 50.000,00",
            "referenceMonth": target["reference_month"]}


def pbev_payload(row):
    binding = row["pbev"]
    year = row["catalog"]["year"]
    value = {**binding["identity"], **binding["consumption"], "propulsion_type": "combustion",
             "raw": {"cycle_year": year, "page_number": binding["page"],
                     "row_number": binding["row_number"], "row_hash": binding["row_hash"]}}
    return {"cycle": year, "status": "parsed", "rows": [value]}


def validate_pbev(row, parsed):
    return _pbev(row, parsed, load_manifest()["sources"][row["pbev"]["source"]])


def test_exact_scope_and_historical_conflicts():
    spec = load_manifest()
    assert [r["id"] for r in spec["reviews"]] == list(range(1, 35))
    assert tuple(r["id"] for r in spec["reviews"] if r["status"] == "identity_approved") == APPROVED
    for vehicle_id in (6, 7, 13, 17, 21, 23):
        assert review(vehicle_id)["status"] == "blocked"
        assert review(vehicle_id)["pbev"] is None
    assert review(33)["fipe"]["reference_month"] == "2026-07"


@pytest.mark.parametrize("vehicle_id", APPROVED)
def test_individually_reviewed_bindings_are_idempotent(vehicle_id):
    row = review(vehicle_id)
    payload = price_payload(row)
    assert _price(row, payload) == _price(row, deepcopy(payload))
    assert _price(row, payload)[0] == Decimal("50000")
    parsed = pbev_payload(row)
    assert validate_pbev(row, parsed) == validate_pbev(row, deepcopy(parsed))


@pytest.mark.parametrize("field,value", [
    ("model", "Other trim"), ("modelYear", 2017), ("fuel", "Gasolina"),
    ("codeFipe", "000000-0"), ("brand", "Ford"), ("vehicleType", 2),
    ("referenceMonth", "2026-08"), ("price", "R$ -1,00"),
])
def test_fipe_identity_or_value_divergence_rejected(field, value):
    row = review()
    payload = price_payload(row)
    payload[field] = value
    with pytest.raises(ValueError):
        _price(row, payload)


@pytest.mark.parametrize("field,value", [
    ("version_name", "UNREVIEWED"), ("fuel_type", "diesel"),
    ("motor_description", "2.0-16V"), ("transmission_code", "M5"),
    ("fossil_city_km_l", "0"), ("fossil_highway_km_l", "-1"),
])
def test_pbev_version_fuel_engine_transmission_and_consumption_rejected(field, value):
    row = review()
    parsed = pbev_payload(row)
    parsed["rows"][0][field] = value
    with pytest.raises(ValueError):
        validate_pbev(row, parsed)


@pytest.mark.parametrize("mutation", ["cycle", "locator", "hash", "missing", "duplicate", "unit", "fuel_code"])
def test_closed_on_year_locator_missing_duplicate_and_units(mutation):
    row = review()
    parsed = pbev_payload(row)
    if mutation == "cycle": parsed["cycle"] -= 1
    elif mutation == "locator": parsed["rows"][0]["raw"]["page_number"] += 1
    elif mutation == "hash": parsed["rows"][0]["raw"]["row_hash"] = "0" * 64
    elif mutation == "missing": parsed["rows"] = []
    elif mutation == "duplicate": parsed["rows"] *= 2
    elif mutation == "unit": row["pbev"]["unit"] = "l/100km"
    elif mutation == "fuel_code": row["fipe"]["year_code"] = "2018-1"
    with pytest.raises(ValueError):
        validate_pbev(row, parsed)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "identity", "approval"])
def test_contract_requires_canonical_scope_and_individual_review(tmp_path, mutation):
    spec = load_manifest()
    if mutation == "missing": spec["reviews"].pop()
    elif mutation == "duplicate": spec["reviews"][1] = spec["reviews"][0]
    elif mutation == "identity": spec["reviews"][1]["catalog"]["year"] -= 1
    elif mutation == "approval": spec["reviews"][0]["status"] = "identity_approved"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(ValueError):
        load_manifest(path)


def test_archive_tampering_blocks_before_returning_any_vehicle(tmp_path):
    source = next(iter(load_manifest()["sources"].values()))
    (tmp_path / source["cache_file"]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        legacy_matrix_v4(SourceArchive((tmp_path,)))


def test_archive_missing_blocks_before_returning_any_vehicle(tmp_path):
    with pytest.raises(ValueError, match="not found"):
        legacy_matrix_v4(SourceArchive((tmp_path,)))


def test_archive_accepts_exact_hash_only(tmp_path):
    content = b"unit-test-only"
    (tmp_path / "evidence.json").write_bytes(content)
    archive = SourceArchive((tmp_path,))
    assert archive.bytes({"cache_file": "evidence.json", "sha256": hashlib.sha256(content).hexdigest()}) == content
    with pytest.raises(ValueError):
        archive.bytes({"cache_file": "evidence.json", "sha256": "0" * 64})


def test_replay_cannot_accept_empty_scope():
    with pytest.raises(ValueError, match="canonical 34"):
        replay_legacy_v4(())


def test_manifest_does_not_claim_safety_or_technical_coverage():
    for row in load_manifest()["reviews"]:
        assert row["technical_evidence_status"] == (
            "No exact legacy OEM/CarPedia dimensional or safety dossier admitted from local registered sources."
        )
        if row["pbev"]:
            assert set(row["pbev"]["consumption"]) == {"fossil_city_km_l", "fossil_highway_km_l"}
