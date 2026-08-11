from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from data_platform.contracts.pbev import (
    AUDITED_ASSETS,
    PBEV_MATCHER_VERSION,
    ExternalVehicleIdentity,
    ExternalVehicleMapping,
    MappingStatus,
    MatchMethod,
    find_audited_assets,
)
from data_platform.ingestion.pbev.client import PbevAssetClient, PbevDownloadPolicy
from data_platform.ingestion.pbev.parser import (
    PbevPdfParser,
    PbevQuarantineError,
    PbevValidationError,
    decimal_from_cell,
    normalize_cell,
    sanitize_official_url,
    validate_synthetic_table,
)
from data_platform.orchestration.contracts import CancellationToken
from data_platform.pbev.pipeline import PbevExecutionOptions, run_pbev_pipeline
from data_platform.pbev.targets import (
    _body_style,
    _catalog_conflict,
    _catalog_version,
    _door_count,
    _engine_description,
    _fuel_identity_warning,
    _target_version,
    _transmission,
)
from data_platform.quality.pbev_checks import (
    AUDITED_PILOT_COUNTS,
    build_coverage_report,
    enforce_audited_pilot_baseline,
    validate_shadow_rows,
)
from data_platform.transformation.pbev import (
    ENGINE_DISPLACEMENT_TOLERANCE_CC,
    _brand,
    _model_compatible,
    _motor_compatible,
    _transmission_compatible,
    match_vehicle,
    score_candidate,
    supersede_mapping,
)


def _cells(year: int, *, energy: str = "1,50", version: str = "EX 1.0") -> list[str]:
    common = ["Hatch", "Marca", "Modelo", version, "1.0", "M-5"]
    emissions_legacy = ["0,010", "0,200", "0,020", "A", "100", "120"]
    consumption = ["8,0", "10,0", "12,0", "14,0"]
    if year <= 2019:
        return common + ["S", "E", "F"] + emissions_legacy + consumption + [energy, "A", "B", "Sim"]
    if year == 2020:
        return ["Hatch", "Marca", "Modelo", "1.0", version, "M-5", "S", "E", "F"] + emissions_legacy + consumption + [energy, "A", "B", "Sim"]
    if year == 2021:
        return common + ["S", "E", "Combustão", "F"] + emissions_legacy + consumption + [energy, "A", "B"]
    emissions_2022 = ["10", "200", "20", "A", "100", "120"]
    return ["Hatch", "Marca", "Modelo", version, "1.0", "Combustão", "M-5", "S", "E", "F"] + emissions_2022 + consumption + [energy, "A", "B", "Não"]


def _row(year: int = 2019, *, row_id: int = 10, energy: str = "1,50", version: str = "EX 1.0"):
    parsed = validate_synthetic_table(
        next(item for item in AUDITED_ASSETS if item.cycle_year == year),
        _cells(year, energy=energy, version=version),
    )
    return replace(parsed, raw=replace(parsed.raw, pbev_raw_row_id=row_id, asset_id=year))


def _candidate(
    *,
    year: int = 2019,
    row_id: int = 10,
    energy: str = "1,50",
    brand: str = "Marca",
    model: str = "Modelo",
    version: str | None = "EX 1.0",
    motor: str | None = "1.0",
    transmission: str | None = "M-5",
    category: str = "Hatch",
):
    parsed = _row(
        year,
        row_id=row_id,
        energy=energy,
        version=version or "missing",
    )
    return replace(
        parsed,
        brand_name=brand,
        model_name=model,
        version_name=version,
        motor_description=motor,
        transmission_code=transmission,
        category_name=category,
    )


def _target(**changes):
    values = {
        "vehicle_sk": 101,
        "brand_name": "Marca",
        "model_name": "Modelo",
        "model_year": 2019,
        "fuel_type": "flex",
        "version_name": "EX 1.0",
        "motor_description": "1.0",
        "transmission_type": "manual 5",
        "body_style": "hatch",
    }
    values.update(changes)
    return ExternalVehicleIdentity(**values)


