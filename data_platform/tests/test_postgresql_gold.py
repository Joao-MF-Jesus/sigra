from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest


POSTGRESQL_URL = os.getenv("DATA_PLATFORM_TEST_POSTGRESQL_URL")
SOURCE_NAME = "Tabela FIPE via API Parallelum"


def _config(monkeypatch):
    from alembic.config import Config

    root = Path(__file__).parents[2]
    monkeypatch.setenv("MIGRATION_DATABASE_URL", POSTGRESQL_URL)
    return Config(str(root / "backend" / "alembic.ini"))


def _reset_database(config):
    from alembic import command

    command.upgrade(config, "head")
    command.downgrade(config, "20260723_0001")
    command.upgrade(config, "head")


def _insert_run(connection, *, name: str = "postgresql_gold_fixture") -> UUID:
    from sqlalchemy import text

    run_id = uuid4()
    started = datetime(2026, 8, 1, tzinfo=UTC)
    connection.execute(
        text(
            """INSERT INTO meta.pipeline_run
            (pipeline_run_id,pipeline_name,pipeline_version,dataset_version,
             trigger_type,status,started_at,finished_at)
            VALUES (:run,:name,'fixture-v1',:dataset,'manual','succeeded',
                    :started,:started)"""
        ),
        {
            "run": run_id,
            "name": name,
            "dataset": f"fixture-{run_id}",
            "started": started,
        },
    )
    return run_id


def _insert_bronze(
    connection,
    run_id: UUID,
    *,
    ordinal: int,
    vehicle_type: str,
    fipe_code: str,
    year_code: str,
    collected_at: datetime,
    source_record_key: str | None = None,
) -> int:
    from sqlalchemy import text

    payload = {
        "brand": f"Brand {ordinal}",
        "model": f"Model {ordinal}",
        "fuel": "Gasolina",
        "fuelAcronym": "G",
        "modelYear": 2021,
        "codeFipe": fipe_code,
        "referenceMonth": "agosto de 2026",
        "price": "R$ 80.000,00",
    }
    raw = json.dumps(payload, sort_keys=True).encode()
    return int(
        connection.execute(
            text(
                """INSERT INTO bronze.fipe_raw
                (pipeline_run_id,source_name,source_endpoint,vehicle_type,
                 source_record_key,fipe_code,year_code,reference_month_raw,
                 http_status,collected_at,payload,payload_hash,schema_fingerprint,
                 raw_content_length,ingestion_status)
                VALUES (:run,:source,:endpoint,:vehicle_type,:source_key,
                        :fipe,:year,'agosto de 2026',200,:collected,
                        CAST(:payload AS jsonb),:payload_hash,:schema_hash,
                        :length,'received')
                RETURNING fipe_raw_id"""
            ),
            {
                "run": run_id,
                "source": SOURCE_NAME,
                "endpoint": f"/test/gold/{vehicle_type}/{ordinal}",
                "vehicle_type": vehicle_type,
                "source_key": source_record_key or f"{fipe_code}:{year_code}",
                "fipe": fipe_code,
                "year": year_code,
                "collected": collected_at,
                "payload": raw.decode(),
                "payload_hash": sha256(
                    raw + str(ordinal).encode() + collected_at.isoformat().encode()
                ).hexdigest(),
                "schema_hash": sha256(b"gold-fixture-schema").hexdigest(),
                "length": len(raw),
            },
        ).scalar_one()
    )


def _insert_mapping_0003(
    connection,
    run_id: UUID,
    bronze_id: int,
    *,
    source_key: str,
    fipe_code: str,
    year_code: str,
    status: str,
    valid_from: datetime,
) -> int:
    from sqlalchemy import text

    return int(
        connection.execute(
            text(
                """INSERT INTO silver.vehicle_source_mapping
                (vehicle_sk,source_name,source_vehicle_key,fipe_code,year_code,
                 mapping_status,valid_from,pipeline_run_id,bronze_record_id,
                 review_notes)
                VALUES (NULL,:source,:source_key,:fipe,:year,:status,:valid_from,
                        :run,:bronze,:notes)
                RETURNING mapping_id"""
            ),
            {
                "source": SOURCE_NAME,
                "source_key": source_key,
                "fipe": fipe_code,
                "year": year_code,
                "status": status,
                "valid_from": valid_from,
                "run": run_id,
                "bronze": bronze_id,
                "notes": "Raw key requires review" if status == "ambiguous" else None,
            },
        ).scalar_one()
    )


