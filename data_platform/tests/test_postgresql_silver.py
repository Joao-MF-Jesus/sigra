from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from data_platform.tests.postgresql_safety import disposable_postgresql_url


POSTGRESQL_URL = disposable_postgresql_url()


def _canonical_hash(payload):
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@pytest.mark.skipif(not POSTGRESQL_URL, reason="PostgreSQL real nao configurado")
def test_postgresql_silver_contract_history_idempotency_and_downgrade(monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.dialects.postgresql import NUMERIC, UUID
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.sql.sqltypes import Boolean, Date

    from data_platform.transformation.loader import SilverLoader
    from data_platform.transformation.pipeline import run_silver_pipeline

    root = Path(__file__).parents[2]
    monkeypatch.setenv("MIGRATION_DATABASE_URL", POSTGRESQL_URL)
    config = Config(str(root / "backend" / "alembic.ini"))

    # Exercita um PostgreSQL inicialmente vazio e toda a cadeia de revisions.
    command.upgrade(config, "head")
    command.downgrade(config, "20260723_0001")
    command.upgrade(config, "head")

    engine = create_engine(POSTGRESQL_URL)
    try:
        database = inspect(engine)
        assert set(database.get_table_names(schema="silver")) == {
            "vehicle_identity",
            "vehicle_source_mapping",
            "vehicle_price_history",
            "pbev_vehicle_mapping",
            "vehicle_efficiency_observation",
            "anp_fuel_price_observation",
        }

        identity_columns = {
            item["name"]: item
            for item in database.get_columns("vehicle_identity", schema="silver")
        }
        mapping_columns = {
            item["name"]: item
            for item in database.get_columns("vehicle_source_mapping", schema="silver")
        }
        price_columns = {
            item["name"]: item
            for item in database.get_columns("vehicle_price_history", schema="silver")
        }
        assert isinstance(identity_columns["is_zero_km"]["type"], Boolean)
        assert identity_columns["model_year"]["nullable"] is True
        assert identity_columns["canonical_key"]["type"].length == 64
        assert isinstance(identity_columns["pipeline_run_id"]["type"], UUID)
        assert mapping_columns["vehicle_sk"]["nullable"] is True
        assert mapping_columns["vehicle_type"]["nullable"] is False
        assert mapping_columns["vehicle_type"]["type"].length == 20
        assert isinstance(mapping_columns["pipeline_run_id"]["type"], UUID)
        assert isinstance(price_columns["price_amount"]["type"], NUMERIC)
        assert price_columns["price_amount"]["type"].precision == 14
        assert price_columns["price_amount"]["type"].scale == 2
        assert isinstance(price_columns["reference_month"]["type"], Date)
        assert isinstance(price_columns["pipeline_run_id"]["type"], UUID)

        identity_checks = {
            item["name"]
            for item in database.get_check_constraints("vehicle_identity", schema="silver")
        }
        mapping_checks = {
            item["name"]
            for item in database.get_check_constraints(
                "vehicle_source_mapping", schema="silver"
            )
        }
        price_checks = {
            item["name"]
            for item in database.get_check_constraints(
                "vehicle_price_history", schema="silver"
            )
        }
        assert {
            "ck_vehicle_identity_year",
            "ck_vehicle_identity_fuel",
            "ck_vehicle_identity_current",
        }.issubset(identity_checks)
        assert {
            "ck_vehicle_source_mapping_status",
            "ck_vehicle_source_mapping_target",
            "ck_vehicle_source_mapping_review_notes",
            "ck_vehicle_source_mapping_vehicle_type",
        }.issubset(mapping_checks)
        assert {
            "ck_vehicle_price_positive",
            "ck_vehicle_price_currency",
            "ck_vehicle_price_reference_month",
            "ck_vehicle_price_current",
        }.issubset(price_checks)

        identity_indexes = {
            item["name"]
            for item in database.get_indexes("vehicle_identity", schema="silver")
        }
        mapping_indexes = {
            item["name"]
            for item in database.get_indexes(
                "vehicle_source_mapping", schema="silver"
            )
        }
        price_indexes = {
            item["name"]
            for item in database.get_indexes("vehicle_price_history", schema="silver")
        }
        quality_indexes = {
            item["name"]
            for item in database.get_indexes("data_quality_issue", schema="meta")
        }
        assert "uq_vehicle_identity_current" in identity_indexes
        assert {
            "uq_vehicle_source_mapping_current_key",
            "uq_vehicle_source_mapping_current_fipe",
        }.issubset(mapping_indexes)
        mapping_index_contracts = {
            item["name"]: item["column_names"]
            for item in database.get_indexes(
                "vehicle_source_mapping", schema="silver"
            )
        }
        assert mapping_index_contracts["uq_vehicle_source_mapping_current_key"] == [
            "source_name",
            "vehicle_type",
            "source_vehicle_key",
        ]
        assert mapping_index_contracts["uq_vehicle_source_mapping_current_fipe"] == [
            "source_name",
            "vehicle_type",
            "fipe_code",
            "year_code",
        ]
        assert "uq_vehicle_price_current" in price_indexes
        assert "uq_data_quality_issue_open_silver" in quality_indexes

        bronze_run_id = uuid4()
        started = datetime(2026, 8, 1, tzinfo=UTC)
        with engine.begin() as connection:
            connection.execute(
                text(
                    """INSERT INTO meta.pipeline_run
                    (pipeline_run_id,pipeline_name,pipeline_version,dataset_version,
                     trigger_type,status,started_at,finished_at,records_received,
                     records_inserted)
                    VALUES (:id,'silver_test_bronze','test','bronze-fixture','manual',
                            'succeeded',:started,:finished,10,10)"""
                ),
                {
                    "id": bronze_run_id,
                    "started": started,
                    "finished": started + timedelta(minutes=1),
                },
            )

        def insert_received(
            payload,
            *,
            code="004517-9",
            year_code="2021-1",
            collected_at,
            marker,
        ):
            full_payload = {**payload, "fixtureMarker": marker}
            payload_hash = _canonical_hash(full_payload)
            with engine.begin() as connection:
                return int(
                    connection.execute(
                        text(
                            """INSERT INTO bronze.fipe_raw
                            (pipeline_run_id,source_name,source_endpoint,vehicle_type,
                             source_record_key,fipe_code,year_code,reference_month_raw,
                             http_status,collected_at,payload,payload_hash,
                             schema_fingerprint,raw_content_length,ingestion_status)
                            VALUES (:run,'Tabela FIPE via API Parallelum','/cars/test',
                                    'car',:source_key,:code,:year_code,:reference,200,
                                    :collected,CAST(:payload AS jsonb),:payload_hash,
                                    :fingerprint,:length,'received')
                            RETURNING fipe_raw_id"""
                        ),
                        {
                            "run": bronze_run_id,
                            "source_key": f"{code}:{year_code}",
                            "code": code,
                            "year_code": year_code,
                            "reference": full_payload.get("referenceMonth"),
                            "collected": collected_at,
                            "payload": json.dumps(full_payload, ensure_ascii=False),
                            "payload_hash": payload_hash,
                            "fingerprint": hashlib.sha256(
                                f"shape:{marker}".encode()
                            ).hexdigest(),
                            "length": len(
                                json.dumps(full_payload, ensure_ascii=False).encode()
                            ),
                        },
                    ).scalar_one()
                )

        base_payload = {
            "brand": "Chevrolet",
            "model": "ONIX HATCH LT 1.0 12V Flex 5p Mec.",
            "modelYear": 2021,
            "fuel": "Flex",
            "fuelAcronym": "F",
            "codeFipe": "004517-9",
        }
        august_id = insert_received(
            {**base_payload, "price": "R$ 80.000,00", "referenceMonth": "agosto de 2026"},
            collected_at=started + timedelta(days=1),
            marker="august",
        )
        october_id = insert_received(
            {**base_payload, "price": "R$ 82.000,00", "referenceMonth": "outubro de 2026"},
            collected_at=started + timedelta(days=2),
            marker="october",
        )
        september_id = insert_received(
            {**base_payload, "price": "R$ 81.000,00", "referenceMonth": "setembro de 2026"},
            collected_at=started + timedelta(days=3),
            marker="september-backfill",
        )
        duplicate_id = insert_received(
            {**base_payload, "price": "R$ 81.000,00", "referenceMonth": "setembro de 2026"},
            collected_at=started + timedelta(days=4),
            marker="september-duplicate",
        )
        conflict_id = insert_received(
            {**base_payload, "price": "R$ 81.500,00", "referenceMonth": "setembro de 2026"},
            collected_at=started + timedelta(days=5),
            marker="september-conflict",
        )
        pending_id = insert_received(
            {
                **base_payload,
                "codeFipe": "004518-7",
                "modelYear": 2022,
                "fuel": None,
                "fuelAcronym": None,
                "price": "R$ 90.000,00",
                "referenceMonth": "agosto de 2026",
            },
            code="004518-7",
            year_code="2022-1",
            collected_at=started + timedelta(days=6),
            marker="pending-fuel",
        )
        ambiguous_id = insert_received(
            {
                **base_payload,
                "codeFipe": "004519-5",
                "modelYear": 2023,
                "fuel": "Gasolina",
                "fuelAcronym": "D",
                "price": "R$ 95.000,00",
                "referenceMonth": "agosto de 2026",
            },
            code="004519-5",
            year_code="2023-1",
            collected_at=started + timedelta(days=7),
            marker="ambiguous-fuel",
        )
        zero_id = insert_received(
            {
                **base_payload,
                "brand": "Marca Zero",
                "model": "Modelo Zero KM",
                "codeFipe": "004520-9",
                "modelYear": 32000,
                "fuel": "Elétrico",
                "fuelAcronym": "E",
                "price": "R$ 120.000,00",
                "referenceMonth": "agosto de 2026",
            },
            code="004520-9",
            year_code="32000-1",
            collected_at=started + timedelta(days=8),
            marker="zero-km",
        )

        with engine.begin() as connection:
            for status, http_status, marker in (
                ("invalid_json", 200, "invalid"),
                ("http_error", 503, "http"),
            ):
                connection.execute(
                    text(
                        """INSERT INTO bronze.fipe_raw
                        (pipeline_run_id,source_name,source_endpoint,vehicle_type,
                         source_record_key,fipe_code,year_code,http_status,collected_at,
                         payload,payload_hash,schema_fingerprint,raw_content_length,
                         ingestion_status)
                        VALUES (:run,'Tabela FIPE via API Parallelum',:endpoint,'car',
                                :source_key,'009999-9','2026-1',:http_status,:collected,
                                NULL,:hash,NULL,10,:status)"""
                    ),
                    {
                        "run": bronze_run_id,
                        "endpoint": f"/cars/{marker}",
                        "source_key": f"009999-9:2026-1:{marker}",
                        "http_status": http_status,
                        "collected": started + timedelta(days=9),
                        "hash": hashlib.sha256(marker.encode()).hexdigest(),
                        "status": status,
                    },
                )

        loader = SilverLoader(engine)
        first = run_silver_pipeline(loader, source_reference="2026-08")
        assert first.status == "partial"
        assert first.records_received == 8
        assert first.records_inserted == 6
        assert first.records_deduplicated == 1
        assert first.records_rejected == 3

        with engine.connect() as connection:
            identities = connection.execute(
                text(
                    """SELECT vehicle_sk,brand_name,model_name,model_year,is_zero_km,
                        version_name,transmission_type,bronze_record_id,
                        pipeline_run_id,created_by_run_id,canonical_key
                    FROM silver.vehicle_identity ORDER BY vehicle_sk"""
                )
            ).mappings().all()
            mappings = connection.execute(
                text(
                    """SELECT mapping_id,vehicle_sk,fipe_code,year_code,
                        mapping_status,review_notes,bronze_record_id,pipeline_run_id
                    FROM silver.vehicle_source_mapping ORDER BY mapping_id"""
                )
            ).mappings().all()
            prices = connection.execute(
                text(
                    """SELECT vehicle_price_id,vehicle_sk,price_amount,currency,
                        reference_month,valid_from,valid_to,is_current,
                        bronze_record_id,pipeline_run_id
                    FROM silver.vehicle_price_history
                    ORDER BY vehicle_sk,reference_month"""
                )
            ).mappings().all()
            issues = connection.execute(
                text(
                    """SELECT rule_code,record_reference,message,details
                    FROM meta.data_quality_issue
                    WHERE layer_name='silver'
                    ORDER BY rule_code,record_reference"""
                )
            ).mappings().all()

        assert len(identities) == 2
        normal_identity = next(item for item in identities if not item["is_zero_km"])
        zero_identity = next(item for item in identities if item["is_zero_km"])
        assert normal_identity["model_year"] == 2021
        assert normal_identity["model_name"] == base_payload["model"]
        assert normal_identity["version_name"] is None
        assert normal_identity["transmission_type"] is None
        assert normal_identity["bronze_record_id"] == august_id
        assert str(normal_identity["pipeline_run_id"]) == first.pipeline_run_id
        assert str(normal_identity["created_by_run_id"]) == first.pipeline_run_id
        assert zero_identity["model_year"] is None
        assert zero_identity["bronze_record_id"] == zero_id
        assert normal_identity["canonical_key"] != zero_identity["canonical_key"]

        assert [item["mapping_status"] for item in mappings] == [
            "matched",
            "pending",
            "ambiguous",
            "matched",
        ]
        assert all(
            (item["vehicle_sk"] is not None) == (item["mapping_status"] == "matched")
            for item in mappings
        )
        assert next(item for item in mappings if item["mapping_status"] == "ambiguous")["review_notes"]
        assert {item["bronze_record_id"] for item in mappings} == {
            august_id,
            pending_id,
            ambiguous_id,
            zero_id,
        }

        normal_prices = [
            item for item in prices if item["vehicle_sk"] == normal_identity["vehicle_sk"]
        ]
        assert [item["reference_month"].isoformat() for item in normal_prices] == [
            "2026-08-01",
            "2026-09-01",
            "2026-10-01",
        ]
        assert [item["price_amount"] for item in normal_prices] == [
            Decimal("80000.00"),
            Decimal("81000.00"),
            Decimal("82000.00"),
        ]
        assert [item["is_current"] for item in normal_prices] == [False, False, True]
        assert normal_prices[0]["valid_to"] == normal_prices[1]["valid_from"]
        assert normal_prices[1]["valid_to"] == normal_prices[2]["valid_from"]
        assert normal_prices[2]["valid_to"] is None
        assert {item["bronze_record_id"] for item in normal_prices} == {
            august_id,
            september_id,
            october_id,
        }
        assert all(str(item["pipeline_run_id"]) == first.pipeline_run_id for item in prices)
        assert duplicate_id not in {item["bronze_record_id"] for item in prices}
        assert conflict_id not in {item["bronze_record_id"] for item in prices}

        issue_codes = {item["rule_code"] for item in issues}
        assert {"UNMAPPED_FUEL", "FUEL_CONFLICT", "PRICE_CONFLICT_SAME_MONTH"}.issubset(
            issue_codes
        )
        assert all("password" not in repr(item).lower() for item in issues)
        assert all("token" not in repr(item).lower() for item in issues)
        assert {
            f"bronze.fipe_raw:{pending_id}",
            f"bronze.fipe_raw:{ambiguous_id}",
            f"bronze.fipe_raw:{conflict_id}",
        }.issubset({item["record_reference"] for item in issues})

        before_counts = (
            len(identities),
            len(mappings),
            len(prices),
            len(issues),
        )
        second = run_silver_pipeline(loader, source_reference="2026-08-retry")
        assert second.status == "partial"
        assert second.records_inserted == 0
        with engine.connect() as connection:
            after_counts = (
                connection.execute(text("SELECT COUNT(*) FROM silver.vehicle_identity")).scalar_one(),
                connection.execute(text("SELECT COUNT(*) FROM silver.vehicle_source_mapping")).scalar_one(),
                connection.execute(text("SELECT COUNT(*) FROM silver.vehicle_price_history")).scalar_one(),
                connection.execute(
                    text("SELECT COUNT(*) FROM meta.data_quality_issue WHERE layer_name='silver'")
                ).scalar_one(),
            )
        assert after_counts == before_counts

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """INSERT INTO silver.vehicle_source_mapping
                        (vehicle_sk,source_name,vehicle_type,source_vehicle_key,
                         fipe_code,year_code,mapping_status,valid_from,
                         pipeline_run_id,bronze_record_id)
                        VALUES (:vehicle,'constraint','car','x','009991-1','2026-1',
                                 'pending',:valid_from,:run,:bronze)"""
                    ),
                    {
                        "vehicle": normal_identity["vehicle_sk"],
                        "valid_from": started + timedelta(days=10),
                        "run": mappings[0]["pipeline_run_id"],
                        "bronze": duplicate_id,
                    },
                )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """INSERT INTO silver.vehicle_source_mapping
                        (vehicle_sk,source_name,vehicle_type,source_vehicle_key,
                         fipe_code,year_code,mapping_status,match_method,confidence,valid_from,
                         pipeline_run_id,bronze_record_id,review_notes)
                        VALUES (NULL,'constraint','car','y','009992-1','2026-1',
                                 'ambiguous',NULL,NULL,:valid_from,:run,:bronze,NULL)"""
                    ),
                    {
                        "valid_from": started + timedelta(days=11),
                        "run": mappings[0]["pipeline_run_id"],
                        "bronze": duplicate_id,
                    },
                )

        with engine.connect() as connection:
            bronze_count = connection.execute(
                text("SELECT COUNT(*) FROM bronze.fipe_raw")
            ).scalar_one()
            run_count = connection.execute(
                text("SELECT COUNT(*) FROM meta.pipeline_run")
            ).scalar_one()
        engine.dispose()
        command.downgrade(config, "20260803_0002")
        engine = create_engine(POSTGRESQL_URL)
        after_downgrade = inspect(engine)
        assert after_downgrade.get_table_names(schema="silver") == []
        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM bronze.fipe_raw")).scalar_one() == bronze_count
            assert connection.execute(text("SELECT COUNT(*) FROM meta.pipeline_run")).scalar_one() == run_count

        engine.dispose()
        command.upgrade(config, "head")
        engine = create_engine(POSTGRESQL_URL)
        assert set(inspect(engine).get_table_names(schema="silver")) == {
            "vehicle_identity",
            "vehicle_source_mapping",
            "vehicle_price_history",
            "pbev_vehicle_mapping",
            "vehicle_efficiency_observation",
            "anp_fuel_price_observation",
        }
        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM silver.vehicle_identity")).scalar_one() == 0
    finally:
        engine.dispose()
        command.downgrade(config, "20260723_0001")
        command.upgrade(config, "head")