def _decision(status: MappingStatus, index: int, *, reviewed: bool = False):
    matched = status == MappingStatus.MATCHED
    return ExternalVehicleMapping(
        target_identity_hash=f"{index:064x}",
        target_identity_evidence={"index": index},
        mapping_status=status,
        match_method=MatchMethod.MANUAL_REVIEW if reviewed else (MatchMethod.EXACT_RULE if matched else MatchMethod.SCORED_RULE),
        matcher_version=PBEV_MATCHER_VERSION,
        confidence=Decimal("100") if matched else Decimal("80"),
        review_required=not matched,
        evidence={},
        decision_reason=status.value,
        vehicle_sk=index if matched else None,
        selected_raw_row_id=index if matched else None,
        reviewed_by="reviewer" if reviewed else None,
        reviewed_at=datetime(2026, 8, 10, tzinfo=UTC) if reviewed else None,
    )


@pytest.mark.parametrize("year", [2017, 2020, 2021, 2022])
def test_four_versioned_layout_families_parse_synthetic_rows(year):
    row = _row(year)
    assert row.energy_mj_km == Decimal("1.50")
    assert row.raw.layout_family == next(item.layout_family for item in AUDITED_ASSETS if item.cycle_year == year)
    if year == 2022:
        assert row.emission_schema_version == "pbev-emissions-2022-mg-v1"
        assert row.nmog_nox_mg_km == Decimal("10")
        assert row.nmhc_mg_km is None
    else:
        assert row.emission_schema_version == "pbev-emissions-2017-2021-g-v1"
        assert row.nmhc_mg_km == Decimal("10.000")
        assert row.nmog_nox_mg_km is None


def test_parser_normalization_preserves_absence_and_decimal_precision():
    assert [normalize_cell(value) for value in ("-", "\\", "", "N/D", None)] == [None] * 5
    assert normalize_cell("co\u00adbertura") == "co-bertura"
    assert decimal_from_cell("1.234,567") == Decimal("1234.567")
    assert decimal_from_cell("-") is None


def test_asset_validation_rejects_origin_mime_signature_hash_and_page_drift(tmp_path, monkeypatch):
    audited = AUDITED_ASSETS[0]
    with pytest.raises(PbevValidationError):
        sanitize_official_url("http://www.gov.br/file.pdf")
    with pytest.raises(PbevValidationError):
        sanitize_official_url("https://user:secret@www.gov.br/file.pdf")

    text_path = tmp_path / "asset.txt"
    text_path.write_bytes(b"%PDF-fake")
    with pytest.raises(PbevValidationError, match="MIME"):
        PbevPdfParser().parse(text_path, audited)

    bad_signature = tmp_path / "bad.pdf"
    bad_signature.write_bytes(b"not-pdf")
    with pytest.raises(PbevValidationError, match="signature"):
        PbevPdfParser().parse(bad_signature, audited)

    fake_pdf = tmp_path / "hash.pdf"
    fake_pdf.write_bytes(b"%PDF-fake")
    with pytest.raises(PbevQuarantineError, match="hash"):
        PbevPdfParser().parse(fake_pdf, audited)

    content = b"%PDF-page-drift"
    drift_asset = replace(
        audited,
        sha256=hashlib.sha256(content).hexdigest(),
        byte_length=len(content),
        page_count=2,
    )
    fake_pdf.write_bytes(content)

    class FakeDocument:
        pages = [SimpleNamespace(width=842, height=595)]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(PbevPdfParser, "_pdfplumber", staticmethod(lambda: SimpleNamespace(open=lambda _path: FakeDocument())))
    with pytest.raises(PbevQuarantineError, match="page count"):
        PbevPdfParser().parse(fake_pdf, drift_asset)
    quarantined = PbevPdfParser().inspect_hash_drift(fake_pdf, audited)
    assert quarantined.asset_status == "quarantined"
    assert quarantined.storage_mode == "metadata_only"
    assert quarantined.document_bytes is None
    assert quarantined.validation_details["requires_layout_validation"] is True


