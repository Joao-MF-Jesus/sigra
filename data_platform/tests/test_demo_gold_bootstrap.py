from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.pool import StaticPool

from scripts.bootstrap_postgresql_demo_gold import (
    ANP_SOURCE_REFERENCE,
    DEMO_CATALOG_MARKER,
    DEMO_DATABASE,
    DEMO_GEOGRAPHY_KEY,
    DEMO_PROVENANCE,
    DEMO_WEEK_START,
    PBEV_METHODOLOGY,
    DemoAnpClient,
    _activation_reconciliation_plan,
    _canonical_catalog_rows,
    _load_fipe_cache,
    _resolve_demo_anp_source,
    bootstrap_demo_catalog,
    build_demo_pbev_fixture,
    validate_catalog,
    validate_demo_database_url,
)
from data_platform.contracts.pbev import ExternalVehicleIdentity, MappingStatus
from data_platform.ingestion.anp.parser import AnpCsvParser
from data_platform.pbev.loader import (
    PBEV_OFFICIAL_METHODOLOGY_REFERENCE,
    PbevLoader,
)
from data_platform.quality.pbev_checks import enforce_audited_pilot_baseline


def _targets() -> tuple[ExternalVehicleIdentity, ...]:
    return tuple(
        ExternalVehicleIdentity(
            vehicle_sk=index,
            brand_name=f"Brand {index}",
            model_name=f"Model {index}",
            model_year=2020,
            fuel_type="flex",
            external_catalog_reference=index,
            evidence={"external_reference": index},
        )
        for index in range(1, 35)
    )


def _postgresql_url(host: str, database: str, port: int = 54329) -> str:
    return URL.create(
        "postgresql+psycopg",
        username="demo",
        password="synthetic",
        host=host,
        port=port,
        database=database,
    ).render_as_string(hide_password=False)


def test_demo_database_target_is_local_exact_and_sanitized():
    summary = validate_demo_database_url(
        _postgresql_url("127.0.0.1", "sigra_postgresql_demo")
    )
    assert summary == {
        "backend": "postgresql",
        "host_local": True,
        "port": 54329,
        "database": DEMO_DATABASE,
        "database_name_safe": True,
    }
    assert "synthetic" not in repr(summary)

    for unsafe in (
        "sqlite:///sigra_postgresql_demo",
        _postgresql_url("localhost", "sigra_postgresql_demo"),
        _postgresql_url("example.com", "sigra_postgresql_demo"),
        _postgresql_url("127.0.0.1", "sigra_postgresql_test"),
        _postgresql_url("127.0.0.1", "another_demo"),
        _postgresql_url("127.0.0.1", "sigra_postgresql_demo", 54330),
    ):
        with pytest.raises(ValueError):
            validate_demo_database_url(unsafe)


def _catalog_test_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        connection.execute(
            text(
                "INSERT INTO alembic_version (version_num) VALUES ('20260811_0012')"
            )
        )
        connection.execute(
            text(
                """CREATE TABLE sigra_schema_migrations (
                version VARCHAR(40) PRIMARY KEY)"""
            )
        )
        connection.execute(
            text(
                "INSERT INTO sigra_schema_migrations (version) VALUES (:version)"
            ),
            {"version": DEMO_CATALOG_MARKER},
        )
        connection.execute(
            text(
                """CREATE TABLE vehicles (
                id INTEGER PRIMARY KEY,
                brand VARCHAR(80) NOT NULL,
                model VARCHAR(120) NOT NULL,
                year INTEGER NOT NULL,
                vehicle_type VARCHAR(20) NOT NULL)"""
            )
        )
        connection.execute(
            text(
                """CREATE TABLE motorcycles (
                id INTEGER PRIMARY KEY,
                vehicle_type VARCHAR(20) NOT NULL)"""
            )
        )
    return engine


def test_empty_catalog_never_reports_success_even_when_marker_exists():
    engine = _catalog_test_engine()
    try:
        with pytest.raises(ValueError, match=r"count=0, distinct=0"):
            validate_catalog(engine)
    finally:
        engine.dispose()


