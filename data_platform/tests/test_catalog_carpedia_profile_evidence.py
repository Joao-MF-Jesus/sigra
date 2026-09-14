"""Synthetic offline checks for the hash-bound CarPedia profile evidence bridge."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

import pytest

from data_platform.catalog.carpedia_profile_evidence import (
    MANIFEST_PATH,
    augment_carpedia_profile_evidence,
    carpedia_body_types,
    reprocess_carpedia_caches,
)
from data_platform.catalog.experimental_cohort import assess_cohort
from data_platform.catalog.profile_contracts_v3 import Citation, ProfileVehicle, blank_fields, observed
from data_platform.catalog.profile_scoring_v3 import configuration, score_cohort


def _citation(provider: str) -> Citation:
    return Citation(
        provider=provider,
        url="https://example.org/synthetic-source",
        sha256="d" * 64,
        document="SYNTHETIC UNIT TEST ONLY",
        locator="row=1",
        collected_at="2026-09-11T00:00:00Z",
    )


def _vehicle(record: dict[str, object]) -> ProfileVehicle:
    fields = blank_fields()
    identity = record["catalog_identity"]
    for name, value in {
        "fipe_code": identity["fipe_code"],
        "year_code": identity["year_code"],
        "commercial_identity": identity["commercial_identity"],
        "reference_month": "2026-09",
        "price_brl": "80000",
    }.items():
        fields[name] = observed(name, value, (_citation("fipe"),))
    for name, value in {
        "consumption_city": "10",
        "consumption_highway": "14",
        "fuel": "flex",
        "transmission": "cvt" if record["candidate_id"] == 47 else "automatic",
    }.items():
        fields[name] = observed(name, value, (_citation("pbev"),), "shared_powertrain")
    return ProfileVehicle(
        id=record["candidate_id"],
        label=identity["commercial_identity"],
        identity_status="identity_approved",
        fields=fields,
    )


def _fixture_payload(record: dict[str, object]) -> dict[str, object]:
    indexed = []
    for field in record["fields"]:
        match = re.fullmatch(r"secoes\[(\d+)]\.itens\[(\d+)]", field["locator"])
        assert match is not None
        indexed.append((int(match.group(1)), int(match.group(2)), field))
    section_count = max(section for section, _, _ in indexed) + 1
    sections = []
    for section_index in range(section_count):
        in_section = [row for row in indexed if row[0] == section_index]
        item_count = max((item for _, item, _ in in_section), default=0) + 1
        title = in_section[0][2]["source_section"] if in_section else f"Synthetic section {section_index}"
        sections.append({
            "titulo": title,
            "itens": [
                {"label": f"Unmapped synthetic field {section_index}-{item_index}", "valor": "unavailable"}
                for item_index in range(item_count)
            ],
        })
    for section_index, item_index, field in indexed:
        sections[section_index]["itens"][item_index] = {
            "label": field["source_label"],
            "valor": field["source_value"],
        }
    source_identity = record["source_identity"]
    return {
        "ref": record["source_reference"],
        "ano": record["model_year"],
        "manual": False,
        "versao": {
            "id": record["external_vehicle_id"],
            "marca": source_identity["brand"],
            "modelo": source_identity["model"],
            "nome": source_identity["version"],
        },
        "secoes": sections,
        "fonte": {"fonte": record["source_name"], "em": record["source_at"]},
    }


def _offline_fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    cache = tmp_path / "cache"
    cache.mkdir(parents=True)
    for record in manifest["records"]:
        payload = json.dumps(_fixture_payload(record), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        (cache / record["cache_file"]).write_bytes(payload)
        record["response_sha256"] = hashlib.sha256(payload).hexdigest()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return cache, manifest_path, manifest


def test_offline_cache_reprocessing_is_exact_idempotent_and_preserves_official_precedence(tmp_path):
    cache, manifest_path, manifest = _offline_fixture(tmp_path)
    vehicles = tuple(_vehicle(record) for record in manifest["records"])

    processed = reprocess_carpedia_caches(cache, manifest_path=manifest_path)
    once = augment_carpedia_profile_evidence(vehicles, cache, manifest_path=manifest_path)
    twice = augment_carpedia_profile_evidence(once, cache, manifest_path=manifest_path)

    assert once == twice
    assert set(processed) == {46, 47}
    by_id = {vehicle.id: vehicle for vehicle in once}
    assert by_id[46].fields["seats"].value == Decimal("5")
    assert by_id[46].fields["cargo_l"].value == Decimal("440.000000")
    assert by_id[46].fields["payload_kg"].kind == "unavailable"
    assert by_id[47].fields["payload_kg"].value == Decimal("413.000000")
    assert by_id[47].fields["cargo_l"].value == Decimal("530.000000")
    assert by_id[46].fields["fuel"].sources[0].provider == "pbev"
    assert by_id[46].fields["transmission"].sources[0].provider == "pbev"
    assert by_id[47].fields["transmission"].value == "cvt"
    assert by_id[46].fields["width_with_mirrors_mm"].kind == "unavailable"
    assert by_id[46].fields["power_gasoline_cv"].kind == "unavailable"
    assert set(carpedia_body_types(once)) == {46, 47}
    assert all(item.value == "Sedã" for item in carpedia_body_types(once).values())
    provenance = by_id[46].provenance["carpedia_profile_evidence"]
    assert provenance["official_precedence_preserved"] == {"fuel": "pbev", "transmission": "pbev"}
    assert provenance["response_sha256"] == manifest["records"][0]["response_sha256"]
    assert provenance["normalized_contract_fields"]["power"]["unit"] == "kW"
    power = provenance["normalized_contract_fields"]["power"]
    assert power["origin"] == "carpedia_api_v1"
    assert power["external_vehicle_id"] == 44709
    assert power["model_year"] == 2020
    assert power["response_sha256"] == manifest["records"][0]["response_sha256"]
    assert power["source_reference"] == "09-2026"
    assert power["collected_at"] == "2026-09-11T21:35:09.000294-03:00"
    assert power["locator"] == "secoes[4].itens[0]"
    assert "manual" not in provenance["normalized_contract_fields"]


def test_cache_tampering_identity_divergence_and_duplicates_fail_closed(tmp_path):
    cache, manifest_path, manifest = _offline_fixture(tmp_path)
    target = cache / manifest["records"][0]["cache_file"]
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="cache changed"):
        reprocess_carpedia_caches(cache, manifest_path=manifest_path)

    cache, manifest_path, manifest = _offline_fixture(tmp_path / "identity")
    vehicles = tuple(_vehicle(record) for record in manifest["records"])
    changed = vehicles[0].model_dump()
    changed["fields"]["commercial_identity"]["value"] = "Similar text is not an identity"
    with pytest.raises(ValueError, match="profile identity differs"):
        augment_carpedia_profile_evidence(
            (ProfileVehicle.model_validate(changed), vehicles[1]),
            cache,
            manifest_path=manifest_path,
        )

    duplicate = deepcopy(manifest)
    duplicate["records"][0]["fields"].append(deepcopy(duplicate["records"][0]["fields"][0]))
    duplicate_path = tmp_path / "duplicate-manifest.json"
    duplicate_path.write_text(json.dumps(duplicate), encoding="utf-8")
    with pytest.raises(ValueError, match="field admission scope differs|Duplicate Carpedia evidence field"):
        reprocess_carpedia_caches(cache, manifest_path=duplicate_path)


def test_dimensions_do_not_imply_methodology_readiness_or_complete_tco(tmp_path):
    cache, manifest_path, manifest = _offline_fixture(tmp_path)
    enriched = augment_carpedia_profile_evidence(
        tuple(_vehicle(record) for record in manifest["records"]),
        cache,
        manifest_path=manifest_path,
    )

    body_types = carpedia_body_types(enriched)
    core = assess_cohort(enriched, body_types=body_types, stability_verified=True)
    assert core["partial_coverage_candidate_ids"]["app"] == [46, 47]
    assert core["partial_coverage_candidate_ids"]["trabalho"] == [46, 47]
    assert core["partial_coverage_capacity_gate_passed"] is False
    assert all(core["partial_coverage_candidate_ids"][profile] == [] for profile in ("cidade", "familia", "estrada", "suv"))

    before = configuration()
    for profile in before["profiles"]:
        preview = score_cohort(enriched, profile, "2026-09")
        assert preview["methodology_ready_ids"] == []
        for row in preview["records"]:
            assert row["methodology_ready"] is False
            assert row["costs"]["is_complete_tco"] is False
            assert row["costs"]["monthly_tco"] is None
            assert "PROFILE_REQUIRED_EVIDENCE_MISSING" in row["gate_reasons"]
    assert configuration() == before
