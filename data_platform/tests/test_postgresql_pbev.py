from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from data_platform.contracts.pbev import PbevAssetParseResult, SourceAsset
from data_platform.tests.postgresql_safety import disposable_postgresql_url


POSTGRESQL_URL = disposable_postgresql_url()
REQUIRES_SAFE_POSTGRESQL = pytest.mark.skipif(
    not POSTGRESQL_URL,
    reason="PostgreSQL descartavel terminado em _test nao configurado",
)


@REQUIRES_SAFE_POSTGRESQL
def test_postgresql_pbev_ddl_idempotency_immutability_and_rollback(monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.exc import DBAPIError

    from data_platform.pbev.loader import PbevLoader

    root = Path(__file__).parents[2]
    monkeypatch.setenv("MIGRATION_DATABASE_URL", POSTGRESQL_URL)
    config = Config(str(root / "backend" / "alembic.ini"))
    command.upgrade(config, "head")
    command.downgrade(config, "20260810_0005")
    engine = create_engine(POSTGRESQL_URL)
    try:
        downgraded = inspect(engine)
        assert not {
            "pbev_source_asset",
            "pbev_raw_row",
        }.intersection(downgraded.get_table_names(schema="bronze"))
        assert not {
            "pbev_vehicle_mapping",
            "vehicle_efficiency_observation",
        }.intersection(downgraded.get_table_names(schema="silver"))
        assert not {
            "vehicle_efficiency_dataset",
            "vehicle_efficiency_snapshot",
            "vehicle_efficiency_quality_result",
        }.intersection(downgraded.get_table_names(schema="gold"))

        engine.dispose()
        command.upgrade(config, "head")
        engine = create_engine(POSTGRESQL_URL)
        database = inspect(engine)
        assert {"pbev_source_asset", "pbev_raw_row"}.issubset(
            database.get_table_names(schema="bronze")
        )
        assert {"pbev_vehicle_mapping", "vehicle_efficiency_observation"}.issubset(
            database.get_table_names(schema="silver")
        )
        assert {
            "vehicle_efficiency_dataset",
            "vehicle_efficiency_snapshot",
            "vehicle_efficiency_quality_result",
        }.issubset(database.get_table_names(schema="gold"))
        assert "pbev_vehicle_mapping_current" in database.get_view_names(schema="silver")
        assert "uq_pbev_dataset_active_shadow" in {
            item["name"]
            for item in database.get_indexes("vehicle_efficiency_dataset", schema="gold")
        }
        assert "uq_pbev_quality_result" in {
            item["name"]
            for item in database.get_indexes("vehicle_efficiency_quality_result", schema="gold")
        }

        loader = PbevLoader(engine)
        run_id = loader.start_run(
            "pbev_contract_test",
            "pbev-pdf-v1",
            "pbev-contract-test",
            "manual",
            None,
            None,
        )
        asset = SourceAsset(
            pipeline_run_id=run_id,
            cycle_year=2099,
            official_page_url="https://www.gov.br/inmetro/test.pdf",
            download_url_sanitized="https://www.gov.br/inmetro/test.pdf",
            document_title="Synthetic contract asset",
            accessed_at=datetime.now(UTC),
            content_type="application/pdf",
            byte_length=5,
            page_count=1,
            sha256="a" * 64,
            layout_family="pbev-contract-test-v1",
            document_metadata={"synthetic": True},
            validation_details={"contract_test": True},
        )
        result = PbevAssetParseResult(asset, (), 1, 1, 0)
        _, inserted, deduplicated = loader.persist_bronze(run_id, [result])
        _, inserted_again, deduplicated_again = loader.persist_bronze(run_id, [result])
        assert (inserted, deduplicated) == (1, 0)
        assert (inserted_again, deduplicated_again) == (0, 1)

        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE bronze.pbev_source_asset "
                        "SET document_title='forbidden' WHERE cycle_year=2099"
                    )
                )
        loader.finish_run(
            run_id,
            "succeeded",
            received=1,
            inserted=1,
            deduplicated=1,
            rejected=0,
        )

        engine.dispose()
        command.downgrade(config, "20260810_0005")
        engine = create_engine(POSTGRESQL_URL)
        assert "pbev_source_asset" not in inspect(engine).get_table_names(schema="bronze")
        engine.dispose()
        command.upgrade(config, "head")
        engine = create_engine(POSTGRESQL_URL)
        assert "pbev_source_asset" in inspect(engine).get_table_names(schema="bronze")
    finally:
        engine.dispose()
        command.upgrade(config, "head")
