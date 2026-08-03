from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine

from data_platform.contracts.silver_fipe import (
    BronzeFipeInput,
    SilverPersistenceOutcome,
)
from data_platform.quality.silver_checks import quality_issue
from data_platform.reconciliation.legacy_cars import reconcile_legacy_vehicles
from data_platform.transformation.fipe import (
    FUEL_VOCABULARY,
    build_canonical_key,
    decide_price_history,
    normalize_display,
    normalize_fuel,
    parse_brl_price,
    parse_reference_month,
    transform_bronze_record,
)
from data_platform.transformation.loader import SilverLoader, historical_mapping_matches
from data_platform.transformation.pipeline import (
    SilverPipelinePersistenceError,
    run_silver_pipeline,
)


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
VALID_PAYLOAD = {
    "brand": "Chevrolet",
    "model": "ONIX HATCH LT 1.0 12V Flex 5p Mec.",
    "modelYear": 2021,
    "fuel": "Flex",
    "fuelAcronym": "F",
    "codeFipe": "004517-9",
    "price": "R$ 80.000,00",
    "referenceMonth": "agosto de 2026",
}


def bronze_record(
    payload=None,
    *,
    fipe_raw_id=1,
    year_code="2021-1",
    status="received",
    http_status=200,
    reference_month_raw="agosto de 2026",
):
    return BronzeFipeInput(
        fipe_raw_id=fipe_raw_id,
        bronze_pipeline_run_id=uuid4(),
        source_name="Tabela FIPE via API Parallelum",
        vehicle_type="car",
        source_record_key=f"004517-9:{year_code}",
        fipe_code="004517-9",
        year_code=year_code,
        reference_month_raw=reference_month_raw,
        http_status=http_status,
        collected_at=NOW,
        payload=VALID_PAYLOAD if payload is None else payload,
        payload_hash="a" * 64,
        schema_fingerprint="b" * 64,
        ingestion_status=status,
    )


def codes(candidate):
    return {item.rule_code for item in candidate.issues}


def test_normalization_and_canonical_key_ignore_only_case_accents_and_spaces():
    first = build_canonical_key(
        vehicle_type="car",
        brand_name="Citroën",
        model_name="C3   Live 1.0",
        version_name=None,
        model_year=2021,
        is_zero_km=False,
        fuel_type="flex",
    )
    second = build_canonical_key(
        vehicle_type=" CAR ",
        brand_name="  CITROEN ",
        model_name="c3 live 1.0",
        version_name=None,
        model_year=2021,
        is_zero_km=False,
        fuel_type="FLEX",
    )
    different_punctuation = build_canonical_key(
        vehicle_type="car",
        brand_name="Citroen",
        model_name="C3 Live-1.0",
        version_name=None,
        model_year=2021,
        is_zero_km=False,
        fuel_type="flex",
    )
    assert first == second
    assert first != different_punctuation
    assert len(first) == 64


def test_zero_km_key_is_distinct_from_missing_year_and_regular_year():
    common = {
        "vehicle_type": "car",
        "brand_name": "Marca",
        "model_name": "Modelo",
        "version_name": None,
        "fuel_type": "gasoline",
    }
    zero = build_canonical_key(**common, model_year=None, is_zero_km=True)
    missing = build_canonical_key(**common, model_year=None, is_zero_km=False)
    regular = build_canonical_key(**common, model_year=2026, is_zero_km=False)
    assert len({zero, missing, regular}) == 3


def test_display_values_keep_accents_case_punctuation_and_full_model():
    payload = {
        **VALID_PAYLOAD,
        "brand": "  Citroën  ",
        "model": " C3   Live 1.0 — Série Especial ",
    }
    candidate = transform_bronze_record(bronze_record(payload))
    assert candidate.mapping_status == "matched"
    assert candidate.identity.brand_name == "Citroën"
    assert candidate.identity.model_name == "C3 Live 1.0 — Série Especial"
    assert candidate.identity.version_name is None
    assert candidate.identity.transmission_type is None
    assert normalize_display("  A   B ") == "A B"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Gasolina", "gasoline"),
        ("Álcool", "ethanol"),
        ("Flex", "flex"),
        ("Diesel", "diesel"),
        ("Elétrico", "electric"),
        ("Híbrido", "hybrid"),
        ("GNV", "cng"),
    ],
)
def test_fuel_vocabulary(raw, expected):
    assert normalize_fuel(raw) == expected
    assert expected in FUEL_VOCABULARY


