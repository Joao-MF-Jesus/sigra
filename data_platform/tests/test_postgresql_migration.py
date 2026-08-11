from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from uuid import uuid4

import pytest

from data_platform.tests.postgresql_safety import disposable_postgresql_url


POSTGRESQL_URL = disposable_postgresql_url()


@pytest.mark.skipif(not POSTGRESQL_URL, reason="PostgreSQL real nao configurado")
def test_postgresql_contract_persistence_idempotency_and_downgrade(monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.dialects.postgresql import JSONB, UUID

    from data_platform.contracts.fipe import FipeTarget
    from data_platform.ingestion.fipe.client import FipeResponse
    from data_platform.ingestion.fipe.loader import BronzeLoader
    from data_platform.ingestion.fipe.pipeline import run_pipeline

    class StaticClient:
        def fetch(self, endpoint):
            payload = {
                "codeFipe": "004517-9",
                "modelYear": 2021,
                "referenceMonth": "agosto de 2026",
                "price": "R$ 80.000,00",
            }
            return FipeResponse(endpoint, 200, json.dumps(payload).encode(), datetime.now(UTC))

    class RawClient:
        def __init__(self, status, body):
            self.status = status
            self.body = body

        def fetch(self, endpoint):
            return FipeResponse(endpoint, self.status, self.body, datetime.now(UTC))

    root = Path(__file__).parents[2]
    monkeypatch.setenv("MIGRATION_DATABASE_URL", POSTGRESQL_URL)
    config = Config(str(root / "backend" / "alembic.ini"))
    command.upgrade(config, "head")
    command.downgrade(config, "20260723_0001")
    command.upgrade(config, "head")
    engine = create_engine(POSTGRESQL_URL)
    try:
        db = inspect(engine)
        assert {"meta", "bronze", "silver", "gold"}.issubset(db.get_schema_names())
        assert {"pipeline_run", "data_quality_issue"}.issubset(db.get_table_names(schema="meta"))
        assert set(db.get_table_names(schema="bronze")) == {
            "fipe_raw",
            "pbev_source_asset",
            "pbev_raw_row",
        }
        assert set(db.get_table_names(schema="silver")) == {
            "vehicle_identity",
            "vehicle_source_mapping",
            "vehicle_price_history",
            "pbev_vehicle_mapping",
            "vehicle_efficiency_observation",
        }
        assert set(db.get_table_names(schema="gold")) == {
            "vehicle_feature_dataset",
            "vehicle_features_snapshot",
            "vehicle_feature_dataset_activation",
            "vehicle_efficiency_dataset",
            "vehicle_efficiency_snapshot",
            "vehicle_efficiency_quality_result",
        }
        assert "vehicle_features_current" in db.get_view_names(schema="gold")

        pipeline_columns = {item["name"]: item for item in db.get_columns("pipeline_run", schema="meta")}
        bronze_columns = {item["name"]: item for item in db.get_columns("fipe_raw", schema="bronze")}
        quality_columns = {item["name"]: item for item in db.get_columns("data_quality_issue", schema="meta")}
        assert isinstance(pipeline_columns["pipeline_run_id"]["type"], UUID)
        assert pipeline_columns["started_at"]["type"].timezone is True
        assert pipeline_columns["created_at"]["type"].timezone is True
        assert isinstance(bronze_columns["payload"]["type"], JSONB)
        assert bronze_columns["payload"]["nullable"] is True
        assert bronze_columns["schema_fingerprint"]["nullable"] is True
        assert bronze_columns["raw_content_length"]["nullable"] is False
        assert "raw_content" not in bronze_columns
        assert isinstance(quality_columns["details"]["type"], JSONB)
        assert bronze_columns["year_code"]["type"].length == 30
        assert bronze_columns["payload_hash"]["type"].length == 64
        mapping_columns = {
            item["name"]: item
            for item in db.get_columns("vehicle_source_mapping", schema="silver")
        }
        assert mapping_columns["vehicle_type"]["nullable"] is False
        assert mapping_columns["vehicle_type"]["type"].length == 20

        pipeline_checks = {item["name"] for item in db.get_check_constraints("pipeline_run", schema="meta")}
        bronze_checks = {item["name"] for item in db.get_check_constraints("fipe_raw", schema="bronze")}
        assert {"ck_pipeline_run_counts", "ck_pipeline_run_status", "ck_pipeline_run_timestamps", "ck_pipeline_run_trigger"}.issubset(pipeline_checks)
        assert {"ck_fipe_raw_payload_hash", "ck_fipe_raw_schema_fingerprint", "ck_fipe_raw_status", "ck_fipe_raw_vehicle_type", "ck_fipe_raw_content_length", "ck_fipe_raw_payload_by_status"}.issubset(bronze_checks)
        unique_constraints = {item["name"]: item for item in db.get_unique_constraints("fipe_raw", schema="bronze")}
        index_names = {item["name"] for item in db.get_indexes("fipe_raw", schema="bronze")}
        quality_index_names = {item["name"] for item in db.get_indexes("data_quality_issue", schema="meta")}
        assert unique_constraints["uq_fipe_raw_event_content"]["column_names"] == [
            "source_name", "source_endpoint", "http_status", "ingestion_status", "payload_hash"
        ]
        assert {"ix_fipe_raw_run", "ix_fipe_raw_identity_collected"}.issubset(index_names)
        assert "ix_data_quality_issue_run" in quality_index_names

        invalid_id = uuid4()
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(text("""INSERT INTO meta.pipeline_run
                    (pipeline_run_id,pipeline_name,pipeline_version,dataset_version,trigger_type,status,started_at,records_received)
                    VALUES (:id,'constraint_test','v1','dataset','invalid','unknown',:started,-1)"""),
                    {"id": invalid_id, "started": datetime.now(UTC)})

        target = FipeTarget("car", "004517-9", "2021-5")
        loader = BronzeLoader(engine)
        first = run_pipeline([target], StaticClient(), loader, source_reference="2026-08")
        second = run_pipeline([target], StaticClient(), loader, source_reference="2026-08")
        assert first.status == second.status == "succeeded"
        assert (first.records_inserted, first.records_deduplicated) == (1, 0)
        assert (second.records_inserted, second.records_deduplicated) == (0, 1)

        invalid_body = b"not-json password=never-store"
        invalid_first = run_pipeline([target], RawClient(200, invalid_body), loader, source_reference="2026-08")
        invalid_second = run_pipeline([target], RawClient(200, invalid_body), loader, source_reference="2026-08")
        http_body = b'{"token":"never-store"}'
        http_first = run_pipeline([target], RawClient(503, http_body), loader, source_reference="2026-08")
        http_second = run_pipeline([target], RawClient(503, http_body), loader, source_reference="2026-08")
        for initial, duplicate in ((invalid_first, invalid_second), (http_first, http_second)):
            assert initial.status == duplicate.status == "failed"
            assert (initial.records_inserted, initial.records_deduplicated) == (1, 0)
            assert (duplicate.records_inserted, duplicate.records_deduplicated) == (0, 1)
        with engine.connect() as connection:
            bronze = connection.execute(text("""SELECT year_code,source_record_key,payload,payload_hash,schema_fingerprint,raw_content_length
                FROM bronze.fipe_raw WHERE ingestion_status = 'received'""")).mappings().one()
            error_rows = connection.execute(text("""SELECT ingestion_status,payload,schema_fingerprint,payload_hash,raw_content_length,source_endpoint
                FROM bronze.fipe_raw WHERE ingestion_status IN ('invalid_json','http_error') ORDER BY ingestion_status""")).mappings().all()
            runs = connection.execute(text("""SELECT status,records_received,records_inserted,records_deduplicated,records_rejected
                FROM meta.pipeline_run""")).mappings().all()
        assert bronze["year_code"] == "2021-5"
        assert bronze["source_record_key"] == "004517-9:2021-5"
        assert bronze["payload"]["modelYear"] == 2021
        assert len(bronze["payload_hash"]) == len(bronze["schema_fingerprint"]) == 64
        assert [(item["ingestion_status"], item["raw_content_length"]) for item in error_rows] == [
            ("http_error", len(http_body)),
            ("invalid_json", len(invalid_body)),
        ]
        assert all(item["payload"] is None and item["schema_fingerprint"] is None for item in error_rows)
        assert all(len(item["payload_hash"]) == 64 for item in error_rows)
        assert "never-store" not in repr(error_rows)
        assert len(runs) == 6
        assert sum(item["status"] == "succeeded" for item in runs) == 2
        assert sum(item["status"] == "failed" for item in runs) == 4
        assert sum(item["records_inserted"] for item in runs) == 3
        assert sum(item["records_deduplicated"] for item in runs) == 3

        engine.dispose()
        command.downgrade(config, "20260723_0001")
        engine = create_engine(POSTGRESQL_URL)
        after = inspect(engine)
        assert not {"meta", "bronze", "silver", "gold"}.intersection(after.get_schema_names())
    finally:
        engine.dispose()
        command.upgrade(config, "head")