def test_catalog_bootstrap_refuses_sqlite_without_writing():
    engine = _catalog_test_engine()
    try:
        with pytest.raises(ValueError, match="refuses non-PostgreSQL"):
            bootstrap_demo_catalog(engine)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM vehicles")).scalar_one() == 0
    finally:
        engine.dispose()


def test_catalog_validation_accepts_34_cars_and_ignores_independent_motorcycles():
    engine = _catalog_test_engine()
    canonical = _canonical_catalog_rows()
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """INSERT INTO vehicles (id,brand,model,year,vehicle_type)
                    VALUES (:id,:brand,:model,:year,:vehicle_type)"""
                ),
                [
                    {
                        key: row[key]
                        for key in ("id", "brand", "model", "year", "vehicle_type")
                    }
                    for row in canonical
                ],
            )
            connection.execute(
                text(
                    """INSERT INTO motorcycles (id,vehicle_type)
                    VALUES (:id,'motorcycle')"""
                ),
                [{"id": item} for item in range(101, 106)],
            )
        report = validate_catalog(engine)
        repeated = validate_catalog(engine)
        assert report["automobiles"] == 34
        assert report["distinct_vehicle_ids"] == 34
        assert report["vehicle_ids"] == list(range(1, 35))
        assert repeated == report
        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM motorcycles")).scalar_one() == 5
    finally:
        engine.dispose()


def test_versioned_fipe_cache_is_complete_live_and_read_only():
    rows = _load_fipe_cache()
    assert len(rows) == 34
    assert {int(row["vehicle_id"]) for row in rows} == set(range(1, 35))
    assert {row["retrieval_status"] for row in rows} == {"live"}
    assert all("-" in str(row["year_code"]) for row in rows)


def test_pbev_demo_fixture_preserves_the_audited_matrix_and_provenance():
    parse_result, mappings = build_demo_pbev_fixture(_targets())
    assert parse_result.asset.storage_mode == "metadata_only"
    assert parse_result.asset.document_bytes is None
    assert parse_result.asset.document_metadata["provenance"] == DEMO_PROVENANCE
    assert parse_result.asset.validation_details["official_evidence"] is False
    assert len(parse_result.rows) == 18
    assert all("DEMO_FIXTURE" in row.raw.raw_text for row in parse_result.rows)
    assert all(row.ethanol_city_km_l and row.fossil_city_km_l for row in parse_result.rows)
    assert Counter(item.mapping_status for item in mappings) == {
        MappingStatus.MATCHED: 18,
        MappingStatus.AMBIGUOUS: 6,
        MappingStatus.REJECTED: 3,
        MappingStatus.NOT_FOUND: 3,
        MappingStatus.PENDING: 4,
    }
    assert all(item.evidence["provenance"] == DEMO_PROVENANCE for item in mappings)
    enforce_audited_pilot_baseline(mappings, baseline_applicable=True)


def test_pbev_loader_keeps_official_default_and_allows_explicit_demo_methodology():
    engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    assert PbevLoader(engine).methodology_reference == PBEV_OFFICIAL_METHODOLOGY_REFERENCE
    assert (
        PbevLoader(engine, methodology_reference=PBEV_METHODOLOGY).methodology_reference
        == PBEV_METHODOLOGY
    )
    with pytest.raises(ValueError):
        PbevLoader(engine, methodology_reference=" ")
    with pytest.raises(ValueError):
        PbevLoader(engine, methodology_reference="x" * 121)


