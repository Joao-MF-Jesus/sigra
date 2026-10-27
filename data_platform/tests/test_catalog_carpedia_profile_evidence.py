"""Synthetic offline checks for the hash-bound CarPedia profile evidence bridge."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

import pytest

import data_platform.catalog.crosswalk as crosswalk_module
from data_platform.catalog.carpedia_profile_evidence import (
    BATCH2_MANIFEST_PATH,
    MANIFEST_PATH,
    augment_carpedia_profile_evidence,
    carpedia_body_types,
    reprocess_carpedia_caches,
)
from data_platform.catalog.crosswalk import BATCH2_REVIEW_PATH, batch2_collection, review_batch2
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
    transmission_evidence = next(
        field["source_value"]
        for field in record["fields"]
        if field["attribute_code"] == "transmission"
    ).casefold()
    transmission = (
        "cvt"
        if "cvt" in transmission_evidence
        else "automatic"
        if "autom" in transmission_evidence
        else "manual"
    )
    for name, value in {
        "consumption_city": "10",
        "consumption_highway": "14",
        "fuel": record["source_identity"]["fuel"],
        "transmission": transmission,
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


def _offline_fixture(
    tmp_path: Path,
    source_manifest: Path = MANIFEST_PATH,
) -> tuple[Path, Path, dict[str, object]]:
    manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    cache = tmp_path / "cache"
    cache.mkdir(parents=True)
    for record in manifest["records"]:
        payload = json.dumps(_fixture_payload(record), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        (cache / record["cache_file"]).write_bytes(payload)
        record["response_sha256"] = hashlib.sha256(payload).hexdigest()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return cache, manifest_path, manifest


def test_batch2_review_scope_is_exact_and_keeps_failed_identity_out():
    collection = batch2_collection()
    assert collection["pre_http_plan"]["priority_queue_ids"][:11] == [
        57, 58, 59, 68, 69, 70, 79, 80, 91, 92, 93,
    ]
    assert set(collection["pre_http_plan"]["priority_queue_ids"]) == set(range(57, 101))
    assert collection["http_accounting"]["fipe"]["current_executed"] == 11
    assert collection["http_accounting"]["carpedia"]["current_executed"] == 10
    assert collection["http_accounting"]["carpedia"]["current_remaining"] == 12
    result = review_batch2()
    assert result["counts"] == {
        "identity_approved": 10,
        "methodology_ready": 0,
        "source_chain_published": 0,
        "postgresql_validated": 0,
        "ui_ready": 0,
        "operationally_active": 0,
    }
    assert result["blocked"] == 1
    assert [row["id"] for row in result["decisions"]] == [
        57, 58, 59, 68, 69, 70, 79, 80, 91, 92, 93,
    ]
    blocked = next(row for row in result["decisions"] if row["id"] == 57)
    assert blocked["status"] == "blocked_with_evidence"
    assert blocked["blockers"] == ["FIPE_SEPTEMBER_2026_EXACT_TARGET_HTTP_404"]
    assert all(
        row["review"]["link_type"] in {"exact_trim_powertrain", "shared_powertrain_group"}
        for row in result["decisions"] if row["status"] == "identity_approved"
    )

    changed = json.loads(BATCH2_REVIEW_PATH.read_text(encoding="utf-8"))["reviews"]
    changed.reverse()
    with pytest.raises(ValueError, match="frozen priority queue"):
        review_batch2(changed)


def test_batch2_collection_rejects_duplicate_queue_and_incomplete_profile_balance(tmp_path, monkeypatch):
    original = batch2_collection()
    changed = deepcopy(original)
    changed["pre_http_plan"]["priority_queue_ids"][-1] = 57
    path = tmp_path / "duplicate-queue.json"
    path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(crosswalk_module, "BATCH2_COLLECTION_PATH", path)
    with pytest.raises(ValueError, match="priority queue"):
        batch2_collection()

    changed = deepcopy(original)
    changed["pre_http_plan"]["profile_target_counts"]["familia"] = 2
    path = tmp_path / "incomplete-balance.json"
    path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(crosswalk_module, "BATCH2_COLLECTION_PATH", path)
    with pytest.raises(ValueError, match="profile balance"):
        batch2_collection()


def test_batch2_cached_fichas_are_hash_bound_exact_and_preserve_source_precedence(tmp_path):
    cache, manifest_path, manifest = _offline_fixture(tmp_path, BATCH2_MANIFEST_PATH)
    vehicles = tuple(_vehicle(record) for record in manifest["records"])

    processed = reprocess_carpedia_caches(cache, manifest_path=manifest_path)
    once = augment_carpedia_profile_evidence(vehicles, cache, manifest_path=manifest_path)
    twice = augment_carpedia_profile_evidence(once, cache, manifest_path=manifest_path)

    expected_ids = {58, 59, 68, 69, 70, 79, 80, 91, 92, 93}
    assert set(processed) == expected_ids
    assert once == twice
    by_id = {vehicle.id: vehicle for vehicle in once}
    clearance = {59, 68, 70, 79, 91, 92, 93}
    assert all(by_id[identifier].fields["ground_clearance_mm"].kind == "observed" for identifier in clearance)
    assert all(by_id[identifier].fields["ground_clearance_mm"].unit == "mm" for identifier in clearance)
    assert all(by_id[identifier].fields["ground_clearance_mm"].kind == "unavailable" for identifier in expected_ids - clearance)
    assert all(by_id[identifier].fields["length_mm"].kind == "observed" for identifier in expected_ids)
    assert all(by_id[identifier].fields["width_mm"].kind == "observed" for identifier in expected_ids)
    assert all(by_id[identifier].fields["width_with_mirrors_mm"].kind == "unavailable" for identifier in expected_ids)
    assert all(by_id[identifier].fields["airbags"].kind == "unavailable" for identifier in expected_ids)
    assert all(by_id[identifier].fields["abs"].kind == "unavailable" for identifier in expected_ids)
    assert all(by_id[identifier].fields["esc"].kind == "unavailable" for identifier in expected_ids)
    assert by_id[70].fields["transmission"].value == "automatic"
    assert by_id[70].fields["transmission"].sources[0].provider == "pbev"
    assert by_id[70].fields["fuel"].sources[0].provider == "pbev"
    normalized = by_id[70].provenance["carpedia_profile_evidence"]["normalized_contract_fields"]
    assert normalized["transmission"]["value"] == "Automatizado"
    assert normalized["transmission"]["source_value"] == "Automatizado"
    assert "manual" not in normalized


def test_batch2_manifest_rejects_tampering_invalid_units_and_duplicate_fields(tmp_path):
    cache, manifest_path, manifest = _offline_fixture(tmp_path, BATCH2_MANIFEST_PATH)
    target = cache / manifest["records"][0]["cache_file"]
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="cache changed"):
        reprocess_carpedia_caches(cache, manifest_path=manifest_path)

    cache, manifest_path, manifest = _offline_fixture(tmp_path / "invalid-unit", BATCH2_MANIFEST_PATH)
    record = next(row for row in manifest["records"] if row["candidate_id"] == 59)
    field = next(row for row in record["fields"] if row["attribute_code"] == "ground_clearance")
    field["source_unit"] = "cm"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="field differs"):
        reprocess_carpedia_caches(cache, manifest_path=manifest_path)

    cache, manifest_path, manifest = _offline_fixture(tmp_path / "duplicate", BATCH2_MANIFEST_PATH)
    manifest["records"][0]["fields"].append(deepcopy(manifest["records"][0]["fields"][0]))
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="field admission scope differs|Duplicate Carpedia evidence field"):
        reprocess_carpedia_caches(cache, manifest_path=manifest_path)


def test_offline_cache_reprocessing_is_exact_idempotent_and_preserves_official_precedence(tmp_path):
    cache, manifest_path, manifest = _offline_fixture(tmp_path)
    vehicles = tuple(_vehicle(record) for record in manifest["records"])

    processed = reprocess_carpedia_caches(cache, manifest_path=manifest_path)
    once = augment_carpedia_profile_evidence(vehicles, cache, manifest_path=manifest_path)
    twice = augment_carpedia_profile_evidence(once, cache, manifest_path=manifest_path)

    assert once == twice
    expected_ids = {36, 37, 38, 39, 42, 43, 46, 47, 49}
    assert set(processed) == expected_ids
    by_id = {vehicle.id: vehicle for vehicle in once}
    assert by_id[36].fields["payload_kg"].value == Decimal("430.000000")
    assert by_id[36].fields["cargo_l"].value == Decimal("285.000000")
    assert by_id[38].fields["payload_kg"].kind == "unavailable"
    assert by_id[49].fields["cargo_l"].value == Decimal("526.000000")
    assert by_id[46].fields["seats"].value == Decimal("5")
    assert by_id[46].fields["cargo_l"].value == Decimal("440.000000")
    assert by_id[46].fields["payload_kg"].kind == "unavailable"
    assert by_id[47].fields["payload_kg"].value == Decimal("413.000000")
    assert by_id[47].fields["cargo_l"].value == Decimal("530.000000")
    assert by_id[42].fields["ground_clearance_mm"].value == Decimal("147.000000")
    assert by_id[43].fields["ground_clearance_mm"].value == Decimal("125.000000")
    assert by_id[42].fields["ground_clearance_mm"].sources[0].provider == "carpedia"
    assert by_id[46].fields["fuel"].sources[0].provider == "pbev"
    assert by_id[46].fields["transmission"].sources[0].provider == "pbev"
    assert by_id[47].fields["transmission"].value == "cvt"
    assert by_id[46].fields["width_with_mirrors_mm"].kind == "unavailable"
    assert by_id[42].fields["width_with_mirrors_mm"].kind == "unavailable"
    assert all(by_id[identifier].fields["airbags"].kind == "unavailable" for identifier in expected_ids)
    assert all(by_id[identifier].fields["abs"].kind == "unavailable" for identifier in expected_ids)
    assert all(by_id[identifier].fields["esc"].kind == "unavailable" for identifier in expected_ids)
    assert by_id[46].fields["power_gasoline_cv"].kind == "unavailable"
    assert set(carpedia_body_types(once)) == expected_ids
    assert carpedia_body_types(once)[36].value == "Hatch"
    assert carpedia_body_types(once)[49].value == "Sedã"
    provenance = by_id[46].provenance["carpedia_profile_evidence"]
    assert provenance["official_precedence_preserved"] == {"fuel": "pbev", "transmission": "pbev"}
    manifest_by_id = {record["candidate_id"]: record for record in manifest["records"]}
    assert provenance["response_sha256"] == manifest_by_id[46]["response_sha256"]
    assert provenance["normalized_contract_fields"]["power"]["unit"] == "kW"
    power = provenance["normalized_contract_fields"]["power"]
    assert power["origin"] == "carpedia_api_v1"
    assert power["external_vehicle_id"] == 44709
    assert power["model_year"] == 2020
    assert power["response_sha256"] == manifest_by_id[46]["response_sha256"]
    assert power["source_reference"] == "09-2026"
    assert power["collected_at"] == "2026-09-11T21:35:09.000294-03:00"
    assert power["locator"] == "secoes[4].itens[0]"
    assert "manual" not in provenance["normalized_contract_fields"]
    clearance = by_id[42].provenance["carpedia_profile_evidence"]["normalized_contract_fields"]["ground_clearance"]
    assert clearance["unit"] == "mm"
    assert clearance["source_unit"] == "mm"
    assert clearance["response_sha256"] == manifest_by_id[42]["response_sha256"]
    assert clearance["locator"] == "secoes[2].itens[4]"


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

    cache, manifest_path, manifest = _offline_fixture(tmp_path / "invalid-unit")
    ground = next(
        field
        for record in manifest["records"] if record["candidate_id"] == 42
        for field in record["fields"] if field["attribute_code"] == "ground_clearance"
    )
    ground["source_label"] = "Vão livre do solo (cm)"
    changed_payload = _fixture_payload(next(record for record in manifest["records"] if record["candidate_id"] == 42))
    target = cache / next(record["cache_file"] for record in manifest["records"] if record["candidate_id"] == 42)
    payload = json.dumps(changed_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    target.write_bytes(payload)
    next(record for record in manifest["records"] if record["candidate_id"] == 42)["response_sha256"] = hashlib.sha256(payload).hexdigest()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="label or unit is not exact"):
        reprocess_carpedia_caches(cache, manifest_path=manifest_path)


def test_matching_manufacturer_values_are_preserved_and_conflicts_fail_closed(tmp_path):
    cache, manifest_path, manifest = _offline_fixture(tmp_path)
    record = next(item for item in manifest["records"] if item["candidate_id"] == 36)
    vehicle = _vehicle(record)
    source_by_profile = {
        field["profile_field"]: field
        for field in record["fields"]
        if field["profile_field"] not in {None, "body_type"}
    }
    preserved = vehicle.model_dump()
    for profile_field in ("seats", "length_mm", "width_mm", "wheelbase_mm"):
        preserved["fields"][profile_field] = observed(
            profile_field,
            source_by_profile[profile_field]["normalized_value"],
            (_citation("manufacturer"),),
        ).model_dump()
    enriched = augment_carpedia_profile_evidence(
        (ProfileVehicle.model_validate(preserved),), cache, manifest_path=manifest_path
    )[0]
    assert all(
        enriched.fields[name].sources[0].provider == "manufacturer"
        for name in ("seats", "length_mm", "width_mm", "wheelbase_mm")
    )
    assert enriched.provenance["carpedia_profile_evidence"]["preserved_existing_profile_fields"] == [
        "seats",
        "length_mm",
        "width_mm",
        "wheelbase_mm",
    ]

    conflicting = deepcopy(preserved)
    conflicting["fields"]["length_mm"]["value"] = "9999"
    with pytest.raises(ValueError, match="cannot overwrite existing profile evidence"):
        augment_carpedia_profile_evidence(
            (ProfileVehicle.model_validate(conflicting),), cache, manifest_path=manifest_path
        )


def test_dimensions_do_not_imply_methodology_readiness_or_complete_tco(tmp_path):
    cache, manifest_path, manifest = _offline_fixture(tmp_path)
    enriched = augment_carpedia_profile_evidence(
        tuple(_vehicle(record) for record in manifest["records"]),
        cache,
        manifest_path=manifest_path,
    )

    body_types = carpedia_body_types(enriched)
    core = assess_cohort(enriched, body_types=body_types, stability_verified=True)
    expected_ids = [36, 37, 38, 39, 42, 43, 46, 47, 49]
    assert all(core["partial_coverage_candidate_ids"][profile] == expected_ids for profile in core["partial_coverage_candidate_ids"])
    assert core["core_coverage_complete_ids"]["app"] == expected_ids
    assert core["core_coverage_complete_ids"]["trabalho"] == expected_ids
    assert core["partial_coverage_capacity_gate_passed"] is False
    assert all(core["core_coverage_complete_ids"][profile] == [] for profile in ("cidade", "familia", "estrada"))
    assert core["core_coverage_complete_ids"]["suv"] == [42, 43]

    before = configuration()
    for profile in before["profiles"]:
        preview = score_cohort(enriched, profile, "2026-09")
        assert preview["methodology_ready_ids"] == ([42, 43] if profile == "suv" else [])
        for row in preview["records"]:
            assert row["methodology_ready"] is (profile == "suv" and row["id"] in {42, 43})
            assert row["recommended"] is False
            assert row["costs"]["is_complete_tco"] is False
            assert row["costs"]["monthly_tco"] is None
            if row["id"] not in {42, 43} or profile != "suv":
                assert "PROFILE_REQUIRED_EVIDENCE_MISSING" in row["gate_reasons"]
    assert configuration() == before
