"""Synthetic payload tests; actual source bytes are replayed outside Git."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import hashlib
import json

import pytest

from data_platform.catalog import legacy_technical_v4 as adapter
from data_platform.catalog.adapter import SourceArchive
from data_platform.catalog.legacy_academic_v4 import load_manifest as legacy_manifest
from data_platform.catalog.profile_contracts_v3 import ProfileVehicle, blank_fields, observed
from data_platform.contracts.carpedia_vehicle_specs import CarpediaAttribute


def attr(code, value, unit, **kwargs):
    return CarpediaAttribute(code, "Synthetic unit test", code, str(value), unit,
                            value, unit, 0, "recognized" if unit else "not_applicable",
                            {"field_locator": code, "origin": "synthetic unit test"}, **kwargs)


def vehicle(identifier=2):
    row = next(r for r in adapter.load_manifest()["records"] if r["id"] == identifier)
    review = next(r for r in legacy_manifest()["reviews"] if r["id"] == identifier)
    fields = blank_fields()
    fipe_ref = adapter.source_citation(adapter.load_manifest()["fipe_33"], "unit-test fixture")
    pbev_source = deepcopy(legacy_manifest()["sources"][review["pbev"]["source"]])
    pbev_ref = adapter.source_citation(pbev_source, "unit-test fixture")
    for key in ("fipe_code", "year_code", "commercial_identity"):
        fields[key] = observed(key, row[key], (fipe_ref,))
    fields["fuel"] = observed("fuel", "flex", (pbev_ref,))
    fields["transmission"] = observed("transmission", review["pbev"]["powertrain"][3], (pbev_ref,))
    return ProfileVehicle(id=identifier, label="Synthetic", identity_status="identity_approved", fields=fields,
                          provenance={"legacy_v4_review": review}), row


def source_fields(transmission="Automático", fuel="Flex"):
    return {"fuel_type": attr("fuel_type", fuel, None),
            "transmission": attr("transmission", transmission, None),
            "width": attr("width", Decimal("1700"), "mm"),
            "seats": attr("seats", Decimal("5"), "count")}


@pytest.fixture
def source_case(tmp_path):
    row = deepcopy(adapter.load_manifest()["records"][0])
    identity = row["source_identity"]
    discovery = {"versoes": [row["discovery_identity"]]}
    fiche = {"ref": "09-2026", "versao": {"id": identity["external_id"], "nome": identity["version"],
                        "marca": identity["brand"], "modelo": identity["model"]},
             "ano": str(identity["year"]),
             "fonte": {"fonte": identity["source_name"], "em": identity["source_at"]},
             "manual": True,
             "secoes": [{"titulo": "Dimensões", "itens": [
                 {"label": "Largura (mm)", "valor": "1700"},
                 {"label": "Número de lugares", "valor": "5"},
                 {"label": "Câmbio (tipo)", "valor": "Automático"},
                 {"label": "Combustível", "valor": "Flex"}]}]}
    def write():
        for key, data in (("discovery", discovery), ("fiche", fiche)):
            raw = json.dumps(data).encode()
            (tmp_path / row[key]["cache_file"]).write_bytes(raw)
            row[key]["sha256"] = hashlib.sha256(raw).hexdigest()
        return row, SourceArchive((tmp_path,))
    return row, discovery, fiche, write


def test_parser_ignores_boolean_manual_and_retains_units_and_provenance(source_case):
    row, _, _, write = source_case
    parsed, (fields, missing) = adapter.parse_record(*write())
    assert fields["transmission"].source_value == "Automático"
    assert fields["width"].normalized_value == Decimal("1700")
    assert fields["width"].provenance["response_sha256"] == row["fiche"]["sha256"]
    assert "ground_clearance" in missing
    assert "width_with_mirrors_mm" not in fields


@pytest.mark.parametrize("mutation", ["version", "year", "brand", "external_id", "source", "duplicate_discovery", "discovery_fuel"])
def test_exact_source_identity_rejects_divergences(source_case, mutation):
    row, discovery, fiche, write = source_case
    if mutation == "version": fiche["versao"]["nome"] += " another trim"
    elif mutation == "year": fiche["ano"] = "2017"
    elif mutation == "brand": fiche["versao"]["marca"] = "Other"
    elif mutation == "external_id": fiche["versao"]["id"] += 1
    elif mutation == "source": fiche["fonte"]["fonte"] = "Other"
    elif mutation == "duplicate_discovery": discovery["versoes"] *= 2
    elif mutation == "discovery_fuel": discovery["versoes"][0]["combustiveis"] = ["Diesel"]
    with pytest.raises(ValueError):
        adapter.parse_record(*write())


def test_tampered_cache_rejected(source_case, tmp_path):
    row, archive = source_case[-1]()
    (tmp_path / row["fiche"]["cache_file"]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        adapter.parse_record(row, archive)


@pytest.mark.parametrize("unit,value,status", [("cm", "170", "recognized"), (None, "1700", "unrecognized"),
    ("kg", "1700", "recognized"), ("mm", "0", "recognized"), ("mm", "-1", "recognized"),
    ("mm", "NaN", "recognized"), ("mm", "1700", "unrecognized")])
def test_invalid_units_or_values_remain_unavailable(unit, value, status):
    fields, missing = adapter.admit_fields([replace(attr("width", Decimal(value), unit), unit_status=status)])
    assert "width" not in fields and "width" in missing


def test_missing_count_fraction_and_duplicate_conflict_fail_closed():
    assert len(adapter.admit_fields([])[1]) == len(adapter.UNITS)
    assert "seats" not in adapter.admit_fields([attr("seats", Decimal("4.5"), "count")])[0]
    item = attr("width", Decimal("1700"), "mm")
    assert adapter.admit_fields([item, item])[0]["width"] == item
    assert "width" not in adapter.admit_fields([item, replace(item, normalized_value=Decimal("1800"))])[0]


@pytest.mark.parametrize("fuel,transmission,expected", [("Flex", "Automático", []),
    ("Diesel", "Automático", ["CARPEDIA_FUEL_NOT_EXACT"]),
    ("Flex", "Manual", ["CARPEDIA_TRANSMISSION_NOT_EXACT"])])
def test_official_fuel_transmission_precedence(fuel, transmission, expected):
    v, row = vehicle()
    assert adapter.identity_blockers(v, row, source_fields(transmission, fuel)) == expected


def test_corolla_automatic_is_not_silently_relabelled_cvt():
    v, row = vehicle(9)
    assert v.fields["transmission"].value == "cvt"
    assert adapter.identity_blockers(v, row, source_fields()) == ["CARPEDIA_TRANSMISSION_NOT_EXACT"]


def test_ka_grouped_trim_cannot_promote_individual_se():
    v, row = vehicle(33)
    assert adapter.identity_blockers(v, row, source_fields("Manual")) == ["CARPEDIA_SE_SE_PLUS_SCOPE_NOT_INDIVIDUALIZED"]


def test_engine_and_approved_catalog_id_cannot_change():
    v, row = vehicle()
    row["source_identity"]["version"] = "Prisma 2.0"
    assert "CARPEDIA_ENGINE_NOT_EXACT" in adapter.identity_blockers(v, row, source_fields())
    row["fipe_code"] = "000000-0"
    with pytest.raises(ValueError, match="approved legacy"):
        adapter.identity_blockers(v, row, source_fields())


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "version", "publication", "database", "catalog", "fipe"])
def test_manifest_scope_fail_closed(tmp_path, mutation):
    data = adapter.load_manifest()
    if mutation == "duplicate": data["records"][1] = data["records"][0]
    elif mutation == "missing": data["records"].pop()
    elif mutation == "version": data["normalizer_version"] = "unknown"
    elif mutation == "publication": data["publication_authorized"] = True
    elif mutation == "database": data["database_write_authorized"] = True
    elif mutation == "catalog": data["records"][0]["catalog"]["year"] -= 1
    elif mutation == "fipe": data["records"][0]["fipe_code"] = "000000-0"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError): adapter.load_manifest(path)


def test_augmentation_idempotent_and_does_not_overwrite_official_evidence(monkeypatch):
    spec = adapter.load_manifest()
    v, row = vehicle()
    original = [ProfileVehicle(id=i, label="Synthetic", identity_status="legacy_binding_not_reaudited",
                               fields=blank_fields()) for i in range(1, 35)]
    original[1] = v
    spec["records"] = [row]
    monkeypatch.setattr(adapter, "load_manifest", lambda path: spec)
    monkeypatch.setattr(adapter, "parse_record", lambda row, archive: (None, (source_fields(), {})))
    monkeypatch.setattr(adapter, "_price", lambda review, payload: (Decimal("44003"), "2026-09", {}))
    class Archive:
        def bytes(self, reference): return b"{}"
    result = adapter.augment_legacy_technical_v4(tuple(original), Archive())
    assert result == adapter.augment_legacy_technical_v4(result, Archive())
    assert result[1].fields["width_mm"].value == Decimal("1700")
    assert result[1].fields["width_with_mirrors_mm"].value is None
    for name in ("fuel", "transmission", "consumption_city", "consumption_highway", "price_brl", "maintenance_annual_brl"):
        assert result[1].fields[name] == v.fields[name]
    for name in ("airbags", "abs", "esc"):
        assert result[1].fields[name].value is None
    assert result[5] == original[5]
    with pytest.raises(ValueError, match="canonical 34"):
        adapter.augment_legacy_technical_v4(result[:-1], Archive())