def test_anp_demo_fixture_is_offline_explicit_and_matches_integrated_grain(tmp_path):
    page, download, filename = _resolve_demo_anp_source(ANP_SOURCE_REFERENCE)
    assert page.startswith("https://demo.invalid/")
    assert download.startswith("https://demo.invalid/")
    assert "demo-fixture" in filename

    asset = DemoAnpClient().download(
        source_reference=ANP_SOURCE_REFERENCE,
        official_page_url=page,
        download_url=download,
        filename=filename,
        destination_directory=Path(tmp_path),
    )
    parsed = AnpCsvParser().parse(asset)
    assert parsed.asset.source_reference == ANP_SOURCE_REFERENCE
    assert parsed.period_start == parsed.period_end == date(2026, 8, 4)
    assert parsed.period_start - date.resolution * parsed.period_start.weekday() == DEMO_WEEK_START
    assert len(parsed.rows) == 3
    assert {row.payload["Produto"] for row in parsed.rows} == {
        "GASOLINA",
        "GASOLINA ADITIVADA",
        "ETANOL",
    }
    assert all(row.payload["Bandeira"] == "DEMO_FIXTURE" for row in parsed.rows)
    assert all(row.payload["CNPJ da Revenda"] == "" for row in parsed.rows)
    assert DEMO_GEOGRAPHY_KEY == "SP:SAO PAULO"


def test_anp_demo_source_rejects_any_other_reference():
    with pytest.raises(ValueError, match="unknown ANP demo fixture"):
        _resolve_demo_anp_source("anp-last-four-weeks-gasoline-ethanol")


def _activation_candidate(
    dataset_version: str,
    *,
    valid: bool,
    active: bool,
    published_at: datetime,
) -> dict[str, object]:
    return {
        "dataset_version": dataset_version,
        "valid": valid,
        "active": active,
        "published_at": published_at,
        "created_at": published_at,
    }


def test_activation_reconciliation_refuses_when_no_valid_candidate_exists():
    with pytest.raises(ValueError, match="valid complete candidate"):
        _activation_reconciliation_plan(
            (
                _activation_candidate(
                    "invalid-active",
                    valid=False,
                    active=True,
                    published_at=datetime(2026, 8, 1, tzinfo=UTC),
                ),
            )
        )


def test_activation_reconciliation_activates_latest_valid_when_none_is_active():
    candidates = (
        _activation_candidate(
            "valid-old",
            valid=True,
            active=False,
            published_at=datetime(2026, 8, 1, tzinfo=UTC),
        ),
        _activation_candidate(
            "valid-new",
            valid=True,
            active=False,
            published_at=datetime(2026, 8, 2, tzinfo=UTC),
        ),
    )
    plan = _activation_reconciliation_plan(candidates)
    assert plan["canonical_dataset_version"] == "valid-new"
    assert plan["activation_required"] is True
    assert plan["deactivate_dataset_versions"] == ()


def test_activation_reconciliation_retires_only_noncanonical_active_candidates():
    candidates = (
        _activation_candidate(
            "valid-old",
            valid=True,
            active=True,
            published_at=datetime(2026, 8, 1, tzinfo=UTC),
        ),
        _activation_candidate(
            "valid-new",
            valid=True,
            active=True,
            published_at=datetime(2026, 8, 2, tzinfo=UTC),
        ),
        _activation_candidate(
            "history-invalid",
            valid=False,
            active=False,
            published_at=datetime(2026, 8, 3, tzinfo=UTC),
        ),
    )
    plan = _activation_reconciliation_plan(candidates)
    assert plan["canonical_dataset_version"] == "valid-new"
    assert plan["deactivate_dataset_versions"] == ("valid-old",)
    assert plan["preserved_dataset_versions"] == (
        "history-invalid",
        "valid-new",
        "valid-old",
    )


def test_activation_reconciliation_plan_is_idempotent_and_preserves_history():
    candidates = (
        _activation_candidate(
            "valid-active",
            valid=True,
            active=True,
            published_at=datetime(2026, 8, 2, tzinfo=UTC),
        ),
        _activation_candidate(
            "retired-history",
            valid=False,
            active=False,
            published_at=datetime(2026, 8, 1, tzinfo=UTC),
        ),
    )
    first = _activation_reconciliation_plan(candidates)
    second = _activation_reconciliation_plan(candidates)
    assert first == second
    assert first["activation_required"] is False
    assert first["deactivate_dataset_versions"] == ()
    assert first["preserved_dataset_versions"] == (
        "retired-history",
        "valid-active",
    )