def _insert_gold_scope_mapping(
    connection,
    run_id: UUID,
    *,
    ordinal: int,
    matched: bool,
    reference_month: date | None = None,
    collected_at: datetime | None = None,
) -> tuple[int, int | None, int]:
    from sqlalchemy import text

    fipe_code = f"{ordinal:06d}-1"
    year_code = "2021-1"
    collected = collected_at or datetime(2026, 8, 2, tzinfo=UTC)
    bronze_id = _insert_bronze(
        connection,
        run_id,
        ordinal=ordinal,
        vehicle_type="car",
        fipe_code=fipe_code,
        year_code=year_code,
        collected_at=collected,
    )
    vehicle_sk = None
    if matched:
        vehicle_sk = int(
            connection.execute(
                text(
                    """INSERT INTO silver.vehicle_identity
                    (vehicle_type,brand_name,model_name,model_year,is_zero_km,
                     fuel_type,canonical_key,valid_from,is_current,bronze_record_id,
                     pipeline_run_id,created_by_run_id,updated_by_run_id)
                    VALUES ('car',:brand,:model,2021,FALSE,'gasoline',:canonical,
                            :valid_from,TRUE,:bronze,:run,:run,:run)
                    RETURNING vehicle_sk"""
                ),
                {
                    "brand": f"Brand {ordinal}",
                    "model": f"Model {ordinal}",
                    "canonical": sha256(f"car-{ordinal}".encode()).hexdigest(),
                    "valid_from": collected,
                    "bronze": bronze_id,
                    "run": run_id,
                },
            ).scalar_one()
        )
    mapping_id = int(
        connection.execute(
            text(
                """INSERT INTO silver.vehicle_source_mapping
                (vehicle_sk,source_name,vehicle_type,source_vehicle_key,
                 fipe_code,year_code,mapping_status,match_method,confidence,
                 valid_from,pipeline_run_id,bronze_record_id)
                VALUES (:vehicle,:source,'car',:source_key,:fipe,:year,:status,
                        :method,:confidence,:valid_from,:run,:bronze)
                RETURNING mapping_id"""
            ),
            {
                "vehicle": vehicle_sk,
                "source": SOURCE_NAME,
                "source_key": f"{fipe_code}:{year_code}",
                "fipe": fipe_code,
                "year": year_code,
                "status": "matched" if matched else "pending",
                "method": "exact" if matched else None,
                "confidence": 100 if matched else None,
                "valid_from": collected,
                "run": run_id,
                "bronze": bronze_id,
            },
        ).scalar_one()
    )
    if matched:
        connection.execute(
            text(
                """INSERT INTO silver.vehicle_price_history
                (vehicle_sk,source_name,source_mapping_id,price_amount,currency,
                 reference_month,collected_at,valid_from,is_current,
                 data_confidence,bronze_record_id,pipeline_run_id)
                VALUES (:vehicle,:source,:mapping,:price,'BRL',:reference,
                        :collected,:valid_from,TRUE,100,:bronze,:run)"""
            ),
            {
                "vehicle": vehicle_sk,
                "source": SOURCE_NAME,
                "mapping": mapping_id,
                "price": f"{80000 + ordinal}.00",
                "reference": reference_month or date(2026, 8, 1),
                "collected": collected,
                "valid_from": datetime.combine(
                    reference_month or date(2026, 8, 1),
                    datetime.min.time(),
                    tzinfo=UTC,
                ),
                "bronze": bronze_id,
                "run": run_id,
            },
        )
    return mapping_id, vehicle_sk, bronze_id


