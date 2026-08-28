from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine

from data_platform.common.logging import sanitize
from data_platform.contracts.gold_vehicle_features import GoldScopeRow
from data_platform.publication.cli import build_parser
from data_platform.publication.loader import GoldLoader
from data_platform.publication.pipeline import (
    _rollback_quality_mismatches,
    build_publication_plan,
    rollback_gold_dataset,
    run_gold_publication,
)
from data_platform.quality.gold_checks import (
    calculate_coverage,
    classify_freshness,
    effective_quality_status,
    issue_resolution_is_coherent,
    safe_issue_details,
)


def scope_row(**changes) -> GoldScopeRow:
    run_id = uuid4()
    values = {
        "mapping_id": 10,
        "mapping_status": "matched",
        "vehicle_sk": 100,
        "vehicle_type": "car",
        "source_name": "Tabela FIPE via API Parallelum",
        "source_vehicle_key": "004517-9:2021-1",
        "fipe_code": "004517-9",
        "year_code": "2021-1",
        "mapping_run_id": run_id,
        "identity_vehicle_sk": 100,
        "identity_vehicle_type": "car",
        "brand_name": "Honda",
        "model_name": "City Sedan EX 1.5 Flex 16V 4p Aut.",
        "version_name": None,
        "model_year": 2021,
        "is_zero_km": False,
        "fuel_type": "flex",
        "transmission_type": None,
        "identity_run_id": run_id,
        "silver_price_id": 1000,
        "price_vehicle_sk": 100,
        "price_amount": Decimal("80000.00"),
        "currency": "BRL",
        "reference_month": date(2026, 8, 1),
        "price_collected_at": datetime(2026, 8, 2, tzinfo=UTC),
        "data_confidence": Decimal("100.00"),
        "price_run_id": run_id,
    }
    values.update(changes)
    return GoldScopeRow(**values)


def issue(
    issue_id: int,
    *,
    layer: str = "gold",
    reference: str | None = None,
    severity: str = "warning",
    status: str = "open",
):
    return {
        "issue_id": issue_id,
        "layer_name": layer,
        "entity_name": "test",
        "record_reference": reference,
        "rule_code": f"RULE_{issue_id}",
        "severity": severity,
        "message": "safe",
        "details": {},
        "resolution_status": status,
        "resolved_at": (
            None if status == "open" else datetime(2026, 8, 2, tzinfo=UTC)
        ),
    }


def build(scope, issues=(), *, day=date(2026, 8, 3)):
    return build_publication_plan(
        scope,
        issues,
        as_of=day,
        now=datetime.combine(day, datetime.min.time(), tzinfo=UTC)
        + timedelta(hours=12),
    )


def test_coverage_uses_decimal_and_accepts_exactly_eighty_percent():
    coverage = calculate_coverage(5, 4)
    assert coverage == Decimal("80.00")
    assert isinstance(coverage, Decimal)
    assert calculate_coverage(6, 4) == Decimal("66.67")
    assert calculate_coverage(0, 0) == Decimal("0.00")
    with pytest.raises(ValueError):
        calculate_coverage(1, 2)


def test_freshness_and_effective_quality_are_dynamic():
    as_of = date(2026, 8, 3)
    assert classify_freshness(as_of - timedelta(days=45), as_of=as_of) == "current"
    assert classify_freshness(as_of - timedelta(days=46), as_of=as_of) == "stale"
    assert classify_freshness(as_of - timedelta(days=90), as_of=as_of) == "stale"
    assert classify_freshness(as_of - timedelta(days=91), as_of=as_of) == "expired"
    assert effective_quality_status("passed", "current") == "passed"
    assert effective_quality_status("passed", "stale") == "warning"
    assert effective_quality_status("passed", "expired") == "warning"
    assert effective_quality_status("warning", "current") == "warning"


