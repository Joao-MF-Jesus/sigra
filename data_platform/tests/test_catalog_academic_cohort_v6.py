"""Offline v6 regressions; all synthetic source bytes confined to tmp_path."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest

from data_platform.catalog import academic_cohort_v6 as v6
from data_platform.catalog.adapter import SourceArchive
from data_platform.catalog.profile_contracts_v3 import observed


@pytest.fixture
def source_fixture(tmp_path, monkeypatch):
    def make(identifier=96):
        record = deepcopy(next(r for r in v6.load_evidence()["records"] if r["id"] == identifier))
        sections = []
        for fact in record["fields"]:
            section = next((s for s in sections if s["titulo"] == fact["source_section"]), None)
            if section is None:
                section = {"titulo": fact["source_section"], "itens": []}
                sections.append(section)
            fact["locator"] = f"secoes[{sections.index(section)}].itens[{len(section['itens'])}]"
            section["itens"].append({"label": fact["source_label"], "valor": fact["source_value"]})
        for fact in record["mechanical_evidence"]:
            section = next((s for s in sections if s["titulo"] == fact["section"]), None)
            if section is None:
                section = {"titulo": fact["section"], "itens": []}
                sections.append(section)
            section["itens"].append({"label": fact["label"], "valor": fact["value"]})
        year = record["catalog_target"]["model_year"]
        values = {"fipe": {**record["fipe_identity"], "TipoVeiculo": 1},
            "carpedia": {"ref": record["technical_reference"], "versao": record["source_identity"],
                         "ano": str(year), "fonte": record["upstream_source"], "secoes": sections},
            "pbev_parse": {"rows": [{**record["pbev_identity"], "propulsion_type": "combustion",
                "fossil_city_km_l": "12", "fossil_highway_km_l": "14",
                "raw": {"cycle_year": year, "row_hash": record["pbev_row_hash"],
                        "page_number": record["pbev_locator"]["page"], "row_number": record["pbev_locator"]["row"]}}]},
            "pbev": b"synthetic audited-byte fixture"}
        contract = json.loads((v6.ROOT / "profile_sources_v3.json").read_text(encoding="utf-8"))
        for name in ("kwid_manual", "kwid_catalog"):
            raw = ("synthetic conflict " + name).encode()
            ref = contract["sources"][name]
            ref["cache_file"] = name + ".fixture"
            ref["sha256"] = hashlib.sha256(raw).hexdigest()
            (tmp_path / ref["cache_file"]).write_bytes(raw)
        contract_bytes = json.dumps(contract).encode()
        (tmp_path / "profile_sources_v3.json").write_bytes(contract_bytes)
        record["known_conflict_contract_sha256"] = hashlib.sha256(contract_bytes).hexdigest()
        monkeypatch.setattr(v6, "ROOT", tmp_path)
        def persist():
            for provider, content in values.items():
                raw = content if isinstance(content, bytes) else json.dumps(content, ensure_ascii=False).encode()
                ref = record["sources"][provider]
                ref["cache_file"] = f"synthetic-{identifier}-{provider}.json"
                ref["sha256"] = hashlib.sha256(raw).hexdigest()
                (tmp_path / ref["cache_file"]).write_bytes(raw)
            monkeypatch.setitem(v6.AUDITED_ASSET_BY_YEAR, year, SimpleNamespace(sha256=record["sources"]["pbev"]["sha256"]))
        persist()
        return record, SourceArchive((tmp_path,)), values, persist
    return make


@pytest.mark.parametrize("identifier,blocker", [(35, "KWID_LENGTH_3679_VS_3680_UNRESOLVED"), (96, None)])
def test_review_preserves_real_blockers_and_idempotence(source_fixture, identifier, blocker):
    record, archive, _, _ = source_fixture(identifier)
    first = v6.review_record(record, archive)
    assert first == v6.review_record(record, archive)
    vehicle, blockers = first
    assert blocker in blockers if blocker else not blockers
    assert vehicle.fields["esc"].value is None
    assert vehicle.fields["airbags"].value is None  # stars are not inventory
    if identifier == 35:
        assert vehicle.fields["length_mm"].value is None
        assert len(vehicle.fields["length_mm"].sources) == 2
    else:
        assert vehicle.fields["reference_month"].value == "2026-10"
    for scenario in v6.SCENARIOS:
        row = v6.evaluate_vehicle(vehicle, "app", scenario, "2026-09")
        assert row["academic_test_ready"] is (identifier == 96)
        assert row["price_reference_month"] == vehicle.fields["reference_month"].value
        assert row["scenario_costs"]["price_reference_month"] == row["price_reference_month"]
        assert not row["operationally_active"] and not row["recommended"]
        assert row["scenario_tco_complete"] and not row["observed_tco_complete"]


@pytest.mark.parametrize("provider", ["fipe", "pbev", "pbev_parse", "carpedia"])
def test_tampered_cache_fails_closed(source_fixture, provider):
    record, archive, _, _ = source_fixture()
    (archive.directories[0] / record["sources"][provider]["cache_file"]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        v6.review_record(record, archive)


@pytest.mark.parametrize("field,value", [("AnoModelo", 2021), ("Modelo", "similar EXL"),
    ("Combustivel", "Diesel"), ("CodigoFipe", "000000-0"), ("TipoVeiculo", 2)])
def test_exact_fipe_identity_required(source_fixture, field, value):
    record, archive, values, persist = source_fixture()
    values["fipe"][field] = value
    persist()
    with pytest.raises(ValueError):
        v6.review_record(record, archive)


@pytest.mark.parametrize("field,value", [("version_name", "EX/EXL"), ("fuel_type", "gasoline"),
    ("transmission_code", "A-6"), ("motor_description", "2.0-16V")])
def test_pbev_scope_mismatch_rejected(source_fixture, field, value):
    record, archive, values, persist = source_fixture()
    values["pbev_parse"]["rows"][0][field] = value
    persist()
    with pytest.raises(ValueError):
        v6.review_record(record, archive)


@pytest.mark.parametrize("field,value", [("ano", "2021"), ("ref", "changed"),
    ("versao", {"id": 123, "nome": "similar"}), ("fonte", {"fonte": "unreviewed"})])
def test_carpedia_identity_provenance_rejected(source_fixture, field, value):
    record, archive, values, persist = source_fixture()
    values["carpedia"][field] = value
    persist()
    with pytest.raises(ValueError):
        v6.review_record(record, archive)


@pytest.mark.parametrize("change", ["unit", "zero", "duplicate", "missing", "locator", "source_value"])
def test_fields_units_and_missingness(source_fixture, change):
    record, archive, _, _ = source_fixture()
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
        v6.review_record(record, archive)


def test_duplicate_pbev_rejected(source_fixture):
    record, archive, values, persist = source_fixture()
    values["pbev_parse"]["rows"] *= 2
    persist()
    with pytest.raises(ValueError, match="ambiguous"):
        v6.review_record(record, archive)


def test_generic_automatic_not_cvt(source_fixture):
    record, archive, values, persist = source_fixture()
    for section in values["carpedia"]["secoes"]:
        for item in section["itens"]:
            if item["label"] == "Câmbio (tipo)":
                item["valor"] = "Automático"
    persist()
    with pytest.raises(ValueError):
        v6.review_record(record, archive)


def test_conflict_contract_tampering_rejected(source_fixture):
    record, archive, _, _ = source_fixture(35)
    record["known_conflict_contract_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="conflict contract"):
        v6.review_record(record, archive)


@pytest.fixture
def composition(source_fixture, monkeypatch):
    record, archive, values, persist = source_fixture()
    values["fipe"]["MesReferencia"] = record["fipe_identity"]["MesReferencia"] = "setembro de 2026"
    persist()
    sample, blockers = v6.review_record(record, archive)
    assert not blockers
    config = deepcopy(v6.configuration())
    inventory, states = [], []
    for identifier in config["baseline_inventory_ids"]:
        data = sample.model_dump()
        data["id"] = identifier
        data["fields"]["fipe_code"] = observed("fipe_code", f"{identifier:06}-0", sample.fields["fipe_code"].sources).model_dump()
        vehicle = v6.ProfileVehicle.model_validate(data)
        inventory.append(vehicle)
        holdout = identifier in v6.HOLDOUTS
        states.append({"id": identifier, "academic_cohort_selected": not holdout, "academic_test_ready": not holdout,
            "legacy_holdout": holdout, "ready_profiles": [] if holdout else ["app"], "evaluations": {},
            "operationally_active": False, "recommended": False})
    baseline = {"states": states, "selected_ids": config["baseline_ready_ids"]}
    config["baseline_vehicle_fingerprints"] = {str(v.id): v6.fingerprint(v) for v in inventory}
    config["baseline_cohort_fingerprint"] = v6.fingerprint(baseline)
    config["additional_selected_ids"] = [96]
    monkeypatch.setattr(v6, "configuration", lambda: config)
    monkeypatch.setattr(v6, "load_evidence", lambda: {"records": [record]})
    return inventory, archive, baseline, record, config


def test_logical_exclusion_reinsertion_and_payload(composition):
    inventory, archive, baseline, _, _ = composition
    before = v6.fingerprint(inventory)
    first = v6.build_cohort(inventory, archive, baseline_report=baseline)
    assert first["cohort_size"] == first["academic_test_ready_count"] == 51
    assert len(first["academic_payload"]) == 51
    assert not set(first["selected_ids"]) & set(first["holdout_ids"])
    removed = v6.build_cohort(inventory, archive, baseline_report=baseline, excluded_ids=(96,))
    assert removed["inventory_count"] == first["inventory_count"] and removed["cohort_size"] == 50
    assert v6.fingerprint(first) == v6.fingerprint(v6.build_cohort(inventory, archive, baseline_report=baseline))
    assert v6.fingerprint(inventory) == before
    assert first["operationally_active"] == first["recommended"] == 0 and first["operational_ranking"] == []
    assert all(r["mode"] == "academic_only" and not r["operationally_active"] for r in first["academic_payload"])


@pytest.mark.parametrize("change", ["baseline_model", "baseline_report", "unknown_exclusion", "blocked_selection", "duplicate_identity"])
def test_composition_fail_closed(composition, change):
    inventory, archive, baseline, record, config = composition
    args = {}
    if change == "baseline_model":
        inventory[0] = inventory[0].model_copy(update={"label": "changed"})
    elif change == "baseline_report":
        baseline["selected_ids"] = []
    elif change == "unknown_exclusion":
        args["excluded_ids"] = (101,)
    elif change == "blocked_selection":
        record["fipe_identity"]["MesReferencia"] = "novembro de 2026"
    else:
        candidate = next(v for v in inventory if v.id in config["baseline_ready_ids"])
        data = candidate.model_dump()
        data["fields"]["fipe_code"] = observed("fipe_code", record["fipe_identity"]["CodigoFipe"], candidate.fields["fipe_code"].sources).model_dump()
        data["fields"]["year_code"] = observed("year_code", "2020-5", candidate.fields["year_code"].sources).model_dump()
        inventory[inventory.index(candidate)] = v6.ProfileVehicle.model_validate(data)
        config["baseline_vehicle_fingerprints"][str(candidate.id)] = v6.fingerprint(next(v for v in inventory if v.id == candidate.id))
    with pytest.raises(ValueError):
        v6.build_cohort(inventory, archive, baseline_report=baseline, **args)


def test_configuration_and_source_verified_admissions():
    config = v6.configuration()
    assert config["additional_selected_ids"] == [96, 102, 104, 106, 108, 109, 122, 123, 124, 125]
    assert not {101, 103, 111} & set(config["additional_selected_ids"])
    assert max(config["new_identity_ids"]) == 129
    assert 35 not in config["additional_selected_ids"]
    assert len(config["new_identity_ids"]) >= 20 and min(config["new_identity_ids"]) > 100
    assert config["target_month"] == "2026-09"
    assert not config["operational_activation_authorized"] and not config["publication_authorized"]


@pytest.mark.parametrize("existing_year", [2019, 2020, 2021])
def test_same_fipe_different_year_cannot_count_as_new_admission(composition, existing_year):
    inventory, archive, baseline, record, config = composition
    candidate = next(v for v in inventory if v.id in config["baseline_ready_ids"])
    data = candidate.model_dump()
    data["fields"]["fipe_code"] = observed("fipe_code", record["fipe_identity"]["CodigoFipe"], candidate.fields["fipe_code"].sources).model_dump()
    data["fields"]["year_code"] = observed("year_code", f"{existing_year}-5", candidate.fields["year_code"].sources).model_dump()
    replacement = v6.ProfileVehicle.model_validate(data)
    inventory[inventory.index(candidate)] = replacement
    config["baseline_vehicle_fingerprints"][str(candidate.id)] = v6.fingerprint(replacement)
    with pytest.raises(ValueError, match="Blocked candidate"):
        v6.build_cohort(inventory, archive, baseline_report=baseline)
    config["additional_selected_ids"] = []
    report = v6.build_cohort(inventory, archive, baseline_report=baseline)
    rejected = next(r for r in report["states"] if r["id"] == record["id"])
    assert rejected["profile_evidence_ready"]
    assert not rejected["academic_test_ready"] and not rejected["academic_cohort_selected"]
    assert rejected["duplicate_of_frozen_id"] == candidate.id
    assert rejected["rejection_reasons"] == ["DUPLICATE_FROZEN_FIPE_CODE_DIFFERENT_YEAR_NOT_NEW_ADMISSION"]
    assert report["cohort_size"] == report["academic_test_ready_count"] == 50
    assert not rejected["operationally_active"] and not rejected["recommended"]


@pytest.mark.parametrize("month", ["2026-09", "2026-10"])
def test_temporal_window_labels_actual_month(month):
    assert v6.price_reference_month(month) == month


@pytest.mark.parametrize("month", [None, "", "2026-08", "2026-11", "2027-01", "2026-13"])
def test_temporal_window_rejects_missing_or_outside(month):
    with pytest.raises(ValueError):
        v6.price_reference_month(month)


def test_september_preferred_and_october_fallback(source_fixture):
    record, _, values, _ = source_fixture()
    october = values["fipe"]
    september = {**october, "MesReferencia": "setembro de 2026"}
    assert v6.select_price_snapshot([october, september], record["fipe_identity"]) == september
    assert v6.select_price_snapshot([september, october], record["fipe_identity"]) == september
    assert v6.select_price_snapshot([october], record["fipe_identity"]) == october
    with pytest.raises(ValueError, match="identity"):
        v6.select_price_snapshot([{**october, "CodigoFipe": "000000-0"}], record["fipe_identity"])
    with pytest.raises(ValueError):
        v6.select_price_snapshot([{k: v for k, v in october.items() if k != "MesReferencia"}], record["fipe_identity"])


def test_v6_identifier_extension_does_not_relax_v3(source_fixture):
    record, archive, _, _ = source_fixture()
    vehicle, _ = v6.review_record(record, archive)
    data = vehicle.model_dump()
    data["id"] = 101
    assert v6.V6ProfileVehicle.model_validate(data).id == 101
    with pytest.raises(ValueError):
        v6.ProfileVehicle.model_validate(data)
    invalid = deepcopy(data)
    invalid["fields"]["width_mm"]["unit"] = "cm"
    with pytest.raises(ValueError):
        v6.V6ProfileVehicle.model_validate(invalid)
    row = v6.evaluate_vehicle(v6.V6ProfileVehicle.model_validate(data), "app", "base")
    assert row["id"] == row["baseline_v3_academic_v1"]["id"] == 101
    assert row["academic_test_ready"]
    assert not row["methodology_ready"] and not row["observed_tco_complete"]
    assert not row["operationally_active"] and not row["recommended"]


def test_extended_evaluator_formula_ast_identical():
    """Only the ID validator and explicit names differ, not weights or formulas."""
    import ast
    import inspect
    from data_platform.catalog import profile_pilot_v4 as old
    original = inspect.getsource(old.evaluate_vehicle)
    actual = inspect.getsource(v6._evaluate_extended_v4)
    expected = original.replace("def evaluate_vehicle(", "def _evaluate_extended_v4(")
    expected = expected.replace("ProfileVehicle.model_validate", "V6ProfileVehicle.model_validate")
    expected = expected.replace("config = configuration()", "config = v4_configuration()")
    expected = expected.replace('"version": VERSION', '"version": v4.VERSION')
    assert ast.dump(ast.parse(actual), include_attributes=False) == ast.dump(ast.parse(expected), include_attributes=False)


def test_selected_candidate_with_explicit_blocker_rejected(composition, monkeypatch):
    inventory, archive, baseline, record, _ = composition
    vehicle, _ = v6.review_record(record, archive)
    monkeypatch.setattr(v6, "review_record", lambda *_: (vehicle, ("FIPE_REFERENCE_MONTH_MISMATCH",)))
    with pytest.raises(ValueError, match="Blocked candidate"):
        v6.build_cohort(inventory, archive, baseline_report=baseline)


@pytest.mark.parametrize("field,value", [("target_size", 61), ("maximum_additional", 11),
    ("target_month", "2026-10"), ("operational_activation_authorized", True), ("publication_authorized", True),
    ("additional_selected_ids", [61]), ("reviewed_candidate_ids", [35, 35, 96]), ("holdout_ids", [])])
def test_scope_cannot_relax_gates(tmp_path, field, value):
    config = deepcopy(v6.configuration())
    config[field] = value
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="scope"):
        v6.configuration(path)


@pytest.mark.parametrize("identifier", [122, 123, 124, 125])
def test_final_four_exact_identity_proxy_and_three_scenarios(source_fixture, identifier):
    """Synthetic bytes exercise the same pinned four dossiers, not productive fixtures."""
    from decimal import Decimal
    record, archive, _, _ = source_fixture(identifier)
    vehicle, blockers = v6.review_record(record, archive)
    assert not blockers and vehicle.id == identifier
    frozen_codes = {r["fipe_identity"]["CodigoFipe"] for r in v6.load_evidence()["records"] if r["id"] in {96, 102, 104, 106, 108, 109}}
    assert vehicle.fields["fipe_code"].value not in frozen_codes
    for scenario in v6.SCENARIOS:
        result = v6.evaluate_vehicle(vehicle, "app", scenario)
        assert result["academic_test_ready"] and result["scenario_tco_complete"]
        proxy = result["criteria"]["passenger_space"]
        expected = (Decimal(vehicle.fields["wheelbase_mm"].value) * Decimal(vehicle.fields["width_mm"].value)
                    / Decimal(vehicle.fields["seats"].value) / Decimal(1_000_000))
        assert proxy["value"] == expected and proxy["nature"] == "derived_academic"
        assert result["price_reference_month"] == result["scenario_costs"]["price_reference_month"] == "2026-10"
        assert not result["observed_tco_complete"] and not result["operationally_active"] and not result["recommended"]
        assert result["operational_ranking"] == []


@pytest.mark.parametrize("identifier", [122, 123, 124, 125])
@pytest.mark.parametrize("change", ["unit", "cache", "year"])
def test_final_four_evidence_fail_closed(source_fixture, identifier, change):
    record, archive, values, persist = source_fixture(identifier)
    if change == "unit":
        next(f for f in record["fields"] if f["name"] == "width_mm")["unit"] = "cm"
    elif change == "cache":
        (archive.directories[0] / record["sources"]["carpedia"]["cache_file"]).write_bytes(b"altered")
    else:
        values["carpedia"]["ano"] = "2021"
        persist()
    with pytest.raises(ValueError):
        v6.review_record(record, archive)