@pytest.mark.skipif(not POSTGRESQL_URL, reason="PostgreSQL real nao configurado")
def test_gold_migration_backfill_constraints_and_safe_downgrade(monkeypatch):
    from alembic import command
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.exc import DBAPIError, IntegrityError

    config = _config(monkeypatch)
    expected_head = ScriptDirectory.from_config(config).get_current_head()
    assert expected_head is not None
    command.upgrade(config, "head")
    command.downgrade(config, "20260723_0001")
    command.upgrade(config, "20260803_0003")
    engine = create_engine(POSTGRESQL_URL)
    collision_mapping_id = None
    collision_bronze_id = None
    try:
        collected = datetime(2026, 8, 1, tzinfo=UTC)
        with engine.begin() as connection:
            run_id = _insert_run(connection)
            expected = []
            for ordinal, vehicle_type, status in (
                (1, "car", "pending"),
                (2, "motorcycle", "pending"),
                (3, "truck", "ambiguous"),
            ):
                fipe_code = f"00000{ordinal}-1"
                year_code = "2021-1"
                bronze_id = _insert_bronze(
                    connection,
                    run_id,
                    ordinal=ordinal,
                    vehicle_type=vehicle_type,
                    fipe_code=fipe_code,
                    year_code=year_code,
                    collected_at=collected + timedelta(minutes=ordinal),
                    source_record_key=(
                        "raw-conflicting-key" if status == "ambiguous" else None
                    ),
                )
                mapping_id = _insert_mapping_0003(
                    connection,
                    run_id,
                    bronze_id,
                    source_key=f"{fipe_code}:{year_code}",
                    fipe_code=fipe_code,
                    year_code=year_code,
                    status=status,
                    valid_from=collected + timedelta(minutes=ordinal),
                )
                expected.append((mapping_id, vehicle_type, status))

            connection.execute(
                text(
                    """UPDATE silver.vehicle_source_mapping
                    SET source_name='Invalid lineage source'
                    WHERE mapping_id=:mapping"""
                ),
                {"mapping": expected[0][0]},
            )

        engine.dispose()
        with pytest.raises((DBAPIError, RuntimeError)):
            command.upgrade(config, "head")
        engine = create_engine(POSTGRESQL_URL)
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == "20260803_0003"
            columns = {
                item["name"]
                for item in inspect(connection).get_columns(
                    "vehicle_source_mapping", schema="silver"
                )
            }
            assert "vehicle_type" not in columns
        with engine.begin() as connection:
            connection.execute(
                text(
                    """UPDATE silver.vehicle_source_mapping
                    SET source_name=:source WHERE mapping_id=:mapping"""
                ),
                {"source": SOURCE_NAME, "mapping": expected[0][0]},
            )
        engine.dispose()
        command.upgrade(config, "head")
        engine = create_engine(POSTGRESQL_URL)
        database = inspect(engine)
        mapping_columns = {
            item["name"]: item
            for item in database.get_columns("vehicle_source_mapping", schema="silver")
        }
        assert mapping_columns["vehicle_type"]["nullable"] is False
        checks = {
            item["name"]
            for item in database.get_check_constraints(
                "vehicle_source_mapping", schema="silver"
            )
        }
        assert "ck_vehicle_source_mapping_vehicle_type" in checks
        indexes = {
            item["name"]: item["column_names"]
            for item in database.get_indexes(
                "vehicle_source_mapping", schema="silver"
            )
        }
        assert indexes["uq_vehicle_source_mapping_current_key"] == [
            "source_name",
            "vehicle_type",
            "source_vehicle_key",
        ]
        assert set(database.get_table_names(schema="gold")) == {
            "vehicle_feature_dataset",
            "vehicle_features_snapshot",
            "vehicle_feature_dataset_activation",
        }
        assert "vehicle_features_current" in database.get_view_names(schema="gold")

        with engine.connect() as connection:
            activation_fk = connection.execute(
                text(
                    """SELECT constraint_row.condeferrable,
                              constraint_row.condeferred
                    FROM pg_constraint AS constraint_row
                    JOIN pg_namespace AS namespace_row
                      ON namespace_row.oid = constraint_row.connamespace
                    WHERE namespace_row.nspname = 'gold'
                      AND constraint_row.conname =
                          'fk_gold_dataset_last_activation'"""
                )
            ).mappings().one()
        assert activation_fk == {
            "condeferrable": True,
            "condeferred": True,
        }

        with engine.begin() as connection:
            actual = connection.execute(
                text(
                    """SELECT mapping_id,vehicle_type,mapping_status
                    FROM silver.vehicle_source_mapping ORDER BY mapping_id"""
                )
            ).all()
            assert [tuple(row) for row in actual] == expected
            run_id = UUID(str(connection.execute(text(
                "SELECT pipeline_run_id FROM meta.pipeline_run LIMIT 1"
            )).scalar_one()))
            existing = connection.execute(
                text(
                    """SELECT fipe_code,year_code,source_vehicle_key,valid_from
                    FROM silver.vehicle_source_mapping
                    WHERE vehicle_type='car'"""
                )
            ).mappings().one()
            collision_bronze_id = _insert_bronze(
                connection,
                run_id,
                ordinal=99,
                vehicle_type="motorcycle",
                fipe_code=existing["fipe_code"],
                year_code=existing["year_code"],
                collected_at=existing["valid_from"],
            )
            collision_mapping_id = int(
                connection.execute(
                    text(
                        """INSERT INTO silver.vehicle_source_mapping
                        (vehicle_sk,source_name,vehicle_type,source_vehicle_key,
                         fipe_code,year_code,mapping_status,valid_from,
                         pipeline_run_id,bronze_record_id)
                        VALUES (NULL,:source,'motorcycle',:source_key,:fipe,:year,
                                'pending',:valid_from,:run,:bronze)
                        RETURNING mapping_id"""
                    ),
                    {
                        "source": SOURCE_NAME,
                        "source_key": existing["source_vehicle_key"],
                        "fipe": existing["fipe_code"],
                        "year": existing["year_code"],
                        "valid_from": existing["valid_from"],
                        "run": run_id,
                        "bronze": collision_bronze_id,
                    },
                ).scalar_one()
            )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """UPDATE silver.vehicle_source_mapping
                        SET vehicle_type='boat'
                        WHERE mapping_id=:mapping"""
                    ),
                    {"mapping": collision_mapping_id},
                )

        try:
            engine.dispose()
            with pytest.raises((DBAPIError, RuntimeError)):
                command.downgrade(config, "20260803_0003")
            engine = create_engine(POSTGRESQL_URL)
            with engine.connect() as connection:
                assert connection.execute(
                    text(
                        "SELECT COUNT(*) FROM silver.vehicle_source_mapping "
                        "WHERE mapping_id=:mapping"
                    ),
                    {"mapping": collision_mapping_id},
                ).scalar_one() == 1
                assert connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one() == expected_head
        finally:
            engine.dispose()
            cleanup_engine = create_engine(POSTGRESQL_URL)
            try:
                with cleanup_engine.begin() as connection:
                    connection.execute(
                        text(
                            "DELETE FROM silver.vehicle_source_mapping "
                            "WHERE mapping_id=:mapping "
                            "AND bronze_record_id=:bronze"
                        ),
                        {
                            "mapping": collision_mapping_id,
                            "bronze": collision_bronze_id,
                        },
                    )
                    connection.execute(
                        text(
                            "DELETE FROM bronze.fipe_raw "
                            "WHERE fipe_raw_id=:bronze"
                        ),
                        {"bronze": collision_bronze_id},
                    )
            finally:
                cleanup_engine.dispose()
            command.upgrade(config, "head")

        command.downgrade(config, "20260803_0003")
        engine = create_engine(POSTGRESQL_URL)
        downgraded = inspect(engine)
        assert "vehicle_type" not in {
            item["name"]
            for item in downgraded.get_columns(
                "vehicle_source_mapping", schema="silver"
            )
        }
        assert downgraded.get_table_names(schema="gold") == []
        engine.dispose()
        command.upgrade(config, "head")
    finally:
        engine.dispose()