def test_denominator_includes_unresolved_car_mappings_and_blocks_them():
    rows = (
        scope_row(mapping_id=1, vehicle_sk=1, identity_vehicle_sk=1, silver_price_id=11, price_vehicle_sk=1),
        scope_row(mapping_id=2, mapping_status="pending", vehicle_sk=None, identity_vehicle_sk=None, silver_price_id=None, price_vehicle_sk=None),
        scope_row(mapping_id=3, mapping_status="ambiguous", vehicle_sk=None, identity_vehicle_sk=None, silver_price_id=None, price_vehicle_sk=None),
        scope_row(mapping_id=4, mapping_status="rejected", vehicle_sk=None, identity_vehicle_sk=None, silver_price_id=None, price_vehicle_sk=None),
    )
    plan = build(rows)
    assert (plan.expected_count, plan.published_count, plan.blocked_count) == (4, 1, 3)
    assert {item.reason_code for item in plan.blocked_mappings} == {
        "MAPPING_PENDING",
        "MAPPING_AMBIGUOUS",
        "MAPPING_REJECTED",
    }


def test_source_key_is_validated_without_using_raw_bronze_key():
    plan = build((scope_row(source_vehicle_key="raw-conflict"),))
    assert plan.published_count == 0
    assert plan.blocked_mappings[0].reason_code == "INVALID_SOURCE_KEY"


def test_open_silver_critical_issue_is_global_without_bronze_lookup():
    plan = build(
        (scope_row(),),
        (
            issue(
                1,
                layer="silver",
                reference="bronze.fipe_raw:99",
                severity="critical",
            ),
        ),
    )
    assert plan.published_count == 1
    assert plan.global_blockers == ("SILVER_CRITICAL:1",)


def test_accepted_issue_warns_and_resolved_issue_does_not_apply():
    accepted = issue(
        1,
        reference="silver.vehicle_source_mapping:10",
        severity="critical",
        status="accepted",
    )
    resolved = issue(
        2,
        reference="silver.vehicle_source_mapping:10",
        severity="critical",
        status="resolved",
    )
    plan = build((scope_row(),), (accepted, resolved))
    assert plan.published_count == 1
    assert plan.candidates[0].base_quality_status == "warning"
    assert plan.base_quality_status == "warning"


def test_open_attributable_gold_critical_blocks_only_its_mapping():
    rows = (
        scope_row(mapping_id=10),
        scope_row(
            mapping_id=11,
            vehicle_sk=101,
            identity_vehicle_sk=101,
            silver_price_id=1001,
            price_vehicle_sk=101,
            fipe_code="004518-7",
            source_vehicle_key="004518-7:2021-1",
        ),
    )
    plan = build(
        rows,
        (
            issue(
                1,
                reference="silver.vehicle_source_mapping:10",
                severity="critical",
            ),
        ),
    )
    assert plan.published_count == 1
    assert plan.candidates[0].mapping_id == 11
    assert plan.blocked_mappings[0].reason_code == "APPLICABLE_CRITICAL_ISSUE"
    assert not plan.global_blockers


def test_fingerprint_is_deterministic_and_excludes_freshness_clock():
    row = scope_row(reference_month=date(2026, 5, 1))
    first = build((row,), day=date(2026, 8, 3))
    second = build((row,), day=date(2026, 8, 20))
    assert first.fingerprint == second.fingerprint
    assert len(first.fingerprint) == 64


def test_duplicate_vehicle_candidates_are_rejected_without_arbitrary_winner():
    rows = (
        scope_row(mapping_id=10),
        scope_row(
            mapping_id=11,
            silver_price_id=1001,
            fipe_code="004518-7",
            source_vehicle_key="004518-7:2021-1",
        ),
    )
    plan = build(rows)
    assert plan.published_count == 0
    assert {item.reason_code for item in plan.blocked_mappings} == {
        "DUPLICATE_VEHICLE_MAPPING"
    }


def test_issue_resolution_coherence_and_sanitization():
    resolved_at = datetime(2026, 8, 3, tzinfo=UTC)
    assert issue_resolution_is_coherent("open", None)
    assert issue_resolution_is_coherent("accepted", resolved_at)
    assert not issue_resolution_is_coherent("accepted", None)
    details = safe_issue_details(
        {"mapping_id": 1, "url": "https://user:secret@example.com/path", "token": "x"}
    )
    assert details == {"mapping_id": "1"}


