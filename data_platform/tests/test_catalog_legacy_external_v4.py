"""Synthetic negative tests; real external bytes are replayed separately offline."""
from copy import deepcopy
from decimal import Decimal
import json

import pytest

from data_platform.catalog import legacy_external_v4 as adapter
from data_platform.catalog.adapter import SourceArchive
from data_platform.catalog.profile_contracts_v3 import ProfileVehicle, blank_fields
from data_platform.catalog.profile_pilot_v4 import evaluate_vehicle
from data_platform.tests.test_catalog_legacy_academic_v4 import price_payload, pbev_payload
from data_platform.tests.test_catalog_legacy_technical_v4 import attr


@pytest.fixture
def case(monkeypatch):
    entry = adapter.load_manifest()["admission"]
    payload = price_payload(entry)
    parsed = pbev_payload(entry)
    fields = {"fuel_type": attr("fuel_type", "flex", None),
              "transmission": attr("transmission", "Automático (CVT)", None),
              "width": attr("width", Decimal("1825"), "mm"),
              "wheelbase": attr("wheelbase", Decimal("2640"), "mm"),
              "seats": attr("seats", Decimal("5"), "count"),
              "cargo_capacity": attr("cargo_capacity", Decimal("440"), "L")}
    class Archive:
        def bytes(self, source): return json.dumps(payload).encode()
    monkeypatch.setattr(adapter, "verified_pbev", lambda e, a: parsed)
    monkeypatch.setattr(adapter, "parse_record", lambda r, a: (None, (fields, {})))
    vehicle = ProfileVehicle(id=12, label="Synthetic XR", identity_status="legacy_binding_not_reaudited",
                             fields=blank_fields())
    return vehicle, entry, Archive(), payload, parsed, fields


def test_id12_all_three_scenarios_and_idempotence(case):
    original, entry, archive, *_ = case
    result = adapter.admit_vehicle(original, entry, archive)
    assert result == adapter.admit_vehicle(result, entry, archive)
    assert original.fields["seats"].value is None
    assert result.fields["transmission"].value == "cvt"
    assert result.fields["consumption_city"].value == Decimal("11.7")
    for scenario in ("low", "base", "high"):
        row = evaluate_vehicle(result, "app", scenario, "2026-09")
        assert row["academic_test_ready"] and row["scenario_tco_complete"]
        assert not row["operationally_active"] and not row["recommended"]
        assert not row["operational_ranking"]
    for field in ("airbags", "abs", "esc", "width_with_mirrors_mm", "maintenance_annual_brl"):
        assert result.fields[field].value is None


@pytest.mark.parametrize("identifier", [1,6,7,9,11,13,17,18,19,21,23,24,25,26,27,28,33])
def test_each_unresolved_vehicle_remains_blocked(identifier, case):
    disposition = next(r for r in adapter.load_manifest()["dispositions"] if r["id"] == identifier)
    assert disposition["status"] == "blocked" and disposition["reason"]
    vehicle, entry, archive, *_ = case
    vehicle = ProfileVehicle.model_validate({**vehicle.model_dump(), "id": identifier})
    with pytest.raises(ValueError, match="Only reviewed ID 12"):
        adapter.admit_vehicle(vehicle, entry, archive)


@pytest.mark.parametrize("field,value", [("model", "Corolla Cross XR/XRE"),
    ("model", "Corolla Cross XRE 2.0 16V Flex Aut."), ("modelYear", 2021),
    ("fuel", "Gasolina"), ("referenceMonth", "2026-08"), ("codeFipe", "000000-0")])
def test_wrong_fipe_trim_year_fuel_month_code(case, field, value):
    vehicle, entry, archive, payload, *_ = case
    payload[field] = value
    with pytest.raises(ValueError): adapter.admit_vehicle(vehicle, entry, archive)


@pytest.mark.parametrize("field,value", [("version_name", "XRE 20"), ("fuel_type", "gasoline"),
    ("transmission_code", "M-6"), ("motor_description", "1.8 - 16V")])
def test_wrong_pbev_identity(case, field, value):
    vehicle, entry, archive, _, parsed, _ = case
    parsed["rows"][0][field] = value
    with pytest.raises(ValueError): adapter.admit_vehicle(vehicle, entry, archive)


def test_automatic_does_not_prove_cvt(case):
    vehicle, entry, archive, _, _, fields = case
    fields["transmission"] = attr("transmission", "Automático", None)
    with pytest.raises(ValueError, match="TRANSMISSION_NOT_EXACT"):
        adapter.admit_vehicle(vehicle, entry, archive)


@pytest.mark.parametrize("field", sorted(adapter.REQUIRED_TECHNICAL))
def test_price_tco_cannot_replace_missing_technical(case, field):
    vehicle, entry, archive, _, _, fields = case
    fields.pop(field)
    with pytest.raises(ValueError, match="technical evidence missing"):
        adapter.admit_vehicle(vehicle, entry, archive)


def test_unknown_safety_is_not_false_and_human_hold_remains(case):
    vehicle, entry, archive, *_ = case
    vehicle = ProfileVehicle.model_validate({**vehicle.model_dump(), "human_approval_required": True,
                                             "human_approval_status": "pending"})
    result = adapter.admit_vehicle(vehicle, entry, archive)
    assert all(result.fields[k].kind == "unavailable" for k in ("airbags", "abs", "esc"))
    assert not evaluate_vehicle(result, "app", "base", "2026-09")["academic_test_ready"]


@pytest.mark.parametrize("source", ["pbev_source", "fipe_source"])
def test_cache_and_document_tamper(tmp_path, source):
    entry = adapter.load_manifest()["admission"]
    ref = entry[source]
    (tmp_path / ref["cache_file"]).write_bytes(b"tampered")
    archive = SourceArchive((tmp_path,))
    with pytest.raises(ValueError, match="hash mismatch"):
        archive.bytes(ref)
    if source == "pbev_source":
        with pytest.raises(ValueError): adapter.verified_pbev(entry, archive)


@pytest.mark.parametrize("mutation", ["scope", "duplicate", "admitted", "pbev", "fipe", "catalog", "publication", "database"])
def test_manifest_rejects_unreviewed_admissions(tmp_path, mutation):
    data = deepcopy(adapter.load_manifest())
    if mutation == "scope": data["scope_ids"].pop()
    elif mutation == "duplicate": data["dispositions"][0] = data["dispositions"][1]
    elif mutation == "admitted": data["admitted_ids"].append(9)
    elif mutation == "pbev": data["admission"]["pbev"]["identity"]["version_name"] = "XRE 20"
    elif mutation == "fipe": data["admission"]["fipe"]["reference_month"] = "2026-08"
    elif mutation == "catalog": data["admission"]["catalog"]["model"] = "Corolla Cross XRE"
    elif mutation == "publication": data["publication_authorized"] = True
    elif mutation == "database": data["database_write_authorized"] = True
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError): adapter.load_manifest(path)


def test_canonical_scope_and_other33_preserved(case):
    vehicle, _, archive, *_ = case
    originals = tuple(ProfileVehicle.model_validate({**vehicle.model_dump(), "id": i}) for i in range(1,35))
    after = adapter.augment_legacy_external_v4(originals, archive)
    assert all(a == b for a,b in zip(originals,after) if a.id != 12)
    assert after == adapter.augment_legacy_external_v4(after, archive)
    with pytest.raises(ValueError, match="canonical 34"):
        adapter.augment_legacy_external_v4(originals[:-1], archive)
