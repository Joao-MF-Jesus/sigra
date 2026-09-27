"""Synthetic boundary tests; actual immutable source replay runs outside Git."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json

import pytest

from data_platform.catalog import batch3_academic_v4 as batch
from data_platform.catalog.adapter import SourceArchive
from data_platform.catalog.crosswalk import review_batch
from data_platform.catalog.profile_contracts_v3 import Citation, ProfileVehicle, blank_fields, observed
from data_platform.catalog.profile_pilot_v4 import evaluate_vehicle


@pytest.fixture
def case(monkeypatch):
    row = deepcopy(batch.load_manifest()["records"][0])
    decision = next(r for r in review_batch()["decisions"] if r["id"] == 55)
    fields = blank_fields()
    for key, value in {**row["identity"], "price_brl": str(decision["observed"]["price_brl"]),
                       "consumption_city": str(decision["observed"]["city_km_l"]),
                       "consumption_highway": str(decision["observed"]["highway_km_l"])}.items():
        provider = "pbev" if key in {"fuel", "transmission", "consumption_city", "consumption_highway"} else "fipe"
        source = decision["review"]["source_references"][int(provider == "pbev")]
        citation = Citation(provider=provider, url=source["url"], sha256=source["sha256"],
                            document="Synthetic test boundary", locator=key, collected_at=source["collected_at"])
        fields[key] = observed(key, value, (citation,))
    vehicle = ProfileVehicle(id=55, label=row["identity"]["commercial_identity"],
                             identity_status="identity_approved", fields=fields)
    body = b"%PDF synthetic immutable fixture; no production observations"
    row["source"]["sha256"] = hashlib.sha256(body).hexdigest()
    class Archive:
        def bytes(self, source): return body
    monkeypatch.setattr(batch, "prepare_batch", lambda *args: None)
    return vehicle, row, Archive()


def test_id55_three_scenarios_four_profiles_and_no_operational_use(case):
    vehicle, row, archive = case
    result = batch.admit_vehicle(vehicle, row, archive)
    assert result == batch.admit_vehicle(result, row, archive)
    for scenario in ("low", "base", "high"):
        for profile in ("app", "familia", "estrada", "suv"):
            report = evaluate_vehicle(result, profile, scenario, "2026-09")
            assert report["academic_test_ready"] and report["scenario_tco_complete"]
            assert not report["observed_tco_complete"]
            assert not report["operationally_active"] and not report["recommended"]
            assert not report["operational_ranking"]
    assert vehicle.fields["airbags"].value is None
    assert result.fields["airbags"].value == Decimal(2)
    assert result.fields["width_with_mirrors_mm"].value is None


@pytest.mark.parametrize("key,value", [("model_year", 2019), ("variant", "2.0 SL"),
    ("engine", "1.8 16V"), ("fuel", "gasoline"), ("transmission", "automatic"),
    ("market", "US"), ("source_kind", "generic_manual"),
    ("source_kind", "latin_ncap_different_protocol"), ("status", "if_equipped"),
    ("unresolved_restrictions", ["VIN not bound"])] )
def test_wrong_document_scope_rejected(case, key, value):
    vehicle, row, archive = case
    row["review"][key] = value
    with pytest.raises(ValueError): batch.admit_vehicle(vehicle, row, archive)


@pytest.mark.parametrize("key,value", [("fipe_code", "000000-0"), ("year_code", "2019-5"),
    ("commercial_identity", "Sentra SL 2.0 FlexStart 16V Aut."), ("fuel", "gasoline"),
    ("transmission", "automatic"), ("reference_month", "2026-08")])
def test_wrong_canonical_identity_rejected(case, key, value):
    vehicle, row, archive = case
    row["identity"][key] = value
    with pytest.raises(ValueError): batch.admit_vehicle(vehicle, row, archive)


@pytest.mark.parametrize("condition", ["optional", "if_equipped", "unknown", "absent"])
def test_qualifications_cannot_be_standard_equipment(case, condition):
    vehicle, row, archive = case
    row["fields"]["airbags"]["condition"] = condition
    with pytest.raises(ValueError): batch.admit_vehicle(vehicle, row, archive)


@pytest.mark.parametrize("name", ["airbags", "abs", "esc"])
def test_missing_safety_stays_unknown_and_only_blocks_safety_profiles(case, name):
    vehicle, row, archive = case
    row["fields"].pop(name)
    result = batch.admit_vehicle(vehicle, row, archive)
    assert result.fields[name].value is None and result.fields[name].kind == "unavailable"
    assert evaluate_vehicle(result, "app", "base", "2026-09")["academic_test_ready"]
    for profile in ("familia", "estrada"):
        assert not evaluate_vehicle(result, profile, "base", "2026-09")["academic_test_ready"]


@pytest.mark.parametrize("name", sorted(batch.REQUIRED))
def test_missing_critical_input_rejected(case, name):
    vehicle, row, archive = case
    row["fields"].pop(name)
    with pytest.raises(ValueError): batch.admit_vehicle(vehicle, row, archive)


@pytest.mark.parametrize("unit", ["m", "cm", "unknown", "mm_with_mirrors"])
def test_invalid_units_rejected(case, unit):
    vehicle, row, archive = case
    row["fields"]["width_mm"]["unit"] = unit
    with pytest.raises(ValueError): batch.admit_vehicle(vehicle, row, archive)


def test_tampered_document_rejected(case):
    vehicle, row, archive = case
    row["source"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash"): batch.admit_vehicle(vehicle, row, archive)


def test_source_archive_rejects_tampered_bytes(tmp_path):
    path = tmp_path / "document.pdf"
    path.write_bytes(b"%PDF initial")
    source = {"cache_file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    path.write_bytes(b"%PDF changed")
    with pytest.raises(ValueError): SourceArchive((tmp_path,)).bytes(source)


@pytest.mark.parametrize("field", ["price_brl", "consumption_city", "consumption_highway"])
def test_official_values_cannot_be_replaced(case, field):
    vehicle, row, archive = case
    values = dict(vehicle.fields)
    old = values[field]
    values[field] = observed(field, old.value + 1, old.sources)
    wrong = ProfileVehicle.model_validate({**vehicle.model_dump(), "fields": values})
    with pytest.raises(ValueError, match="price/consumption"): batch.admit_vehicle(wrong, row, archive)


def test_remove_reinsert_and_replay_duplicates(case, monkeypatch):
    vehicle, row, archive = case
    monkeypatch.setattr(batch, "load_manifest", lambda *a: {"records": [row]})
    first = batch.batch3_matrix((vehicle,), archive)
    assert first == batch.batch3_matrix(first, archive)
    assert first == batch.batch3_matrix((vehicle,), archive)
    with pytest.raises(ValueError, match="Duplicate input"):
        batch.batch3_matrix((vehicle, vehicle), archive)
    with pytest.raises(ValueError, match="Missing reviewed"):
        batch.batch3_matrix((), archive)
    duplicate = ProfileVehicle.model_validate({**vehicle.model_dump(), "id": 56})
    with pytest.raises(ValueError, match="Duplicate canonical"):
        batch.batch3_matrix((vehicle, duplicate), archive)


def test_partial_universe_is_54_not_60_and_backlog_is_preserved():
    data = batch.load_manifest()
    plan = json.loads(batch.COLLECTION_PATH.read_text(encoding="utf-8"))
    ids = plan["legacy_ids"] + plan["existing_new_ids"] + plan["admitted_ids"]
    assert len(ids) == len(set(ids)) == 54
    assert plan["unfilled_new_slots"] == 6 and [r["id"] for r in data["records"]] == [55]
    assert set(plan["available_reserved_ids"]) | set(plan["existing_new_ids"]) == set(range(35, 101))


@pytest.mark.parametrize("mutation", ["duplicate", "wrong_catalog", "wrong_unit_scope", "activation"])
def test_manifest_invalid_mutations(tmp_path, mutation):
    data = batch.load_manifest()
    plan = json.loads(batch.COLLECTION_PATH.read_text(encoding="utf-8"))
    if mutation == "duplicate": data["records"].append(deepcopy(data["records"][0]))
    elif mutation == "wrong_catalog": data["records"][0]["catalog"]["model_year"] = 2019
    elif mutation == "wrong_unit_scope": data["records"][0]["fields"]["insurance_annual_brl"] = {}
    else: plan["publication_authorized"] = True
    manifest = tmp_path / "manifest.json"; manifest.write_text(json.dumps(data), encoding="utf-8")
    collection = tmp_path / "collection.json"; collection.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ValueError): batch.load_manifest(manifest, collection)
