"""Offline v5 regressions; synthetic source bytes never enter production evidence."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest

from data_platform.catalog import academic_cohort_v5 as v5
from data_platform.catalog.adapter import SourceArchive
from data_platform.catalog.profile_contracts_v3 import observed


@pytest.fixture
def fixture_source(tmp_path, monkeypatch):
    def make(identifier=62):
        record = deepcopy(next(r for r in v5.load_evidence()["records"] if r["id"] == identifier))
        year = record["catalog_target"]["model_year"]
        sections = []
        for fact in record["fields"]:
            title = fact["source_section"]
            section = next((s for s in sections if s["titulo"] == title), None)
            if section is None:
                section = {"titulo": title, "itens": []}
                sections.append(section)
            fact["locator"] = f"secoes[{sections.index(section)}].itens[{len(section['itens'])}]"
            section["itens"].append({"label": fact["source_label"], "valor": fact["source_value"]})
        for fact in record["mechanical_evidence"]:
            section = next((s for s in sections if s["titulo"] == fact["section"]), None)
            if section is None:
                section = {"titulo": fact["section"], "itens": []}
                sections.append(section)
            section["itens"].append({"label": fact["label"], "valor": fact["value"]})
        carpedia = {"ref": "09-2026", "versao": record["source_identity"], "ano": str(year),
                    "fonte": record["upstream_source"], "secoes": sections}
        row = {**record["pbev_identity"], "propulsion_type": "combustion",
               "fossil_city_km_l": "10", "fossil_highway_km_l": "12",
               "raw": {"cycle_year": year, "row_hash": record["pbev_row_hash"],
                       "page_number": record["pbev_locator"]["page"], "row_number": record["pbev_locator"]["row"]}}
        values = {"fipe": {**record["fipe_identity"], "TipoVeiculo": 1},
                  "pbev_parse": {"rows": [row]}, "carpedia": carpedia, "pbev": b"synthetic official-byte fixture"}
        def persist():
            for provider, content in values.items():
                raw = content if isinstance(content, bytes) else json.dumps(content, ensure_ascii=False).encode()
                ref = record["sources"][provider]
                ref["cache_file"] = f"synthetic-{identifier}-{provider}.json"
                ref["sha256"] = hashlib.sha256(raw).hexdigest()
                (tmp_path / ref["cache_file"]).write_bytes(raw)
            monkeypatch.setitem(v5.AUDITED_ASSET_BY_YEAR, year, SimpleNamespace(sha256=record["sources"]["pbev"]["sha256"]))
        persist()
        return record, SourceArchive((tmp_path,)), values, persist
    return make


@pytest.mark.parametrize("identifier", [62, 65, 72, 76, 77, 88, 94])
def test_each_reviewed_binding_offline(fixture_source, identifier):
    record, archive, _, _ = fixture_source(identifier)
    first = v5.admit_record(record, archive)
    assert first == v5.admit_record(record, archive)
    assert first.id == identifier and first.identity_status == "identity_approved"
    assert first.fields["price_brl"].sources[0].provider == "fipe"
    assert first.fields["consumption_city"].sources[0].provider == "pbev"
    assert first.fields["width_mm"].sources[0].provider == "carpedia"
    for field in ("airbags", "abs", "esc", "width_with_mirrors_mm", "maintenance_annual_brl"):
        assert first.fields[field].kind == "unavailable" and first.fields[field].value is None
    for scenario in v5.SCENARIOS:
        result = v5.evaluate_vehicle(first, "app", scenario, "2026-09")
        assert result["academic_test_ready"]
        assert not result["operationally_active"] and not result["recommended"]


@pytest.mark.parametrize("provider", ["fipe", "carpedia", "pbev", "pbev_parse"])
def test_tampered_or_missing_cache_rejected(fixture_source, provider):
    record, archive, _, _ = fixture_source()
    path = archive.directories[0] / record["sources"][provider]["cache_file"]
    path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        v5.admit_record(record, archive)
    path.unlink()
    with pytest.raises(ValueError, match="hash mismatch"):
        v5.admit_record(record, archive)


@pytest.mark.parametrize("field,value", [("AnoModelo", 2019), ("Combustivel", "Diesel"),
    ("Modelo", "Different trim"), ("TipoVeiculo", 2), ("MesReferencia", "agosto de 2026"), ("CodigoFipe", "000000-0")])
def test_fipe_identity_does_not_use_similarity(fixture_source, field, value):
    record, archive, values, persist = fixture_source()
    values["fipe"][field] = value
    persist()
    with pytest.raises(ValueError):
        v5.admit_record(record, archive)


@pytest.mark.parametrize("field,value", [("version_name", "COMFORTLINE/HIGHLINE"),
    ("transmission_code", "DCT"), ("fuel_type", "diesel"), ("motor_description", "2.0-16V")])
def test_pbev_changed_and_aggregated_binding_rejected(fixture_source, field, value):
    record, archive, values, persist = fixture_source()
    values["pbev_parse"]["rows"][0][field] = value
    persist()
    with pytest.raises(ValueError):
        v5.admit_record(record, archive)


def test_duplicate_pbev_row_rejected(fixture_source):
    record, archive, values, persist = fixture_source()
    values["pbev_parse"]["rows"] *= 2
    persist()
    with pytest.raises(ValueError, match="ambiguous"):
        v5.admit_record(record, archive)


@pytest.mark.parametrize("field,value", [("ano", "2021"), ("ref", "08-2026"),
    ("versao", {"id": 123, "nome": "similar"}), ("fonte", {"fonte": "unreviewed"})])
def test_carpedia_identity_year_and_provenance_rejected(fixture_source, field, value):
    record, archive, values, persist = fixture_source()
    values["carpedia"][field] = value
    persist()
    with pytest.raises(ValueError, match="mismatch"):
        v5.admit_record(record, archive)


@pytest.mark.parametrize("change", ["unit", "zero", "duplicate", "missing", "locator", "source_value"])
def test_technical_fields_fail_closed(fixture_source, change):
    record, archive, _, _ = fixture_source()
    fact = next(f for f in record["fields"] if f["name"] == "width_mm")
    if change == "unit":
        fact["unit"] = "cm"
    elif change == "zero":
        fact["value"] = "0"
    elif change == "duplicate":
        record["fields"].append(deepcopy(fact))
    elif change == "missing":
        record["fields"].remove(fact)
    else:
        fact[change] = "unreviewed"
    with pytest.raises(ValueError):
        v5.admit_record(record, archive)


def test_generic_automatic_does_not_prove_cvt(fixture_source):
    record, archive, values, persist = fixture_source(72)
    for section in values["carpedia"]["secoes"]:
        for item in section["itens"]:
            if item["label"] == "Câmbio (tipo)":
                item["valor"] = "Automático"
    persist()
    with pytest.raises(ValueError):
        v5.admit_record(record, archive)


def test_no_aspiration_inferred_from_pbev_omission(fixture_source):
    record, archive, _, _ = fixture_source(88)
    assert record["pbev_identity"]["motor_description"] == "2.0-16V"
    assert record["engine_binding"]["aspiration"] == "Turbocompressor"
    assert v5.admit_record(record, archive).fields["transmission"].value == "automatic"


def test_wheel_configuration_conflict_rejected(fixture_source):
    record, archive, values, persist = fixture_source()
    record["pbev_identity"]["version_name"] = "COMFORTLINE aro 17"
    values["pbev_parse"]["rows"][0]["version_name"] = "COMFORTLINE aro 17"
    persist()
    with pytest.raises(ValueError, match="Wheel"):
        v5.admit_record(record, archive)


@pytest.mark.parametrize("part", ["fipe_identity", "pbev_identity"])
def test_missing_identity_fields_rejected(fixture_source, part):
    record, archive, _, _ = fixture_source()
    record[part].pop(next(iter(record[part])))
    with pytest.raises(ValueError, match="Incomplete"):
        v5.admit_record(record, archive)


@pytest.fixture
def composition(fixture_source, monkeypatch):
    record, archive, _, _ = fixture_source()
    sample = v5.admit_record(record, archive)
    config = deepcopy(v5.configuration())
    inventory = []
    for identifier in config["baseline_inventory_ids"]:
        item = sample.model_copy(deep=True, update={"id": identifier})
        item.fields["fipe_code"] = observed("fipe_code", f"{100000+identifier:06}-1", item.fields["fipe_code"].sources)
        inventory.append(item)
    config["baseline_vehicle_fingerprints"] = {str(v.id): v5.fingerprint(v) for v in inventory}
    monkeypatch.setattr(v5, "configuration", lambda: config)
    monkeypatch.setattr(v5, "load_evidence", lambda: {"records": [{"id": i} for i in config["additional_selected_ids"]]})
    def admitted(r, _):
        item = sample.model_copy(deep=True, update={"id": r["id"]})
        item.fields["fipe_code"] = observed("fipe_code", f"{200000+item.id:06}-1", item.fields["fipe_code"].sources)
        return item
    monkeypatch.setattr(v5, "admit_record", admitted)
    # Membership tests isolate composition from costly profile computation.
    monkeypatch.setattr(v5, "evaluate_vehicle", lambda vehicle, profile, scenario, month:
                        {"academic_test_ready": profile == "app", "operationally_active": False, "recommended": False})
    return inventory, archive, config


def test_partial_never_announces_sixty_or_activates(composition):
    inventory, archive, config = composition
    report = v5.build_cohort(inventory, archive)
    assert report["decision"] == "ACADEMIC_COHORT_V5_PARTIAL"
    assert report["inventory_count"] == 67 and report["cohort_size"] == 50
    assert report["unfilled_slots"] == 10
    assert set(config["baseline_ready_ids"]) <= set(report["selected_ids"])
    assert len(set(report["selected_ids"])) == 50
    assert report["operationally_active"] == report["recommended"] == 0
    assert report["operational_ranking"] == []
    for row in report["states"]:
        if row["id"] in v5.HOLDOUTS:
            assert row["legacy_holdout"] and row["inventory_registered"]
            assert not row["academic_cohort_selected"] and not row["academic_test_ready"]


def test_logical_removal_reinsertion_preserves_inventory_and_input(composition):
    inventory, archive, _ = composition
    before = v5.fingerprint(inventory)
    original = v5.build_cohort(inventory, archive)
    removed = v5.build_cohort(inventory, archive, excluded_ids=(62,))
    assert removed["inventory_count"] == original["inventory_count"]
    assert removed["cohort_size"] == original["cohort_size"] - 1
    assert next(r for r in removed["states"] if r["id"] == 62)["exclusion_reason"] == "logical_exclusion"
    assert original == v5.build_cohort(inventory, archive)
    assert before == v5.fingerprint(inventory)


def test_frozen_inventory_mutation_rejected(composition):
    inventory, archive, _ = composition
    inventory[0] = inventory[0].model_copy(update={"label": "changed"})
    with pytest.raises(ValueError, match="Frozen"):
        v5.build_cohort(inventory, archive)


def test_unknown_exclusion_rejected(composition):
    inventory, archive, _ = composition
    with pytest.raises(ValueError, match="Unknown"):
        v5.build_cohort(inventory, archive, excluded_ids=(1000,))


def test_duplicate_canonical_identity_rejected(composition):
    inventory, archive, config = composition
    ready = [v for v in inventory if v.id in config["baseline_ready_ids"]]
    ready[1].fields["fipe_code"] = ready[0].fields["fipe_code"]
    config["baseline_vehicle_fingerprints"] = {str(v.id): v5.fingerprint(v) for v in inventory}
    with pytest.raises(ValueError, match="Duplicate canonical"):
        v5.build_cohort(inventory, archive)


def test_lost_profile_readiness_is_not_quota_fallback(composition, monkeypatch):
    inventory, archive, _ = composition
    monkeypatch.setattr(v5, "evaluate_vehicle", lambda *args: {"academic_test_ready": False})
    with pytest.raises(ValueError, match="no longer testable"):
        v5.build_cohort(inventory, archive)


def test_complete_requires_sixty_distinct_ready_not_inventory_count(composition):
    inventory, archive, config = composition
    config["additional_selected_ids"] = sorted(set(range(1, 101)) - set(config["baseline_inventory_ids"]))[:17]
    report = v5.build_cohort(inventory, archive)
    assert report["inventory_count"] == 77
    assert report["cohort_size"] == report["academic_test_ready_count"] == 60
    assert len(set(report["selected_ids"])) == 60
    assert report["decision"] == "ACADEMIC_COHORT_V5_COMPLETE"
    assert not set(report["holdout_ids"]) & set(report["selected_ids"])
    assert report["operationally_active"] == report["recommended"] == 0


@pytest.mark.parametrize("key,value", [("target_size", 59), ("maximum_additional", 18),
    ("publication_authorized", True), ("operational_activation_authorized", True),
    ("holdout_ids", []), ("additional_selected_ids", [1])])
def test_config_cannot_relax_authorization(tmp_path, key, value):
    config = v5.configuration()
    config[key] = value
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError):
        v5.configuration(path)


def test_collection_budget_and_decisions_match():
    collection = json.loads((v5.ROOT / "academic_cohort_v5_collection.json").read_text(encoding="utf-8"))
    assert collection["admitted_ids"] == v5.configuration()["additional_selected_ids"]
    assert not {61, 74} & set(collection["admitted_ids"])
    for provider, budget in collection["budget"].items():
        attempts = [r for r in collection["attempts"] if r["provider"] == provider]
        discovery = collection["search_queries"] if provider == "public_documents" else 0
        assert len(attempts) + discovery == budget["executed"] <= budget["limit"]
        assert budget["remaining"] == budget["limit"] - budget["executed"]
        assert all("@" not in r["url"] and "?" not in r["url"] for r in attempts)
    assert collection["raw_responses_in_repository"] is False