@pytest.mark.parametrize("fuel", [None, "", "hidrogenio", 123])
def test_missing_or_unmapped_fuel_is_pending_without_price(fuel):
    candidate = transform_bronze_record(
        bronze_record({**VALID_PAYLOAD, "fuel": fuel, "fuelAcronym": None})
    )
    assert candidate.mapping_status == "pending"
    assert candidate.identity is None
    assert candidate.price is None
    assert "UNMAPPED_FUEL" in codes(candidate)


def test_proven_fuel_acronym_conflict_is_ambiguous_and_requires_review():
    candidate = transform_bronze_record(
        bronze_record({**VALID_PAYLOAD, "fuel": "Gasolina", "fuelAcronym": "D"})
    )
    assert candidate.mapping_status == "ambiguous"
    assert candidate.identity is None
    assert candidate.price is None
    assert candidate.review_notes
    assert "FUEL_CONFLICT" in codes(candidate)


def test_unknown_fuel_acronym_warns_but_does_not_override_primary_fuel():
    candidate = transform_bronze_record(
        bronze_record({**VALID_PAYLOAD, "fuelAcronym": "?"})
    )
    assert candidate.mapping_status == "matched"
    assert candidate.identity.fuel_type == "flex"
    assert candidate.price is not None
    assert "UNMAPPED_FUEL_ACRONYM" in codes(candidate)


def test_regular_year_preserves_full_year_code_and_cross_validates_model_year():
    candidate = transform_bronze_record(bronze_record(year_code="2021-9"))
    assert candidate.mapping_status == "matched"
    assert candidate.bronze.year_code == "2021-9"
    assert candidate.source_vehicle_key == "004517-9:2021-9"
    assert candidate.identity.model_year == 2021
    assert candidate.identity.is_zero_km is False


def test_model_year_32000_creates_zero_km_identity_without_model_year():
    candidate = transform_bronze_record(
        bronze_record(
            {**VALID_PAYLOAD, "modelYear": 32000},
            year_code="32000-1",
        )
    )
    assert candidate.mapping_status == "matched"
    assert candidate.identity.model_year is None
    assert candidate.identity.is_zero_km is True
    assert candidate.price.price_amount == Decimal("80000.00")


def test_model_year_conflict_is_ambiguous_without_price():
    candidate = transform_bronze_record(
        bronze_record({**VALID_PAYLOAD, "modelYear": 2020})
    )
    assert candidate.mapping_status == "ambiguous"
    assert candidate.price is None
    assert "MODEL_YEAR_CONFLICT" in codes(candidate)


def test_brl_price_uses_decimal_and_never_accepts_float():
    value = parse_brl_price("R$ 123.456,78")
    assert value == Decimal("123456.78")
    assert isinstance(value, Decimal)
    with pytest.raises(ValueError):
        parse_brl_price(123456.78)
    with pytest.raises(ValueError):
        parse_brl_price("USD 10.00")
    with pytest.raises(ValueError):
        parse_brl_price("R$ 0,00")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Janeiro de 2026", date(2026, 1, 1)),
        ("MARÇO DE 2025", date(2025, 3, 1)),
        ("  dezembro   de  2024 ", date(2024, 12, 1)),
    ],
)
def test_reference_month_is_first_day(raw, expected):
    assert parse_reference_month(raw) == expected


def test_invalid_price_or_reference_keeps_mapping_but_creates_no_history():
    candidate = transform_bronze_record(
        bronze_record(
            {**VALID_PAYLOAD, "price": "80 mil", "referenceMonth": "hoje"},
            reference_month_raw="hoje",
        )
    )
    assert candidate.mapping_status == "matched"
    assert candidate.identity is not None
    assert candidate.price is None
    assert {"INVALID_PRICE", "INVALID_REFERENCE_MONTH"}.issubset(codes(candidate))


def test_history_newer_reference_becomes_current_and_closes_predecessor():
    price = transform_bronze_record(bronze_record()).price
    decision = decide_price_history(price, predecessor_exists=True)
    assert decision.action == "insert"
    assert decision.valid_from == datetime(2026, 8, 1, tzinfo=UTC)
    assert decision.valid_to is None
    assert decision.is_current is True
    assert decision.close_predecessor is True


def test_history_older_reference_is_non_current_and_keeps_successor():
    price = transform_bronze_record(bronze_record()).price
    successor = datetime(2026, 10, 1, tzinfo=UTC)
    decision = decide_price_history(
        price,
        predecessor_exists=True,
        successor_valid_from=successor,
    )
    assert decision.action == "insert"
    assert decision.valid_to == successor
    assert decision.is_current is False
    assert decision.close_predecessor is True