def test_matcher_produces_all_five_states_without_fictitious_vehicle_ids():
    candidate = _row()
    matched = match_vehicle(_target(), [candidate])
    pending = match_vehicle(_target(motor_description=None), [candidate])
    ambiguous = match_vehicle(_target(version_name=None, motor_description=None), [candidate])
    rejected = match_vehicle(_target(catalog_conflict=True), [candidate])
    not_found = match_vehicle(_target(fuel_type="diesel"), [candidate])
    assert [item.mapping_status for item in (matched, pending, ambiguous, rejected, not_found)] == [
        MappingStatus.MATCHED,
        MappingStatus.PENDING,
        MappingStatus.AMBIGUOUS,
        MappingStatus.REJECTED,
        MappingStatus.NOT_FOUND,
    ]
    assert matched.vehicle_sk == 101
    assert all(item.vehicle_sk is None for item in (pending, ambiguous, rejected, not_found))


def test_materially_different_top_tie_is_ambiguous():
    first = _row(row_id=1, energy="1,50")
    second = _row(row_id=2, energy="1,70")
    decision = match_vehicle(_target(), [first, second])
    assert decision.mapping_status == MappingStatus.AMBIGUOUS
    assert decision.evidence["top_tie_count"] == 2
    assert decision.evidence["materially_different"] is True


@pytest.mark.parametrize(
    "value",
    ("VW", "Volkswagen", "VW - Volkswagen", "Volkswagen - VW"),
)
def test_brand_aliases_canonicalize_only_equivalent_volkswagen_names(value):
    assert _brand(value) == "vw"
    assert _brand(value) != _brand("Volvo")


@pytest.mark.parametrize(
    ("target_model", "candidate_model", "compatible"),
    (
        ("Onix LT", "ONIX", True),
        ("Onix LT", "ONIX PLUS", False),
        ("Onix LT", "ONIX JOY", False),
        ("Corolla GLi", "COROLLA", True),
        ("Corolla GLi", "COROLLA CROSS", False),
        ("Corolla GLi", "HILUX FLEX 4X4", False),
        ("Corolla GLi", "SW4 FLEX 4X2", False),
    ),
)
def test_model_family_is_anchored_and_ignores_generic_tokens(
    target_model,
    candidate_model,
    compatible,
):
    target = _target(catalog_model_name=target_model)
    candidate = _candidate(model=candidate_model)
    assert _model_compatible(target, candidate) is compatible


@pytest.mark.parametrize(
    ("target_motor", "candidate_motor", "compatible", "conflict"),
    (
        ("1.0", "1.0-12V", True, False),
        ("1.0", "1.6-16V", False, True),
        ("1.6", "1598 cm3", True, False),
        ("1.6", "1.598 cc", True, False),
    ),
)
def test_engine_displacement_uses_cc_tolerance_without_digit_intersection(
    target_motor,
    candidate_motor,
    compatible,
    conflict,
):
    assert ENGINE_DISPLACEMENT_TOLERANCE_CC == Decimal("50")
    assert _motor_compatible(target_motor, candidate_motor) == (compatible, conflict)


@pytest.mark.parametrize("candidate", ("A-4", "A-6", "CVT", "DCT-6", "MTA-5"))
def test_generic_automatic_accepts_recognized_automatic_transmissions(candidate):
    assert _transmission_compatible("Aut.", candidate) == (True, False)


def test_automatic_and_manual_remain_incompatible():
    assert _transmission_compatible("Aut.", "M-5") == (False, True)
    assert _transmission_compatible("Mec.", "CVT") == (False, True)


