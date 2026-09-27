"""Synthetic parser-boundary fixtures; live source bytes replayed externally."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pytest

from data_platform.catalog import batch4_academic_v4 as b
from data_platform.catalog.adapter import SourceArchive
from data_platform.catalog.crosswalk import review_batch
from data_platform.catalog.profile_contracts_v3 import Citation, ProfileVehicle, blank_fields, observed
from data_platform.catalog.profile_pilot_v4 import evaluate_vehicle


@pytest.fixture
def factory(tmp_path, monkeypatch):
    monkeypatch.setattr(b, "prepare_batch", lambda *args: [])
    def create(identifier=45):
        row = deepcopy(next(r for r in b.load_manifest()["records"] if r["id"] == identifier))
        rv = next(d for d in review_batch()["decisions"] if d["id"] == identifier)
        fields = blank_fields()
        for name, value in row["identity"].items():
            provider = "pbev" if name in ("fuel", "transmission") else "fipe"
            citation = Citation(provider=provider, url="https://example.org/fixture", sha256="a"*64,
                document="synthetic", locator=name, collected_at="2026-09-01T00:00:00+00:00")
            fields[name] = observed(name, value, (citation,))
        for name, key in (("price_brl", "price_brl"), ("consumption_city", "city_km_l"), ("consumption_highway", "highway_km_l")):
            citation = Citation(provider="fipe" if name == "price_brl" else "pbev", url="https://example.org/fixture",
                sha256="a"*64, document="synthetic", locator=name, collected_at="2026-09-01T00:00:00+00:00")
            fields[name] = observed(name, Decimal(str(rv["observed"][key])), (citation,))
        vehicle = ProfileVehicle(id=identifier, label=row["identity"]["commercial_identity"],
            identity_status="identity_approved", fields=fields,
            human_approval_required=rv["human_approval_required"], human_approval_status=rv["human_approval_status"])
        # Preserve the recorded locators by constructing the exact section/item slots.
        import re
        sections = []
        for fact in row["fields"]:
            indexes = [int(n) for n in re.findall(r"\[(\d+)\]", fact["locator"])]
            si, ii = indexes[:2]
            while len(sections) <= si: sections.append({"titulo": "Unused", "itens": []})
            sections[si]["titulo"] = fact["source_section"]
            items = sections[si]["itens"]
            while len(items) <= ii: items.append({"label": "unused"+str(len(items)), "valor": "fixture"})
            items[ii] = {"label": fact["source_label"], "valor": fact["source_value"]}
        for fact in row["mechanical_evidence"]:
            section = next((s for s in sections if s["titulo"] == fact["section"]), None)
            if section is None:
                section = {"titulo": fact["section"], "itens": []}; sections.append(section)
            section["itens"].append({"label": fact["label"], "valor": fact["value"]})
        payload = {"ref": "09-2026", "versao": row["source_identity"], "ano": row["identity"]["year_code"][:4],
                   "fonte": row["upstream_source"], "secoes": sections}
        def store():
            raw = json.dumps(payload, ensure_ascii=False).encode()
            (tmp_path/row["source"]["cache_file"]).write_bytes(raw)
            row["source"]["sha256"] = hashlib.sha256(raw).hexdigest()
        store()
        return vehicle, row, SourceArchive((tmp_path,)), payload, store
    return create


@pytest.mark.parametrize("identifier", b.IDS)
@pytest.mark.parametrize("scenario", ("low", "base", "high"))
def test_each_vehicle_ready_without_operational_activation(factory, identifier, scenario):
    vehicle, row, archive, _, _ = factory(identifier)
    result = b.admit_vehicle(vehicle, row, archive)
    evaluation = evaluate_vehicle(result, "app", scenario, "2026-09")
    assert evaluation["academic_test_ready"] and evaluation["scenario_tco_complete"]
    assert not evaluation["observed_tco_complete"]
    assert not evaluation["operationally_active"] and not evaluation["recommended"]
    assert not evaluation["operational_ranking"]
    assert b.admit_vehicle(result, row, archive) == result
    assert result.fields["width_with_mirrors_mm"].value is None
    assert all(result.fields[k].value is None for k in ("airbags", "abs", "esc"))


@pytest.mark.parametrize("case", ("year", "version", "external_id", "month", "fuel", "gear", "generic_transmission", "cvt_generic", "unit", "missing_seats", "zero_width", "duplicate_label", "source"))
def test_rejects_incompatible_raw_evidence(factory, case):
    vehicle, row, archive, payload, store = factory(52 if case == "cvt_generic" else 45)
    if case == "year": payload["ano"] = "2020"
    elif case == "version": payload["versao"]["nome"] = "Other version"
    elif case == "external_id": payload["versao"]["id"] = 999
    elif case == "month": payload["ref"] = "08-2026"
    elif case == "source": payload["fonte"] = {"fonte": "other", "em": "2026-01-01"}
    else:
        labels = {"fuel": "Combustível", "gear": "Número de marchas", "generic_transmission": "Câmbio (tipo)",
                  "cvt_generic": "Câmbio (tipo)", "unit": "Largura (mm)", "missing_seats": "Número de lugares",
                  "zero_width": "Largura (mm)", "duplicate_label": "Número de lugares"}
        section = next(s for s in payload["secoes"] if any(i["label"] == labels[case] for i in s["itens"]))
        item = next(i for i in section["itens"] if i["label"] == labels[case])
        if case == "unit": item["label"] = "Largura (cm)"
        elif case == "missing_seats": section["itens"].remove(item)
        elif case == "duplicate_label": section["itens"].append(deepcopy(item))
        else: item["valor"] = {"fuel": "Gasolina", "gear": "4", "generic_transmission": "Aut.", "cvt_generic": "Automático", "zero_width": "0"}[case]
    store()
    with pytest.raises((ValueError, KeyError)): b.admit_vehicle(vehicle, row, archive)


@pytest.mark.parametrize("case", ("pending", "conflict", "price", "identity", "hash", "official_field", "negative", "manifest_unit"))
def test_fail_closed_admission(factory, case):
    vehicle, row, archive, _, _ = factory()
    if case == "pending": vehicle = vehicle.model_copy(update={"human_approval_required": True, "human_approval_status": "pending"})
    elif case == "conflict": vehicle = vehicle.model_copy(update={"source_conflicts": ("unresolved",)})
    elif case == "price": vehicle.fields["price_brl"] = vehicle.fields["price_brl"].model_copy(update={"value": Decimal(1)})
    elif case == "identity": row["identity"]["year_code"] = "2020-5"
    elif case == "hash": row["source"]["sha256"] = "0"*64
    elif case == "official_field": row["fields"][0]["attribute_code"] = "price_brl"
    elif case == "negative": row["fields"][0]["normalized_value"] = "-5"
    elif case == "manifest_unit": row["fields"][0]["normalized_unit"] = "mm"
    with pytest.raises(ValueError): b.admit_vehicle(vehicle, row, archive)


@pytest.mark.parametrize("case", ("duplicate", "missing", "outside_scope", "activation", "budget_scope"))
def test_manifest_scope_rejects_mutations(tmp_path, case):
    manifest = b.load_manifest(); plan = json.loads((b.ROOT/'batch4_collection_v1.json').read_text())
    if case == "duplicate": manifest["records"].append(deepcopy(manifest["records"][0]))
    elif case == "missing": manifest["records"][0]["fields"] = []
    elif case == "outside_scope": manifest["records"][0]["id"] = 40
    elif case == "activation": plan["publication_authorized"] = True
    else: plan["maximum_total_identities"] = 61
    m=tmp_path/'m.json';p=tmp_path/'p.json';m.write_text(json.dumps(manifest));p.write_text(json.dumps(plan))
    with pytest.raises(ValueError): b.load_manifest(m,p)


def test_duplicate_inputs_and_canonical_identity(factory, monkeypatch):
    vehicle, row, archive, _, _ = factory()
    with pytest.raises(ValueError, match="Duplicate input"): b.batch4_matrix((vehicle,vehicle),archive)
    monkeypatch.setattr(b,"load_manifest",lambda *args: {"records":[row]})
    other=vehicle.model_copy(update={"id":1})
    with pytest.raises(ValueError, match="Duplicate canonical"): b.batch4_matrix((vehicle,other),archive)
    with pytest.raises(ValueError, match="Missing candidate"): b.batch4_matrix((),archive)


def test_exact_sixty_scope_and_backlog_preservation():
    plan=json.loads((b.ROOT/'batch4_collection_v1.json').read_text())
    ids=plan['legacy_ids']+plan['existing_new_ids']+plan['admitted_ids']
    assert len(ids)==len(set(ids))==60
    assert {35,40,41}.isdisjoint(plan['admitted_ids'])