@pytest.mark.parametrize(
    ("message", "safe_location"),
    (
        (
            "postgresql://synthetic-user:synthetic-secret@localhost:5432/sigra_test",
            "postgresql://localhost:5432/sigra_test",
        ),
        (
            "prefix connection failed for "
            "postgresql+psycopg://synthetic-user:synthetic-secret@localhost:5432/sigra_test "
            "suffix",
            "postgresql+psycopg://localhost:5432/sigra_test",
        ),
        (
            "error https://synthetic-user:synthetic-secret@example.test/path end",
            "https://example.test/path",
        ),
        (
            "error postgresql://synthetic%2Duser:synthetic%2Dsecret@localhost/sigra_test",
            "postgresql://localhost/sigra_test",
        ),
    ),
)
def test_sanitize_removes_authenticated_url_userinfo(message, safe_location):
    result = sanitize(message)
    for secret in (
        "synthetic-user",
        "synthetic-secret",
        "synthetic%2Duser",
        "synthetic%2Dsecret",
    ):
        assert secret not in result
    assert safe_location in result


def test_sanitize_preserves_existing_secret_key_redaction():
    result = sanitize(
        "password=value-one passwd=value-two token=value-three "
        "api_key=value-four api-key=value-five secret=value-six"
    )
    for secret in (
        "value-one",
        "value-two",
        "value-three",
        "value-four",
        "value-five",
        "value-six",
    ):
        assert secret not in result


def test_rollback_quality_mismatch_is_only_passed_to_warning():
    warning = build((scope_row(),), (issue(1, layer="silver", status="accepted"),))
    passed = build((scope_row(),))

    assert _rollback_quality_mismatches(
        {100: "passed"}, warning.candidates
    ) == (100,)
    assert _rollback_quality_mismatches(
        {100: "warning"}, passed.candidates
    ) == ()


def test_sqlite_publication_and_rollback_are_deliberate_noops():
    engine = create_engine("sqlite:///:memory:")
    try:
        loader = GoldLoader(engine)
        publication = run_gold_publication(loader)
        rollback = rollback_gold_dataset(loader, "old")
    finally:
        engine.dispose()
    assert publication.status == "skipped"
    assert rollback.status == "skipped"


def test_gold_cli_requires_explicit_publish_or_rollback_command():
    parser = build_parser()
    assert parser.parse_args(["publish"]).command == "publish"
    rollback = parser.parse_args(["rollback", "dataset-v1"])
    assert rollback.command == "rollback"
    assert rollback.dataset_version == "dataset-v1"


def test_gold_publication_source_never_queries_bronze_or_network():
    publication = Path(__file__).parents[1] / "publication"
    source = "\n".join(
        item.read_text(encoding="utf-8")
        for item in sorted(publication.glob("*.py"))
    ).lower()
    assert "bronze." not in source
    assert "requests" not in source
    assert "httpx" not in source
    assert "urllib.request" not in source


def test_migration_orders_nullable_backfill_validation_and_not_null():
    migration_path = (
        Path(__file__).parents[2]
        / "backend"
        / "alembic"
        / "versions"
        / "20260803_0004_data_platform_gold_vehicle_features.py"
    )
    migration = migration_path.read_text(encoding="utf-8")
    add_nullable = migration.index('sa.Column("vehicle_type", sa.String(20), nullable=True)')
    backfill = migration.index("SET vehicle_type = bronze.vehicle_type")
    validation = migration.index("Silver vehicle_type backfill aborted")
    not_null = migration.index('"vehicle_type",\n        existing_type=sa.String(20)')
    assert add_nullable < backfill < validation < not_null
    assert "bronze.source_record_key IS DISTINCT FROM" not in migration
    assert "mapping.fipe_code || ':' || mapping.year_code" in migration
    for marker in (
        "vehicle_feature_dataset",
        "vehicle_features_snapshot",
        "vehicle_feature_dataset_activation",
        "vehicle_features_current",
        "trg_gold_snapshot_immutable",
        "trg_gold_activation_immutable",
        "_abort_incompatible_downgrade()\n    _drop_gold_tables()",
        "if not _is_postgresql()",
    ):
        assert marker in migration