def test_model_year_qualifiers_filter_my_and_parenthesized_years():
    target = _target(
        model_year=2018,
        catalog_model_name="Prisma LT",
        version_name="LT",
        motor_description="1.4",
        transmission_type="Aut.",
        body_style="sedan",
    )
    my18 = _candidate(
        year=2018,
        model="PRISMA (MY18)",
        version="1.4AT LT",
        motor="1.4L-8V",
        transmission="A-6",
        category="Sedan",
    )
    my19 = replace(my18, model_name="PRISMA (MY19)")
    parenthesized_2019 = replace(my18, model_name="PRISMA (2019)")
    assert match_vehicle(target, [my18]).mapping_status == MappingStatus.MATCHED
    for candidate in (my19, parenthesized_2019):
        decision = match_vehicle(target, [candidate])
        assert decision.mapping_status == MappingStatus.NOT_FOUND
        assert "year" in decision.evidence["rejected_candidates"][0]["conflicts"]


def test_explicit_version_conflict_rejects_non_zen_candidates():
    target = _target(
        catalog_model_name="Sandero Zen",
        version_name="Zen",
        motor_description="1.0",
        transmission_type="manual",
    )
    candidate = _candidate(
        model="Sandero",
        version="Dynamique",
        motor="1.0-12V",
        transmission="M-5",
    )
    decision = match_vehicle(target, [candidate])
    assert decision.mapping_status == MappingStatus.NOT_FOUND
    assert "version" in decision.evidence["rejected_candidates"][0]["conflicts"]


def test_missing_version_is_rejected_when_comparable_versioned_variants_exist():
    target = _target(
        catalog_model_name="Duster Zen",
        version_name="Zen",
        motor_description="1.6",
        transmission_type="Aut.",
        body_style="suv",
    )
    missing = _candidate(
        model="Duster",
        version=None,
        motor="1.6-16V",
        transmission="CVT",
        category="SUV",
    )
    dynamique = replace(missing, version_name="Dynamique")
    decision = match_vehicle(target, [missing, dynamique])
    assert decision.mapping_status == MappingStatus.NOT_FOUND
    assert all(
        "version" in item["conflicts"]
        for item in decision.evidence["rejected_candidates"]
    )


def test_exact_version_is_preferred_over_broader_version_at_equal_score():
    target = _target(
        catalog_model_name="Kicks S",
        version_name="S",
        motor_description="1.6",
        transmission_type="Aut.",
        body_style="suv",
    )
    exact = _candidate(
        row_id=1,
        model="Kicks",
        version="S",
        motor="1.6-16V",
        transmission="CVT",
        category="SUV",
    )
    broader = replace(
        _candidate(
            row_id=2,
            model="Kicks",
            version="S DRCT",
            motor="1.6-16V",
            transmission="CVT",
            category="SUV",
        ),
        energy_mj_km=exact.energy_mj_km,
    )
    decision = match_vehicle(target, [exact, broader])
    assert decision.mapping_status == MappingStatus.MATCHED
    assert decision.evidence["selected_row_hash"] == exact.raw.row_hash


def test_material_stop_start_variant_remains_ambiguous():
    target = _target(
        catalog_model_name="Argo Drive",
        version_name="Drive",
        motor_description="1.0",
        transmission_type="Mec.",
        body_style="compact_hatch",
    )
    drive = _candidate(
        row_id=1,
        model="ARGO",
        version="DRIVE 1.0",
        motor="1.0-6V",
        transmission="M-5",
        category="Compacto",
    )
    stop_start = replace(
        _candidate(
            row_id=2,
            model="ARGO",
            version="DRIVE 1.0 STOP&START",
            motor="1.0-6V",
            transmission="M-5",
            category="Compacto",
        ),
        energy_mj_km=Decimal("1.44"),
    )
    decision = match_vehicle(target, [drive, stop_start])
    assert decision.mapping_status == MappingStatus.AMBIGUOUS
    assert decision.evidence["semantic_identity_count"] == 2