def test_history_same_month_same_price_is_idempotent_and_difference_conflicts():
    price = transform_bronze_record(bronze_record()).price
    same = decide_price_history(
        price,
        existing_price=Decimal("80000.00"),
        existing_currency="BRL",
    )
    conflict = decide_price_history(
        price,
        existing_price=Decimal("80000.01"),
        existing_currency="BRL",
    )
    assert same.action == "idempotent"
    assert conflict.action == "conflict"


@pytest.mark.parametrize("field", ["brand", "model"])
def test_missing_identity_fields_are_pending(field):
    payload = dict(VALID_PAYLOAD)
    payload.pop(field)
    candidate = transform_bronze_record(bronze_record(payload))
    assert candidate.mapping_status == "pending"
    assert candidate.identity is None
    assert candidate.price is None
    assert "MISSING_IDENTITY_FIELD" in codes(candidate)


def test_unexpected_payload_is_rejected_without_fictitious_defaults():
    candidate = transform_bronze_record(bronze_record([VALID_PAYLOAD]))
    assert candidate.mapping_status == "rejected"
    assert candidate.identity is None
    assert candidate.price is None
    assert "UNEXPECTED_PAYLOAD" in codes(candidate)


def test_non_received_bronze_is_not_eligible():
    candidate = transform_bronze_record(
        bronze_record(None, status="http_error", http_status=503)
    )
    assert candidate.mapping_status == "rejected"
    assert "INELIGIBLE_BRONZE_RECORD" in codes(candidate)


def test_quality_issue_sanitizes_secrets_and_does_not_include_payload():
    issue = quality_issue(
        "TEST",
        "password=secret",
        details={"token": "api_key=hidden"},
    )
    assert "secret" not in issue.message
    assert "hidden" not in repr(issue.details)


def test_sqlite_transform_is_deliberate_noop():
    engine = create_engine("sqlite:///:memory:")
    try:
        result = run_silver_pipeline(SilverLoader(engine))
    finally:
        engine.dispose()
    assert result.status == "skipped"
    assert result.pipeline_run_id is None
    assert result.records_inserted == 0


class FakePipelineLoader:
    is_postgresql = True

    def __init__(self, records, outcomes=None, persist_error=None, finish_errors=None, fetch_error=None):
        self.records = records
        self.outcomes = iter(outcomes or [])
        self.persist_error = persist_error
        self.fetch_error = fetch_error
        self.finish_errors = iter(finish_errors or [])
        self.started = []
        self.finished = []

    def fetch_received_records(self):
        if self.fetch_error:
            raise self.fetch_error
        return self.records

    def start_run(self, *args):
        self.started.append(args)

    def persist_candidate(self, *_args):
        if self.persist_error:
            raise self.persist_error
        return next(self.outcomes)

    def finish_run(self, *args):
        self.finished.append(args)
        error = next(self.finish_errors, None)
        if error:
            raise error


def test_pipeline_counts_insert_and_idempotent_reprocessing():
    loader = FakePipelineLoader(
        [bronze_record()],
        [SilverPersistenceOutcome(inserted_rows=3)],
    )
    first = run_silver_pipeline(loader)
    duplicate_loader = FakePipelineLoader(
        [bronze_record()],
        [SilverPersistenceOutcome(deduplicated=True)],
    )
    second = run_silver_pipeline(duplicate_loader)
    assert (first.records_inserted, first.records_deduplicated) == (1, 0)
    assert (second.records_inserted, second.records_deduplicated) == (0, 1)


def test_historical_mapping_reprocessing_validates_original_evidence_before_current_state():
    payload = {**VALID_PAYLOAD, "fuel": None, "fuelAcronym": None}
    candidate = transform_bronze_record(bronze_record(payload, fipe_raw_id=77))
    persisted = {
        "source_name": candidate.bronze.source_name,
        "fipe_code": candidate.bronze.fipe_code,
        "year_code": candidate.bronze.year_code,
        "source_vehicle_key": candidate.source_vehicle_key,
        "mapping_status": "pending",
    }
    assert historical_mapping_matches(candidate, persisted)
    for field, incompatible in (
        ("source_name", "different-source"),
        ("fipe_code", "999999-9"),
        ("year_code", "2022-1"),
        ("source_vehicle_key", "999999-9:2022-1"),
        ("mapping_status", "matched"),
    ):
        changed = {**persisted, field: incompatible}
        assert not historical_mapping_matches(candidate, changed)