@pytest.mark.skipif(not POSTGRESQL_URL, reason="PostgreSQL real nao configurado")
def test_postgresql_pending_to_matched_reprocessing_is_idempotent(monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    from data_platform.transformation.loader import SilverLoader
    from data_platform.transformation.pipeline import run_silver_pipeline

    root = Path(__file__).parents[2]
    monkeypatch.setenv("MIGRATION_DATABASE_URL", POSTGRESQL_URL)
    config = Config(str(root / "backend" / "alembic.ini"))
    command.upgrade(config, "head")
    command.downgrade(config, "20260723_0001")
    command.upgrade(config, "head")

    engine = create_engine(POSTGRESQL_URL)
    pending_collected_at = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    matched_collected_at = pending_collected_at + timedelta(days=1)
    bronze_run_id = uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """INSERT INTO meta.pipeline_run
                    (pipeline_run_id,pipeline_name,pipeline_version,dataset_version,
                     trigger_type,status,started_at,finished_at,records_received,
                     records_inserted)
                    VALUES (:id,'pending_matched_fixture','test','fixture','manual',
                            'succeeded',:started,:finished,2,2)"""
                ),
                {
                    "id": bronze_run_id,
                    "started": pending_collected_at - timedelta(minutes=1),
                    "finished": pending_collected_at,
                },
            )

        def insert_bronze(payload, collected_at, marker):
            full_payload = {**payload, "fixtureMarker": marker}
            serialized = json.dumps(full_payload, ensure_ascii=False)
            with engine.begin() as connection:
                return int(
                    connection.execute(
                        text(
                            """INSERT INTO bronze.fipe_raw
                            (pipeline_run_id,source_name,source_endpoint,vehicle_type,
                             source_record_key,fipe_code,year_code,reference_month_raw,
                             http_status,collected_at,payload,payload_hash,
                             schema_fingerprint,raw_content_length,ingestion_status)
                            VALUES (:run,'Tabela FIPE via API Parallelum',
                                    '/cars/pending-matched','car',
                                    '004517-9:2021-1','004517-9','2021-1',
                                    'agosto de 2026',200,:collected,
                                    CAST(:payload AS jsonb),:payload_hash,
                                    :fingerprint,:length,'received')
                            RETURNING fipe_raw_id"""
                        ),
                        {
                            "run": bronze_run_id,
                            "collected": collected_at,
                            "payload": serialized,
                            "payload_hash": _canonical_hash(full_payload),
                            "fingerprint": hashlib.sha256(
                                f"pending-matched:{marker}".encode()
                            ).hexdigest(),
                            "length": len(serialized.encode()),
                        },
                    ).scalar_one()
                )

        common = {
            "brand": "Chevrolet",
            "model": "ONIX HATCH LT 1.0 12V Flex 5p Mec.",
            "modelYear": 2021,
            "codeFipe": "004517-9",
            "price": "R$ 80.000,00",
            "referenceMonth": "agosto de 2026",
        }
        pending_bronze_id = insert_bronze(
            {**common, "fuel": None, "fuelAcronym": None},
            pending_collected_at,
            "pending",
        )
        matched_bronze_id = insert_bronze(
            {**common, "fuel": "Flex", "fuelAcronym": "F"},
            matched_collected_at,
            "matched",
        )

        loader = SilverLoader(engine)
        first = run_silver_pipeline(loader, source_reference="pending-matched")
        assert first.status == "partial"
        assert first.records_received == 2
        assert first.records_inserted == 2
        assert first.records_rejected == 1

        with engine.connect() as connection:
            first_mappings = connection.execute(
                text(
                    """SELECT mapping_id,vehicle_sk,mapping_status,valid_from,
                        valid_to,bronze_record_id
                    FROM silver.vehicle_source_mapping
                    ORDER BY valid_from,mapping_id"""
                )
            ).mappings().all()
            first_counts = {
                "identity": connection.execute(
                    text("SELECT COUNT(*) FROM silver.vehicle_identity")
                ).scalar_one(),
                "mapping": connection.execute(
                    text("SELECT COUNT(*) FROM silver.vehicle_source_mapping")
                ).scalar_one(),
                "price": connection.execute(
                    text("SELECT COUNT(*) FROM silver.vehicle_price_history")
                ).scalar_one(),
                "issue": connection.execute(
                    text(
                        "SELECT COUNT(*) FROM meta.data_quality_issue "
                        "WHERE layer_name='silver'"
                    )
                ).scalar_one(),
            }
            price_mapping_id = connection.execute(
                text("SELECT source_mapping_id FROM silver.vehicle_price_history")
            ).scalar_one()

        assert first_counts == {"identity": 1, "mapping": 2, "price": 1, "issue": 1}
        pending_mapping, matched_mapping = first_mappings
        assert pending_mapping["mapping_status"] == "pending"
        assert pending_mapping["vehicle_sk"] is None
        assert pending_mapping["bronze_record_id"] == pending_bronze_id
        assert pending_mapping["valid_to"] == matched_collected_at
        assert matched_mapping["mapping_status"] == "matched"
        assert matched_mapping["vehicle_sk"] is not None
        assert matched_mapping["bronze_record_id"] == matched_bronze_id
        assert matched_mapping["valid_to"] is None
        assert price_mapping_id == matched_mapping["mapping_id"]
        assert sum(item["valid_to"] is None for item in first_mappings) == 1

        second = run_silver_pipeline(loader, source_reference="pending-matched-retry")
        assert second.status == "succeeded"
        assert second.records_received == 2
        assert second.records_inserted == 0
        assert second.records_deduplicated == 2
        assert second.records_rejected == 0

        with engine.connect() as connection:
            second_mappings = connection.execute(
                text(
                    """SELECT mapping_id,vehicle_sk,mapping_status,valid_from,
                        valid_to,bronze_record_id
                    FROM silver.vehicle_source_mapping
                    ORDER BY valid_from,mapping_id"""
                )
            ).mappings().all()
            second_counts = {
                "identity": connection.execute(
                    text("SELECT COUNT(*) FROM silver.vehicle_identity")
                ).scalar_one(),
                "mapping": connection.execute(
                    text("SELECT COUNT(*) FROM silver.vehicle_source_mapping")
                ).scalar_one(),
                "price": connection.execute(
                    text("SELECT COUNT(*) FROM silver.vehicle_price_history")
                ).scalar_one(),
                "issue": connection.execute(
                    text(
                        "SELECT COUNT(*) FROM meta.data_quality_issue "
                        "WHERE layer_name='silver'"
                    )
                ).scalar_one(),
            }
            false_conflicts = connection.execute(
                text(
                    """SELECT COUNT(*) FROM meta.data_quality_issue
                    WHERE layer_name='silver'
                      AND rule_code IN (
                          'SOURCE_MAPPING_CONFLICT',
                          'SOURCE_MAPPING_NON_MONOTONIC'
                      )"""
                )
            ).scalar_one()

        assert second_counts == first_counts
        assert second_mappings == first_mappings
        assert false_conflicts == 0
        assert second_mappings[0]["valid_to"] == matched_collected_at
        assert second_mappings[1]["valid_to"] is None
    finally:
        engine.dispose()
        command.downgrade(config, "20260723_0001")
        command.upgrade(config, "head")
