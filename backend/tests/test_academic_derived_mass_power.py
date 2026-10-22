"""Complementary evidence regressions; synthetic vehicle data only in tests."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json

import pytest

from app.academic_cohort import derived_mass_power as batch
from app.academic_cohort import derived_personalization as method
from backend.tests.test_academic_derived_personalization import metrics, row, profile
from backend.tests.test_academic_recommendation import synthetic_vehicle, service, request
from app.multifactor_schemas import DEFAULT_MULTIFACTOR_WEIGHTS
from data_platform.catalog.profile_contracts_v3 import observed, unavailable


def reviewed_vehicle(identifier):
    # Fictitious costs/equipment fixture with the exact reviewed identity keys.
    vehicle = synthetic_vehicle(1)
    record = next(r for r in batch.configuration()["records"] if r["catalog_id"] == identifier)
    fields = dict(vehicle.fields)
    for field, value in record["identity"].items():
        fields[field] = observed(field, value, fields[field].sources)
    for field in batch.FIELDS:
        fields[field] = unavailable(field)
    if identifier == 55:
        for field, entry in record["evidence"].items():
            fields[field] = observed(field, entry["value"],
                (batch.Citation.model_validate(entry["source"]),))
    return vehicle.model_copy(update={"id": identifier, "fields": fields})


def test_scope_pin_and_preserved_source_hashes():
    manifest = batch.configuration()
    assert [r["catalog_id"] for r in manifest["records"]] == list(batch.IDS)
    assert hashlib.sha256(batch.PATH.read_bytes()).hexdigest() == batch.EXPECTED_SHA256
    statuses = [e["status"] for r in manifest["records"] for e in r["evidence"].values()]
    assert statuses.count("ADMISSIBLE") == 15
    assert statuses.count("PRESERVED_EXISTING") == 2
    assert statuses.count("BLOCKED") == 1
    for record in manifest["records"]:
        for entry in record["evidence"].values():
            if entry["representation"].startswith("normalized"):
                assert entry["original_document_sha256"] is None


@pytest.mark.parametrize("identifier,mass,power", [
    (31,1129,114),(34,1255,130),(44,1127,125),(55,1337,140),
    (62,1259,116),(76,1632,165),(108,1082,115),(124,1136,114)])
def test_exact_pair_and_idempotent_copy(identifier, mass, power):
    original = reviewed_vehicle(identifier)
    before = original.model_dump(mode="json")
    resolved, diagnostic = batch.resolve(original)
    assert resolved.fields["weight_kg"].value == mass
    assert resolved.fields["power_gasoline_cv"].value == power
    assert original.model_dump(mode="json") == before
    again, _ = batch.resolve(resolved)
    assert again.model_dump(mode="json") == resolved.model_dump(mode="json")
    values, _, _ = metrics(original)
    assert values["performance"]["value"] == Decimal(mass) / power
    assert values["performance"]["inputs_used"]["weight_kg"]["supplementary_evidence"]["identity_verified"]
    assert diagnostic["weight_kg"]["definition"] == "curb_order_of_march"


def test_existing_sentra_observation_and_citations_never_replaced():
    vehicle = reviewed_vehicle(55)
    resolved, diagnostic = batch.resolve(vehicle)
    assert resolved.model_dump(mode="json") == vehicle.model_dump(mode="json")
    assert all(d["status"] == "PRESERVED_EXISTING" for d in diagnostic.values())


def test_focus_power_only_unknown_positive_blocks_final():
    vehicle = reviewed_vehicle(80)
    resolved, diagnostic = batch.resolve(vehicle)
    assert resolved.fields["power_gasoline_cv"].value == 175
    assert resolved.fields["weight_kg"].kind == "unavailable"
    assert diagnostic["weight_kg"]["status"] == "BLOCKED"
    values, scenario, _ = metrics(vehicle)
    assert values["performance"]["value"] is None
    result = method.score_group([row(80)], {80: values}, DEFAULT_MULTIFACTOR_WEIGHTS, scenario)[0]
    assert result["multifactor"]["final_score"] is None
    assert "Focus Fastback SE Plus 2018" in values["performance"]["requirement_message"]
    assert not result["multifactor"]["criterion_calculations"]["weights_redistributed"]


@pytest.mark.parametrize("field,value", [
    ("fipe_code","999999-9"),("year_code","2019-5"),
    ("commercial_identity","Kicks SV"),("fuel","ethanol"),("transmission","manual")])
def test_identity_version_year_fuel_and_transmission_mismatch_fail_closed(field, value):
    vehicle = reviewed_vehicle(31)
    fields = dict(vehicle.fields)
    fields[field] = observed(field, value, fields[field].sources)
    vehicle = vehicle.model_copy(update={"fields": fields})
    resolved, diagnostic = batch.resolve(vehicle)
    assert all(d["status"] == "BLOCKED_IDENTITY" for d in diagnostic.values())
    assert all(resolved.fields[f].kind == "unavailable" for f in batch.FIELDS)
    assert vehicle.fields[field].value == value


@pytest.mark.parametrize("field,change", [
    ("weight_kg",{"unit":"kg gross"}),("weight_kg",{"definition":"gross_vehicle_mass"}),
    ("weight_kg",{"definition":"dry_mass"}),("weight_kg",{"definition":"test_mass"}),
    ("power_gasoline_cv",{"unit":"kW"}),("power_gasoline_cv",{"unit":"N.m"}),
    ("power_gasoline_cv",{"fuel_reference":"ethanol"}),
    ("weight_kg",{"value":"-1"}),("weight_kg",{"value":"NaN"}),
    ("power_gasoline_cv",{"value":True})])
def test_invalid_units_definitions_values_and_fuel_rejected(field, change):
    manifest = batch.configuration()
    manifest["records"][0]["evidence"][field].update(change)
    with pytest.raises(ValueError):
        batch.validate_batch(manifest)


def test_unknown_is_not_imputed_and_document_representation_not_mislabelled():
    manifest = batch.configuration()
    focus = next(r for r in manifest["records"] if r["catalog_id"] == 80)
    focus["evidence"]["weight_kg"]["value"] = "1396"
    with pytest.raises(ValueError, match="unknown"):
        batch.validate_batch(manifest)
    manifest = batch.configuration()
    ford = manifest["records"][1]["evidence"]["weight_kg"]
    ford["original_document_sha256"] = ford["source"]["sha256"]
    with pytest.raises(ValueError, match="original PDF"):
        batch.validate_batch(manifest)


def test_duplicate_and_other_identity_rejected():
    manifest = batch.configuration()
    manifest["records"][-1] = deepcopy(manifest["records"][0])
    with pytest.raises(ValueError, match="Duplicate"):
        batch.validate_batch(manifest)
    manifest = batch.configuration()
    manifest["records"][0]["catalog_id"] = 70
    with pytest.raises(ValueError, match="unauthorized"):
        batch.validate_batch(manifest)


def test_conflict_is_preserved_not_overwritten():
    vehicle = reviewed_vehicle(31)
    fields = dict(vehicle.fields)
    fields["weight_kg"] = observed("weight_kg", "999", (batch.Citation.model_validate(
        batch.configuration()["records"][0]["evidence"]["weight_kg"]["source"]),))
    vehicle = vehicle.model_copy(update={"fields": fields})
    resolved, diagnostic = batch.resolve(vehicle)
    assert diagnostic["weight_kg"]["status"] == "BLOCKED_CONFLICT"
    assert resolved.fields["weight_kg"].value is None
    assert vehicle.fields["weight_kg"].value == 999


def test_rejected_crosswalk_never_discards_independent_existing_evidence():
    vehicle = synthetic_vehicle(31)
    before = vehicle.model_dump(mode="json")
    resolved, diagnostic = batch.resolve(vehicle)
    assert all(d["status"] == "BLOCKED_IDENTITY" for d in diagnostic.values())
    assert resolved.model_dump(mode="json") == before
    assert vehicle.model_dump(mode="json") == before
    assert method.observation(resolved, "weight_kg", "kg", exact=True) is not None


def test_manifest_and_preserved_document_tampering_rejected(tmp_path, monkeypatch):
    path = tmp_path / "manifest.json"
    path.write_bytes(batch.PATH.read_bytes().replace(b"1129", b"1130"))
    monkeypatch.setattr(batch, "PATH", path)
    with pytest.raises(ValueError, match="integrity"):
        batch.configuration()
    # Fictitious retained document, independently pinned by the review contract.
    manifest = json.loads(batch.PATH.read_bytes().replace(b"1130", b"1129"))
    doc = tmp_path / "fixture.txt"
    doc.write_bytes(b"test-only source")
    digest = hashlib.sha256(doc.read_bytes()).hexdigest()
    for record in manifest["records"]:
        for entry in record["evidence"].values():
            entry["source"].update(document=doc.name, sha256=digest)
            if entry["representation"] == "original_manufacturer_document":
                entry["original_document_sha256"] = digest
    assert batch.verify_preserved_sources(tmp_path, manifest) == {doc.name:digest}
    doc.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="integrity"):
        batch.verify_preserved_sources(tmp_path, manifest)


def test_gasoline_power_not_reused_for_ethanol_and_lower_ratio_preferred():
    values, _, _ = metrics(reviewed_vehicle(31), fuel_strategy="ethanol_hydrated",
        city_consumption_km_l="8", highway_consumption_km_l="10")
    assert values["performance"]["value"] is None
    values, scenario, _ = metrics(reviewed_vehicle(31))
    second = deepcopy(values)
    second["performance"]["value"] = values["performance"]["value"] + 1
    weights = {k:100 if k == "performance" else 0 for k in DEFAULT_MULTIFACTOR_WEIGHTS}
    result = method.score_group([row(31),row(34)], {31:values,34:second}, weights, scenario)
    assert result[0]["vehicle"]["catalog_id"] == 31
    assert result[0]["score"] > result[1]["score"]


def test_eight_complete_seven_positive_criteria_one_unknown_and_no_other_id_promoted():
    all_metrics = {identifier:metrics(reviewed_vehicle(identifier))[0] for identifier in batch.IDS}
    scenario = metrics()[1]
    rows = method.score_group([row(i) for i in batch.IDS], all_metrics, DEFAULT_MULTIFACTOR_WEIGHTS, scenario)
    assert {r["vehicle"]["catalog_id"] for r in rows if r["multifactor"]["final_score"] is not None} == set(batch.IDS)-{80}
    assert all(r["multifactor"]["criterion_calculations"]["requested_count"] == 7 for r in rows)
    unrelated = synthetic_vehicle(1)
    assert batch.resolve(unrelated)[0] is unrelated


def test_http_derived_supplementary_inputs_and_live_weight_effect(service, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    from data_platform.catalog.profile_pilot_v4 import fingerprint
    monkeypatch.setenv("ACADEMIC_COHORT_ENABLED", "true")
    monkeypatch.setenv("SIGRA_DERIVED_PERSONALIZATION_ENABLED", "true")
    vehicle = reviewed_vehicle(31)
    persisted = next(r for r in service.repository.rows if r.catalog_id == 31)
    persisted.payload = vehicle.model_dump(mode="json")
    persisted.payload_fingerprint = fingerprint(persisted.payload)
    persisted.fipe_code = vehicle.fields["fipe_code"].value
    persisted.year_code = vehicle.fields["year_code"].value
    persisted.label = vehicle.label
    persisted.purchase_price_brl = vehicle.fields["price_brl"].value
    unchanged_payload = deepcopy(persisted.payload)
    monkeypatch.setattr(main, "get_academic_service", lambda _:service)
    main.app.dependency_overrides[main.get_db] = lambda:object()
    try:
        client = TestClient(main.app)  # no lifespan/bootstrap or database
        body = request(service, multifactor_profile=profile()).model_dump(mode="json")
        first = client.post("/recommendations?envelope=true", json=body)
        assert first.status_code == 200
        item = next(r for r in first.json()["recommendations"] if r["vehicle"]["catalog_id"] == 31)
        component = next(c for c in item["multifactor"]["components"] if c["component"] == "performance")
        assert component["available"] and item["multifactor"]["final_score"] is not None
        assert component["inputs_used"]["weight_kg"]["value"] == "1129"
        assert component["inputs_used"]["power_gasoline_cv"]["value"] == "114"
        assert component["inputs_used"]["weight_kg"]["supplementary_evidence"]["version"] == batch.VERSION
        # The underlying technical DTO/snapshot is still the original, unknown mass.
        assert item["vehicle"]["technical_fields"]["weight_kg"]["value"] is None
        body["multifactor_profile"]["weights"].update(performance="25", total_cost="10")
        second = client.post("/recommendations?envelope=true", json=body)
        assert second.status_code == 200
        updated = next(r for r in second.json()["recommendations"] if r["vehicle"]["catalog_id"] == 31)
        changed = next(c for c in updated["multifactor"]["components"] if c["component"] == "performance")
        assert Decimal(changed["contribution"]) > Decimal(component["contribution"])
        assert updated["monthly_total_cost"] == item["monthly_total_cost"]
        assert persisted.payload == unchanged_payload
        monkeypatch.delenv("SIGRA_DERIVED_PERSONALIZATION_ENABLED")
        assert client.post("/recommendations?envelope=true", json=body).status_code == 422
    finally:
        main.app.dependency_overrides.clear()