def test_dry_run_does_not_start_or_persist_and_keeps_inserted_zero():
    loader = FakePipelineLoader([bronze_record()])
    result = run_silver_pipeline(loader, dry_run=True)
    assert result.status == "succeeded"
    assert result.records_received == 1
    assert result.records_inserted == 0
    assert loader.started == []
    assert loader.finished == []


def test_persistence_failure_marks_run_failed_without_exposing_secret():
    loader = FakePipelineLoader(
        [bronze_record()],
        persist_error=RuntimeError("password=silver-secret"),
    )
    result = run_silver_pipeline(loader)
    assert result.status == "failed"
    assert loader.finished[-1][1] == "failed"
    assert "silver-secret" not in repr(result.errors)


def test_bronze_read_failure_is_sanitized_before_any_run_starts():
    loader = FakePipelineLoader(
        [],
        fetch_error=RuntimeError("token=read-secret"),
    )
    with pytest.raises(SilverPipelinePersistenceError) as error:
        run_silver_pipeline(loader)
    assert "read-secret" not in str(error.value)
    assert loader.started == []


def test_second_finalization_failure_is_sanitized():
    loader = FakePipelineLoader(
        [bronze_record()],
        [SilverPersistenceOutcome(inserted_rows=3)],
        finish_errors=[RuntimeError("token=first-secret"), RuntimeError("password=second-secret")],
    )
    with pytest.raises(SilverPipelinePersistenceError) as error:
        run_silver_pipeline(loader)
    assert "first-secret" not in str(error.value)
    assert "second-secret" not in str(error.value)


@dataclass(frozen=True)
class LegacyProfile:
    code: str
    year_code: str


def test_legacy_report_is_read_only_and_uses_ids_only_as_external_references():
    profiles = {
        1: LegacyProfile("004517-9", "2021"),
        2: LegacyProfile("004436-9", "2018"),
        3: LegacyProfile("004421-0", "2018"),
        4: LegacyProfile("004415-6", "2019"),
    }
    cache = [
        {"vehicle_id": 1, "year_code": "2021-1"},
        {"vehicle_id": 2, "year_code": "2018-1"},
        {"vehicle_id": 3, "year_code": "2018-1"},
    ]
    mappings = [
        {
            "fipe_code": "004517-9",
            "year_code": "2021-1",
            "mapping_status": "matched",
            "vehicle_sk": 901,
        },
        {
            "fipe_code": "004436-9",
            "year_code": "2018-1",
            "mapping_status": "ambiguous",
            "vehicle_sk": None,
        },
        {
            "fipe_code": "004421-0",
            "year_code": "2018-1",
            "mapping_status": "rejected",
            "vehicle_sk": None,
        },
    ]
    rows = reconcile_legacy_vehicles(profiles, cache, mappings)
    assert [row.legacy_vehicle_id for row in rows] == [1, 2, 3, 4]
    assert [row.mapping_status for row in rows] == [
        "matched",
        "ambiguous",
        "rejected",
        "rejected",
    ]
    assert rows[0].vehicle_sk == 901
    assert rows[0].vehicle_sk != rows[0].legacy_vehicle_id
    assert all("canonical" not in row.as_dict() for row in rows)


def test_current_legacy_inventory_report_covers_all_34_automobiles():
    from backend.app.fipe import FIPE_REFERENCE_PROFILES

    cache_path = Path(__file__).parents[2] / "backend" / "data" / "fipe_cache.json"
    cached_items = json.loads(cache_path.read_text(encoding="utf-8"))
    rows = reconcile_legacy_vehicles(FIPE_REFERENCE_PROFILES, cached_items, [])
    assert len(rows) == 34
    assert {row.legacy_vehicle_id for row in rows} == set(range(1, 35))
    assert all(row.mapping_status == "pending" for row in rows)


def test_migration_declares_status_lineage_history_and_sqlite_constraints():
    migration = (
        Path(__file__).parents[2]
        / "backend"
        / "alembic"
        / "versions"
        / "20260803_0003_data_platform_silver_fipe.py"
    ).read_text(encoding="utf-8")
    for marker in (
        "vehicle_identity",
        "vehicle_source_mapping",
        "vehicle_price_history",
        "is_zero_km",
        "bronze_record_id",
        "pipeline_run_id",
        "sa.Numeric(14, 2)",
        "uq_data_quality_issue_open_silver",
        "if not _is_postgresql()",
    ):
        assert marker in migration


def test_silver_tests_never_call_external_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("real network forbidden")

    monkeypatch.setattr(httpx.Client, "send", forbidden)
    assert transform_bronze_record(bronze_record()).mapping_status == "matched"