@pytest.mark.skipif(not POSTGRESQL_URL, reason="PostgreSQL real nao configurado")
def test_gold_exact_coverage_idempotency_replacement_and_rollback(monkeypatch):
    from sqlalchemy import create_engine, text

    from data_platform.publication.loader import GoldLoader
    from data_platform.publication.pipeline import rollback_gold_dataset, run_gold_publication

    config = _config(monkeypatch)
    _reset_database(config)
    engine = create_engine(POSTGRESQL_URL)
    try:
        with engine.begin() as connection:
            silver_run = _insert_run(connection)
            for ordinal in range(1, 6):
                _insert_gold_scope_mapping(
                    connection,
                    silver_run,
                    ordinal=ordinal,
                    matched=ordinal <= 4,
                    reference_month=(date(2020, 1, 1) if ordinal == 1 else None),
                    collected_at=(
                        datetime(2020, 1, 2, tzinfo=UTC)
                        if ordinal == 1
                        else None
                    ),
                )

        loader = GoldLoader(engine)
        first = run_gold_publication(loader, source_reference="exact-80")
        assert first.status == "succeeded"
        assert first.coverage_percentage == 80
        second = run_gold_publication(loader, source_reference="same-silver")
        assert second.status == "deduplicated"
        assert second.dataset_version == first.dataset_version

        with engine.connect() as connection:
            assert connection.execute(text(
                "SELECT COUNT(*) FROM gold.vehicle_feature_dataset"
            )).scalar_one() == 1
            assert connection.execute(text(
                "SELECT COUNT(*) FROM gold.vehicle_feature_dataset_activation"
            )).scalar_one() == 1
            expired = connection.execute(text(
                """SELECT base_quality_status,freshness_status,quality_status
                FROM gold.vehicle_features_current
                WHERE price_reference_month='2020-01-01'"""
            )).mappings().one()
            assert expired == {
                "base_quality_status": "passed",
                "freshness_status": "expired",
                "quality_status": "warning",
            }

        with engine.begin() as connection:
            pending = connection.execute(
                text(
                    """SELECT mapping_id,fipe_code,year_code,valid_from
                    FROM silver.vehicle_source_mapping
                    WHERE mapping_status='pending' AND valid_to IS NULL"""
                )
            ).mappings().one()
            matched_at = pending["valid_from"] + timedelta(days=1)
            connection.execute(
                text(
                    """UPDATE silver.vehicle_source_mapping
                    SET valid_to=:valid_to WHERE mapping_id=:mapping"""
                ),
                {"valid_to": matched_at, "mapping": pending["mapping_id"]},
            )
            _insert_gold_scope_mapping(
                connection,
                silver_run,
                ordinal=5,
                matched=True,
                collected_at=matched_at,
            )
            connection.execute(
                text(
                    """INSERT INTO meta.data_quality_issue
                    (pipeline_run_id,layer_name,entity_name,record_reference,
                     rule_code,severity,message,details,resolution_status,resolved_at)
                    VALUES (:run,'silver','bronze.fipe_raw','bronze.fipe_raw:accepted',
                            'ACCEPTED_FIXTURE','critical','accepted fixture','{}',
                            'accepted',CURRENT_TIMESTAMP),
                           (:run,'silver','bronze.fipe_raw','bronze.fipe_raw:resolved',
                            'RESOLVED_FIXTURE','critical','resolved fixture','{}',
                            'resolved',CURRENT_TIMESTAMP)"""
                ),
                {"run": silver_run},
            )

        replacement = run_gold_publication(loader, source_reference="replacement")
        assert replacement.status == "succeeded"
        assert replacement.published_count == 5
        assert replacement.coverage_percentage == 100
        assert replacement.dataset_version != first.dataset_version
        with engine.connect() as connection:
            assert connection.execute(text(
                "SELECT COUNT(*) FROM gold.vehicle_feature_dataset_activation"
            )).scalar_one() == 2
            assert connection.execute(
                text(
                    """SELECT COUNT(*) FROM gold.vehicle_features_current
                    WHERE base_quality_status='warning'"""
                )
            ).scalar_one() == 5
            snapshots_before_rejected_rollback = connection.execute(
                text(
                    """SELECT row_to_json(snapshot_row)::text
                    FROM gold.vehicle_features_snapshot AS snapshot_row
                    ORDER BY dataset_version,vehicle_sk"""
                )
            ).scalars().all()
            datasets_before_rejected_rollback = [
                dict(row)
                for row in connection.execute(
                    text(
                        """SELECT dataset_version,status,is_active,published_at,
                                  retired_at,last_activation_event_id,
                                  activation_run_id
                        FROM gold.vehicle_feature_dataset
                        ORDER BY dataset_version"""
                    )
                ).mappings().all()
            ]

        rollback = rollback_gold_dataset(loader, first.dataset_version)
        assert rollback.status == "rejected"
        assert rollback.errors == ("GOLD_ROLLBACK_QUALITY_MISMATCH",)
        assert rollback.coverage_percentage == 80
        with engine.connect() as connection:
            active = connection.execute(text(
                "SELECT dataset_version FROM gold.vehicle_feature_dataset WHERE is_active"
            )).scalar_one()
            assert active == replacement.dataset_version
            assert connection.execute(text(
                "SELECT COUNT(*) FROM gold.vehicle_feature_dataset_activation"
            )).scalar_one() == 2
            snapshots_after_rejected_rollback = connection.execute(
                text(
                    """SELECT row_to_json(snapshot_row)::text
                    FROM gold.vehicle_features_snapshot AS snapshot_row
                    ORDER BY dataset_version,vehicle_sk"""
                )
            ).scalars().all()
            assert snapshots_after_rejected_rollback == snapshots_before_rejected_rollback
            datasets_after_rejected_rollback = [
                dict(row)
                for row in connection.execute(
                    text(
                        """SELECT dataset_version,status,is_active,published_at,
                                  retired_at,last_activation_event_id,
                                  activation_run_id
                        FROM gold.vehicle_feature_dataset
                        ORDER BY dataset_version"""
                    )
                ).mappings().all()
            ]
            assert datasets_after_rejected_rollback == datasets_before_rejected_rollback
            events = connection.execute(text(
                """SELECT activation_type FROM gold.vehicle_feature_dataset_activation
                ORDER BY activation_event_id"""
            )).scalars().all()
            assert events == ["initial", "replacement"]
            rejected_run = connection.execute(
                text(
                    """SELECT status,error_summary
                    FROM meta.pipeline_run
                    WHERE pipeline_run_id=:run"""
                ),
                {"run": UUID(rollback.pipeline_run_id)},
            ).mappings().one()
            assert rejected_run["status"] == "rejected"
            assert "GOLD_ROLLBACK_QUALITY_MISMATCH" in rejected_run["error_summary"]
            assert connection.execute(
                text(
                    """SELECT COUNT(*) FROM meta.data_quality_issue
                    WHERE pipeline_run_id=:run
                      AND layer_name='gold'
                      AND rule_code='GOLD_ROLLBACK_QUALITY_MISMATCH'
                      AND resolution_status='open'"""
                ),
                {"run": UUID(rollback.pipeline_run_id)},
            ).scalar_one() == 1

        with engine.begin() as connection:
            resolved = connection.execute(
                text(
                    """UPDATE meta.data_quality_issue
                    SET resolution_status='resolved',resolved_at=CURRENT_TIMESTAMP
                    WHERE rule_code='ACCEPTED_FIXTURE'
                      AND resolution_status='accepted'"""
                )
            )
            assert resolved.rowcount == 1

        successful_rollback = rollback_gold_dataset(loader, first.dataset_version)
        assert successful_rollback.status == "succeeded"
        assert successful_rollback.coverage_percentage == 80
        with engine.connect() as connection:
            assert connection.execute(text(
                "SELECT dataset_version FROM gold.vehicle_feature_dataset WHERE is_active"
            )).scalar_one() == first.dataset_version
            assert connection.execute(text(
                "SELECT COUNT(*) FROM gold.vehicle_feature_dataset_activation"
            )).scalar_one() == 3
            assert connection.execute(
                text(
                    """SELECT COUNT(*) FROM gold.vehicle_feature_dataset_activation
                    WHERE activation_type='rollback'"""
                )
            ).scalar_one() == 1
            assert connection.execute(
                text(
                    """SELECT row_to_json(snapshot_row)::text
                    FROM gold.vehicle_features_snapshot AS snapshot_row
                    ORDER BY dataset_version,vehicle_sk"""
                )
            ).scalars().all() == snapshots_before_rejected_rollback
    finally:
        engine.dispose()