def test_version_normalization_accepts_ocr_live_suffix():
    target = _target(
        catalog_model_name="Yaris XL",
        version_name="XL",
        motor_description="1.3",
        transmission_type="Aut.",
        body_style="compact_hatch",
        evidence={"door_count": 5},
    )
    candidate = _candidate(
        model="Yaris Hatchback",
        version="XL Llive",
        motor="1.3-16V",
        transmission="CVT",
        category="Medio",
    )
    decision = match_vehicle(target, [candidate])
    assert decision.mapping_status == MappingStatus.MATCHED
    assert decision.evidence["dimensions"]["version"] == {
        "matched": True,
        "conflict": False,
        "exact": False,
    }


def test_body_and_door_evidence_separate_hatch_from_sedan():
    target = _target(
        catalog_model_name="Etios XLS",
        version_name="XLS",
        motor_description="1.5",
        transmission_type="Aut.",
        body_style="compact_hatch",
        evidence={"door_count": 5},
    )
    hatch = _candidate(
        year=2019,
        model="ETIOS HATCHBACK",
        version="XLS 5p",
        motor="1.5-16V",
        transmission="A-4",
        category="Compacto",
    )
    sedan = replace(hatch, model_name="ETIOS SEDAN", version_name="XLS 4p")
    _, hatch_evidence, hatch_conflicts = score_candidate(target, hatch)
    _, _, sedan_conflicts = score_candidate(target, sedan)
    assert hatch_evidence["body_style"]["matched"] is True
    assert not hatch_conflicts
    assert {"body_style", "doors"}.issubset(sedan_conflicts)


def test_equivalent_leaders_with_equal_metrics_are_collapsed_semantically():
    first = _candidate(row_id=1)
    second = _candidate(row_id=2)
    decision = match_vehicle(_target(), [first, second])
    assert decision.mapping_status == MappingStatus.MATCHED
    assert decision.evidence["equivalent_candidate_count"] == 2
    assert decision.evidence["semantic_identity_count"] == 1


def test_unknown_target_transmission_remains_pending():
    decision = match_vehicle(_target(transmission_type=None), [_candidate()])
    assert decision.mapping_status == MappingStatus.PENDING
    assert decision.vehicle_sk is None


def test_target_identity_helpers_preserve_unknowns_and_audit_fuel_mismatch():
    assert _engine_description("Versao 1.6 Flex") == "1.6"
    assert _engine_description("Versao sem cilindrada") is None
    assert _transmission("MOBI LIKE 1.0 Fire Flex 5p.") is None
    assert _transmission("Corolla 2.0 Flex Aut.") == "automatic_generic"
    assert _door_count("Etios XLS Flex 5p Aut.") == 5
    assert _body_style("compact_hatch", "Etios XLS 5p") == "hatch"
    assert _catalog_version("Corolla Cross XR") == "xr"
    assert _catalog_version("T-Cross 200 TSI") == "200 tsi"
    assert _target_version(
        "T-Cross 200 TSI",
        "T-Cross Comfor. 200 TSI 1.0 Flex 5p Aut.",
    ) == "comfortline 200 tsi"
    assert _fuel_identity_warning("Fit Flex/Flexone", "gasoline") is not None
    assert _fuel_identity_warning("Fit Flex/Flexone", "flex") is None


