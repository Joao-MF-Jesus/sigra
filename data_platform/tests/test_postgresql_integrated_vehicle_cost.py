from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from data_platform.tests.postgresql_safety import disposable_postgresql_url


POSTGRESQL_URL = disposable_postgresql_url()


@pytest.mark.skipif(
    not POSTGRESQL_URL,
    reason="PostgreSQL real local descartavel nao configurado",
)
def test_postgresql_integrated_vehicle_cost_schema_constraints_and_catalog(monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.exc import DBAPIError

    root = Path(__file__).parents[2]
    monkeypatch.setenv("MIGRATION_DATABASE_URL", POSTGRESQL_URL)
    config = Config(str(root / "backend" / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(POSTGRESQL_URL)
    try:
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT COUNT(*) FROM gold.integrated_vehicle_cost_dataset")
            ).scalar_one() == 0
        engine.dispose()
        command.downgrade(config, "20260811_0008")
        downgraded_engine = create_engine(POSTGRESQL_URL)
        try:
            assert not {
                table_name
                for table_name in inspect(downgraded_engine).get_table_names(schema="gold")
                if table_name.startswith("integrated_vehicle_cost_")
            }
        finally:
            downgraded_engine.dispose()
        command.upgrade(config, "head")
        engine = create_engine(POSTGRESQL_URL)

        suffix = uuid4().hex[:12]
        fipe_version = f"fipe-{suffix}"
        pbev_version = f"pbev-{suffix}"
        anp_version = f"anp-{suffix}"
        integrated_version = f"integrated-{suffix}"
        run_ids = [uuid4() for _ in range(4)]
        connection = engine.connect()
        transaction = connection.begin()
        try:
            connection.execute(
                text(
                    """INSERT INTO meta.pipeline_run
                    (pipeline_run_id,pipeline_name,pipeline_version,dataset_version,
                     trigger_type,status,started_at,records_received)
                    VALUES (:id,:name,'v1',:dataset,'manual','running',:started,0)"""
                ),
                [
                    {
                        "id": run_id,
                        "name": f"integrated_schema_fixture_{index}",
                        "dataset": dataset_version,
                        "started": datetime.now(UTC),
                    }
                    for index, (run_id, dataset_version) in enumerate(
                        zip(
                            run_ids,
                            (fipe_version, pbev_version, anp_version, integrated_version),
                            strict=True,
                        )
                    )
                ],
            )
            connection.execute(
                text(
                    """INSERT INTO gold.vehicle_feature_dataset
                    (dataset_version,publication_run_id,dataset_fingerprint,scope_vehicle_type,
                     source_name,status,expected_vehicle_count,published_vehicle_count,
                     blocked_vehicle_count,coverage_percentage,minimum_reference_month,
                     maximum_reference_month,base_quality_status,is_active)
                    VALUES (:version,:run,:fingerprint,'car',:source,'building',1,1,0,
                            100.00,:month,:month,'passed',FALSE)"""
                ),
                {
                    "version": fipe_version,
                    "run": run_ids[0],
                    "fingerprint": "a" * 64,
                    "source": "Tabela FIPE via API Parallelum",
                    "month": date(2026, 8, 1),
                },
            )
            connection.execute(
                text(
                    """INSERT INTO gold.vehicle_efficiency_dataset
                    (dataset_version,publication_run_id,source_system,source_asset_manifest,
                     source_asset_set_hash,parser_version,matcher_version,status,is_active_shadow,
                     universe_count,eligible_count,matched_count,pending_count,ambiguous_count,
                     rejected_count,not_found_count,published_count,coverage_percentage,
                     coverage_report,dataset_fingerprint,quality_status)
                    VALUES (:version,:run,'inmetro_pbev','{}'::jsonb,:source_hash,'v1','v1',
                            'building',FALSE,1,1,1,0,0,0,0,1,100.00,'{}'::jsonb,
                            :fingerprint,'passed')"""
                ),
                {
                    "version": pbev_version,
                    "run": run_ids[1],
                    "source_hash": "b" * 64,
                    "fingerprint": "c" * 64,
                },
            )
            connection.execute(
                text(
                    """INSERT INTO gold.anp_fuel_price_dataset
                    (dataset_version,publication_run_id,source_asset_manifest,source_asset_set_hash,
                     parser_version,normalizer_version,aggregation_version,reference_period_start,
                     reference_period_end,status,is_active_shadow,observation_count,snapshot_count,
                     dataset_fingerprint,quality_status)
                    VALUES (:version,:run,'{}'::jsonb,:source_hash,'v1','v1','v1',:start,:end,
                            'building',FALSE,1,1,:fingerprint,'passed')"""
                ),
                {
                    "version": anp_version,
                    "run": run_ids[2],
                    "source_hash": "d" * 64,
                    "fingerprint": "e" * 64,
                    "start": date(2026, 8, 3),
                    "end": date(2026, 8, 9),
                },
            )
            connection.execute(
                text(
                    """INSERT INTO gold.integrated_vehicle_cost_dataset
                    (dataset_version,publication_run_id,fipe_source_dataset_version,
                     pbev_source_dataset_version,anp_source_dataset_version,
                     fipe_source_fingerprint,pbev_source_fingerprint,anp_source_fingerprint,
                     analytic_cutoff_at,calculation_policy_version,geography_policy_version,
                     scenario_policy_version,quality_policy_version,dataset_fingerprint)
                    VALUES (:version,:run,:fipe,:pbev,:anp,:fipe_hash,:pbev_hash,:anp_hash,
                            :cutoff,'v1','exact-v1','mixed-v1',
                            'integrated-vehicle-cost-quality-v1',:fingerprint)"""
                ),
                {
                    "version": integrated_version,
                    "run": run_ids[3],
                    "fipe": fipe_version,
                    "pbev": pbev_version,
                    "anp": anp_version,
                    "fipe_hash": "a" * 64,
                    "pbev_hash": "c" * 64,
                    "anp_hash": "e" * 64,
                    "cutoff": datetime.now(UTC) - timedelta(seconds=1),
                    "fingerprint": "f" * 64,
                },
            )
            with pytest.raises(DBAPIError, match="downgrade blocked"):
                connection.execute(
                    text("SELECT gold.assert_integrated_downgrade_safe()")
                )
        finally:
            transaction.rollback()
            connection.close()

        database = inspect(engine)
        expected_tables = {
            "integrated_vehicle_cost_dataset",
            "integrated_vehicle_cost_snapshot",
            "integrated_vehicle_cost_projection_snapshot",
            "integrated_vehicle_cost_flex_comparison_snapshot",
            "integrated_vehicle_cost_geography_request",
            "integrated_vehicle_cost_exclusion",
            "integrated_vehicle_cost_quality_rule_catalog",
            "integrated_vehicle_cost_quality_result",
            "integrated_vehicle_cost_activation",
            "integrated_vehicle_cost_invalidation",
            "integrated_vehicle_cost_coverage_baseline",
        }
        assert expected_tables.issubset(database.get_table_names(schema="gold"))
        dataset_columns = {
            item["name"]: item
            for item in database.get_columns(
                "integrated_vehicle_cost_dataset", schema="gold"
            )
        }
        snapshot_columns = {
            item["name"]: item
            for item in database.get_columns(
                "integrated_vehicle_cost_snapshot", schema="gold"
            )
        }
        projection_columns = {
            item["name"]: item
            for item in database.get_columns(
                "integrated_vehicle_cost_projection_snapshot", schema="gold"
            )
        }
        assert dataset_columns["dataset_version"]["type"].length == 96
        assert dataset_columns["fipe_source_dataset_version"]["type"].length == 80
        assert "scenario_code" not in snapshot_columns
        assert projection_columns["scenario_code"]["type"].length == 40

        snapshot_fks = {
            item["name"]: (item["referred_table"], tuple(item["referred_columns"]))
            for item in database.get_foreign_keys(
                "integrated_vehicle_cost_snapshot", schema="gold"
            )
        }
        assert ("vehicle_features_snapshot", ("gold_record_id",)) in snapshot_fks.values()
        assert ("vehicle_efficiency_snapshot", ("gold_record_id",)) in snapshot_fks.values()
        assert ("anp_fuel_price_snapshot", ("snapshot_id",)) in snapshot_fks.values()

        snapshot_uniques = {
            tuple(item["column_names"])
            for item in database.get_unique_constraints(
                "integrated_vehicle_cost_snapshot", schema="gold"
            )
        }
        projection_uniques = {
            tuple(item["column_names"])
            for item in database.get_unique_constraints(
                "integrated_vehicle_cost_projection_snapshot", schema="gold"
            )
        }
        assert (
            "dataset_version",
            "vehicle_sk",
            "fuel_scenario_code",
            "requested_geography_level",
            "requested_geography_key",
            "anp_week_start",
        ) in snapshot_uniques
        assert ("dataset_version", "snapshot_id", "scenario_code") in projection_uniques

        with engine.connect() as connection:
            catalog = connection.execute(
                text(
                    """SELECT rule_kind,expected_status,COUNT(*) AS total
                    FROM gold.integrated_vehicle_cost_quality_rule_catalog
                    GROUP BY rule_kind,expected_status ORDER BY rule_kind"""
                )
            ).all()
            heads = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        assert [tuple(row) for row in catalog] == [
            ("hard_gate", "passed", 29),
            ("statistical_control", "not_calibrated", 7),
        ]
        assert heads == ["20260811_0009"]
    finally:
        engine.dispose()