@pytest.mark.skipif(not POSTGRESQL_URL, reason="PostgreSQL real nao configurado")
def test_gold_rejection_atomic_failure_and_concurrency(monkeypatch):
    from sqlalchemy import create_engine, text

    from data_platform.publication.loader import GoldLoader
    from data_platform.publication.pipeline import GoldPublicationError, run_gold_publication

    config = _config(monkeypatch)
    _reset_database(config)
    engine = create_engine(POSTGRESQL_URL)
    try:
        empty = run_gold_publication(GoldLoader(engine), source_reference="empty")
        assert empty.status == "rejected"
        with engine.connect() as connection:
            assert connection.execute(text(
                "SELECT COUNT(*) FROM gold.vehicle_feature_dataset"
            )).scalar_one() == 0

        with engine.begin() as connection:
            silver_run = _insert_run(connection)
            for ordinal in range(1, 6):
                _insert_gold_scope_mapping(
                    connection,
                    silver_run,
                    ordinal=ordinal,
                    matched=ordinal <= 3,
                )
        below = run_gold_publication(GoldLoader(engine), source_reference="below-80")
        assert below.status == "rejected"
        assert below.coverage_percentage == 60
        with engine.connect() as connection:
            assert connection.execute(text(
                "SELECT COUNT(*) FROM gold.vehicle_feature_dataset"
            )).scalar_one() == 0

        with engine.begin() as connection:
            pending = connection.execute(
                text(
                    """SELECT mapping_id,valid_from
                    FROM silver.vehicle_source_mapping
                    WHERE mapping_status='pending' AND valid_to IS NULL
                    ORDER BY mapping_id LIMIT 1"""
                )
            ).mappings().one()
            matched_at = pending["valid_from"] + timedelta(days=1)
            connection.execute(
                text(
                    "UPDATE silver.vehicle_source_mapping SET valid_to=:closed WHERE mapping_id=:mapping"
                ),
                {"closed": matched_at, "mapping": pending["mapping_id"]},
            )
            ordinal = 4
            _insert_gold_scope_mapping(
                connection,
                silver_run,
                ordinal=ordinal,
                matched=True,
                collected_at=matched_at,
            )
            connection.execute(
                text(
                    """INSERT INTO meta.data_quality_issue
                    (pipeline_run_id,layer_name,entity_name,record_reference,
                     rule_code,severity,message,details,resolution_status)
                    VALUES (:run,'silver','bronze.fipe_raw','bronze.fipe_raw:critical',
                            'GLOBAL_CRITICAL','critical','safe global issue','{}','open')"""
                ),
                {"run": silver_run},
            )
        blocked = run_gold_publication(GoldLoader(engine), source_reference="global-critical")
        assert blocked.status == "rejected"
        with engine.begin() as connection:
            connection.execute(
                text(
                    """UPDATE meta.data_quality_issue
                    SET resolution_status='resolved',resolved_at=CURRENT_TIMESTAMP
                    WHERE rule_code='GLOBAL_CRITICAL'"""
                )
            )

        failing_loader = GoldLoader(engine)

        def fail_activation(*args, **kwargs):
            raise RuntimeError(
                "password=must-not-leak connection failed for "
                "postgresql+psycopg://synthetic-user:synthetic-secret@"
                "localhost:5432/sigra"
            )

        monkeypatch.setattr(failing_loader, "activate_dataset", fail_activation)
        with pytest.raises(GoldPublicationError) as failure:
            run_gold_publication(failing_loader, source_reference="atomic-failure")
        for secret in ("must-not-leak", "synthetic-user", "synthetic-secret"):
            assert secret not in str(failure.value)
        with engine.connect() as connection:
            assert connection.execute(text(
                "SELECT COUNT(*) FROM gold.vehicle_feature_dataset"
            )).scalar_one() == 0
            failed_run = connection.execute(
                text(
                    """SELECT status,error_summary FROM meta.pipeline_run
                    WHERE source_reference='atomic-failure'"""
                )
            ).mappings().one()
            assert failed_run["status"] == "failed"
            for secret in ("must-not-leak", "synthetic-user", "synthetic-secret"):
                assert secret not in failed_run["error_summary"]
            assert "localhost:5432/sigra" in failed_run["error_summary"]

        monkeypatch.undo()

        def publish_once(reference):
            return run_gold_publication(
                GoldLoader(engine), source_reference=reference
            ).status

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = set(
                executor.map(publish_once, ("concurrent-a", "concurrent-b"))
            )
        assert statuses == {"succeeded", "deduplicated"}
        with engine.connect() as connection:
            assert connection.execute(text(
                "SELECT COUNT(*) FROM gold.vehicle_feature_dataset"
            )).scalar_one() == 1
            assert connection.execute(text(
                "SELECT COUNT(*) FROM gold.vehicle_feature_dataset_activation"
            )).scalar_one() == 1
            issue_details = connection.execute(
                text(
                    """SELECT details::text FROM meta.data_quality_issue
                    WHERE layer_name='gold'"""
                )
            ).scalars().all()
            assert "password" not in repr(issue_details).lower()
    finally:
        engine.dispose()