def test_provisional_reconciled_matrix_contains_all_34_references():
    expected = {
        1: (MappingStatus.AMBIGUOUS, "distinct_version_identities"),
        2: (MappingStatus.MATCHED, "normalized_identity"),
        3: (MappingStatus.MATCHED, "normalized_identity"),
        4: (MappingStatus.MATCHED, "normalized_identity"),
        5: (MappingStatus.MATCHED, "normalized_identity"),
        6: (MappingStatus.REJECTED, "catalog_conflict"),
        7: (MappingStatus.REJECTED, "catalog_conflict"),
        8: (MappingStatus.MATCHED, "normalized_identity"),
        9: (MappingStatus.MATCHED, "body_and_version_evidence"),
        10: (MappingStatus.MATCHED, "body_and_door_evidence"),
        11: (MappingStatus.MATCHED, "version_evidence"),
        12: (MappingStatus.MATCHED, "anchored_multiword_model"),
        13: (MappingStatus.NOT_FOUND, "fuel_identity_conflict"),
        14: (MappingStatus.MATCHED, "body_and_door_evidence"),
        15: (MappingStatus.MATCHED, "normalized_identity"),
        16: (MappingStatus.MATCHED, "normalized_identity"),
        17: (MappingStatus.AMBIGUOUS, "material_metrics_tie"),
        18: (MappingStatus.AMBIGUOUS, "material_metrics_tie"),
        19: (MappingStatus.PENDING, "insufficient_transmission_evidence"),
        20: (MappingStatus.PENDING, "insufficient_transmission_evidence"),
        21: (MappingStatus.MATCHED, "brand_alias_and_version_evidence"),
        22: (MappingStatus.PENDING, "insufficient_transmission_evidence"),
        23: (MappingStatus.REJECTED, "catalog_conflict"),
        24: (MappingStatus.AMBIGUOUS, "material_version_variant"),
        25: (MappingStatus.AMBIGUOUS, "material_metrics_tie"),
        26: (MappingStatus.NOT_FOUND, "no_compatible_version"),
        27: (MappingStatus.AMBIGUOUS, "material_metrics_tie"),
        28: (MappingStatus.NOT_FOUND, "missing_version_amid_variants"),
        29: (MappingStatus.MATCHED, "normalized_identity"),
        30: (MappingStatus.MATCHED, "normalized_identity"),
        31: (MappingStatus.MATCHED, "explicit_version_evidence"),
        32: (MappingStatus.MATCHED, "normalized_identity"),
        33: (MappingStatus.PENDING, "insufficient_transmission_evidence"),
        34: (MappingStatus.MATCHED, "body_and_version_evidence"),
    }
    assert sorted(expected) == list(range(1, 35))
    assert all(reason for _, reason in expected.values())
    assert Counter(status for status, _ in expected.values()) == {
        MappingStatus.MATCHED: 18,
        MappingStatus.AMBIGUOUS: 6,
        MappingStatus.REJECTED: 3,
        MappingStatus.NOT_FOUND: 3,
        MappingStatus.PENDING: 4,
    }
    assert {
        reference
        for reference, (status, _) in expected.items()
        if status == MappingStatus.PENDING
    } == {19, 20, 22, 33}


def test_pilot_catalog_conflicts_are_symmetric_and_rejected_candidates_are_audited():
    assert _catalog_conflict("HB20 Comfort", "HB20 Vision")
    assert _catalog_conflict("HB20 Vision", "HB20 Comfort")
    assert _catalog_conflict("Uno Attractive", "Uno Drive")
    decision = match_vehicle(_target(fuel_type="diesel"), [_row()])
    assert decision.mapping_status == MappingStatus.NOT_FOUND
    assert decision.evidence["rejected_candidates"][0]["conflicts"] == ("fuel",)


def test_manual_review_creates_append_only_supersession():
    previous = replace(_decision(MappingStatus.PENDING, 1), mapping_decision_id=42)
    reviewed_at = datetime(2026, 8, 10, tzinfo=UTC)
    replacement = supersede_mapping(
        previous,
        status=MappingStatus.MATCHED,
        reviewer="quality-owner",
        reviewed_at=reviewed_at,
        vehicle_sk=123,
        selected_raw_row_id=456,
        reason="reviewed source evidence",
    )
    assert previous.mapping_status == MappingStatus.PENDING
    assert replacement.mapping_decision_id is None
    assert replacement.supersedes_mapping_id == 42
    assert replacement.reviewed_at == reviewed_at


