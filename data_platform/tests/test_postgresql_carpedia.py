from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from uuid import uuid4

import pytest

from data_platform.tests.postgresql_safety import disposable_postgresql_url


POSTGRESQL_URL = disposable_postgresql_url()


@pytest.mark.skipif(
    not POSTGRESQL_URL,
    reason="PostgreSQL real local descartavel nao configurado",
)
def test_postgresql_carpedia_schema_constraints_guard_and_cycle(monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.exc import DatabaseError, IntegrityError

    root = Path(__file__).parents[2]
    monkeypatch.setenv("MIGRATION_DATABASE_URL", POSTGRESQL_URL)
    config = Config(str(root / "backend" / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(POSTGRESQL_URL, pool_pre_ping=True)
    try:
        database = inspect(engine)
        assert {
            "carpedia_source_asset",
            "carpedia_vehicle_raw",
        }.issubset(database.get_table_names(schema="bronze"))
        assert {
            "carpedia_vehicle_mapping",
            "carpedia_vehicle_specification",
        }.issubset(database.get_table_names(schema="silver"))
        assert {
            "carpedia_vehicle_spec_dataset",
            "carpedia_vehicle_spec_snapshot",
            "carpedia_vehicle_spec_quality_result",
            "carpedia_vehicle_spec_dataset_event",
        }.issubset(database.get_table_names(schema="gold"))
        assert "carpedia_vehicle_mapping_current" in database.get_view_names(schema="silver")
        assert "carpedia_vehicle_specification_current" in database.get_view_names(schema="silver")

        run_id = uuid4()
        observed = datetime(2026, 8, 25, tzinfo=UTC)
        with pytest.raises(DatabaseError, match="Carpedia downgrade blocked"):
            with engine.begin() as connection:
                connection.execute(
                    text("""INSERT INTO meta.pipeline_run
                        (pipeline_run_id,pipeline_name,pipeline_version,dataset_version,
                         trigger_type,status,started_at,finished_at)
                        VALUES (:run,'carpedia_fixture','test','fixture','manual',
                                'succeeded',:at,:at)"""),
                    {"run": run_id, "at": observed},
                )
                connection.execute(
                    text("""INSERT INTO bronze.carpedia_source_asset
                        (pipeline_run_id,logical_endpoint,external_vehicle_id,
                         source_reference,endpoint_path,collected_at,http_status,
                         content_type,byte_length,sha256,schema_fingerprint,
                         contract_version,license_status,storage_mode,payload_sanitized,
                         ingestion_status,technical_metadata)
                        VALUES (:run,'vehicle_specification',12345,'12345:2021',
                                '/api/v1/ficha/12345/2021',:at,200,'application/json',2,
                                :hash,:schema,'carpedia-api-v1','approved_with_restrictions',
                                'database_json',CAST(:payload AS jsonb),'accepted',
                                CAST('{}' AS jsonb))"""),
                    {
                        "run": run_id,
                        "at": observed,
                        "hash": "a" * 64,
                        "schema": "b" * 64,
                        "payload": json.dumps({"ok": True}),
                    },
                )
                connection.execute(text("SELECT meta.assert_carpedia_downgrade_safe()"))

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text("""INSERT INTO gold.carpedia_vehicle_spec_dataset
                        (dataset_version,publication_run_id,source_asset_manifest,
                         parser_version,normalizer_version,matcher_version,
                         publication_version,status,is_active_shadow,source_record_count,
                         matched_count,snapshot_count,dataset_fingerprint,quality_status)
                        VALUES ('invalid',:run,CAST('[]' AS jsonb),'p','n','m','v',
                                'building',FALSE,0,0,0,:hash,'passed')"""),
                    {"run": uuid4(), "hash": "c" * 64},
                )
    finally:
        engine.dispose()

    command.downgrade(config, "20260811_0010")
    command.upgrade(config, "head")
    restored = create_engine(POSTGRESQL_URL, pool_pre_ping=True)
    try:
        with restored.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260811_0011"
    finally:
        restored.dispose()