def test_quality_baseline_coverage_and_empty_shadow_gates():
    assert AUDITED_PILOT_COUNTS == {
        MappingStatus.MATCHED: 18,
        MappingStatus.AMBIGUOUS: 6,
        MappingStatus.REJECTED: 3,
        MappingStatus.NOT_FOUND: 3,
        MappingStatus.PENDING: 4,
    }
    decisions = []
    index = 1
    for status, count in AUDITED_PILOT_COUNTS.items():
        decisions.extend(_decision(status, item) for item in range(index, index + count))
        index += count
    enforce_audited_pilot_baseline(decisions, baseline_applicable=True)
    targets = [_target(vehicle_sk=item, brand_name="Marca", model_year=2019) for item in range(1, 35)]
    report = build_coverage_report(
        dataset_version="shadow-test",
        asset_manifest=(),
        targets=targets,
        mappings=decisions,
        field_coverage={},
        generated_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    assert report.universe_count == 34
    assert report.matched_count == report.published_count == 18
    assert report.coverage_percentage == Decimal("52.94")
    assert isinstance(report.coverage_percentage, Decimal)
    matched_vehicle_ids = list(range(1, 19))
    validate_shadow_rows(decisions, matched_vehicle_ids)
    with pytest.raises(ValueError, match="empty"):
        validate_shadow_rows([], [])
    for non_publishable_id in (19, 25, 28, 31):
        with pytest.raises(ValueError, match="reconcile"):
            validate_shadow_rows(
                decisions,
                [*matched_vehicle_ids[:-1], non_publishable_id],
            )

    regressed = [item for item in decisions if item.vehicle_sk != 18]
    regressed.append(_decision(MappingStatus.AMBIGUOUS, 99))
    with pytest.raises(ValueError, match="regressed"):
        enforce_audited_pilot_baseline(regressed, baseline_applicable=True)

    redistributed = list(decisions)
    redistributed[-1] = _decision(MappingStatus.AMBIGUOUS, 34)
    with pytest.raises(ValueError, match="classification"):
        enforce_audited_pilot_baseline(redistributed, baseline_applicable=True)

    pending_indexes = [
        index
        for index, decision in enumerate(decisions)
        if decision.mapping_status == MappingStatus.PENDING
    ]
    assert len(pending_indexes) == 4
    for pending_index in pending_indexes:
        increased = list(decisions)
        increased[pending_index] = _decision(
            MappingStatus.MATCHED,
            decisions[pending_index].target_identity_evidence["index"],
        )
        with pytest.raises(ValueError, match="review evidence"):
            enforce_audited_pilot_baseline(increased, baseline_applicable=True)

    increased = list(decisions)
    increased[-1] = _decision(MappingStatus.MATCHED, 34, reviewed=True)
    enforce_audited_pilot_baseline(increased, baseline_applicable=True)


def test_dry_run_does_not_resolve_assets_open_database_or_call_network():
    result = run_pbev_pipeline(
        None,
        PbevExecutionOptions(asset_directory=Path("must-not-exist"), dry_run=True),
        cancellation_token=CancellationToken(),
    )
    assert result.status == "succeeded"
    assert result.assets_processed == result.rows_extracted == result.published_count == 0


def test_download_retries_only_transient_status_and_honors_retry_after(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "2"})
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-synthetic")

    delays = []
    with PbevAssetClient(
        PbevDownloadPolicy(max_attempts=2, backoff_seconds=0),
        transport=httpx.MockTransport(handler),
        sleep=delays.append,
    ) as client:
        destination = client.download(AUDITED_ASSETS[0], tmp_path / "external.pdf")
    assert destination.read_bytes() == b"%PDF-synthetic"
    assert len(calls) == 2
    assert delays == [2.0]


@pytest.mark.skipif(not os.getenv("PBEV_TEST_ASSET_DIR"), reason="PBEV_TEST_ASSET_DIR not configured")
def test_official_audited_assets_from_external_directory():
    directory = Path(os.environ["PBEV_TEST_ASSET_DIR"]).resolve(strict=True)
    located = find_audited_assets(directory)
    assert len(located) == len(AUDITED_ASSETS)
    results = [PbevPdfParser().parse(located[asset], asset) for asset in AUDITED_ASSETS]
    assert [len(item.rows) for item in results] == [asset.expected_row_count for asset in AUDITED_ASSETS]
    assert all(not item.fallback_pages for item in results)
