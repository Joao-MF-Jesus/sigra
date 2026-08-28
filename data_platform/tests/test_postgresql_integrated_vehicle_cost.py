from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from data_platform.tests.postgresql_safety import disposable_postgresql_url


POSTGRESQL_URL = disposable_postgresql_url()


def _seed_pbev_gold(connection, *, run_id, vehicle_sk: int) -> str:
    from sqlalchemy import text

    suffix = uuid4().hex[:12]
    now = datetime.now(UTC) - timedelta(seconds=2)
    asset_id = connection.execute(
        text(
            """INSERT INTO bronze.pbev_source_asset
            (pipeline_run_id,source_system,official_page_url,download_url_sanitized,
             document_title,cycle_year,accessed_at,content_type,byte_length,page_count,
             sha256,layout_family,document_metadata,document_bytes,storage_mode,
             license_code,attribution_text,license_url,asset_status,validation_details)
            VALUES (:run,'inmetro_pbev','https://www.gov.br/inmetro/fixture',
                    'https://www.gov.br/inmetro/fixture.pdf','PBEV fixture',2022,
                    :now,'application/pdf',1,1,:hash,'pbev-l4-2022-v1','{}'::jsonb,
                    NULL,'metadata_only','CC-BY-ND-3.0','Inmetro PBE Veicular',
                    'https://creativecommons.org/licenses/by-nd/3.0/',
                    'accepted','{}'::jsonb)
            RETURNING asset_id"""
        ),
        {"run": run_id, "now": now, "hash": sha256(f"asset-{suffix}".encode()).hexdigest()},
    ).scalar_one()
    raw_id = connection.execute(
        text(
            """INSERT INTO bronze.pbev_raw_row
            (asset_id,pipeline_run_id,page_number,row_number,source_record_key,
             parser_version,layout_family,schema_fingerprint,raw_cells,raw_text,
             row_hash,extraction_status,extraction_method,extracted_at)
            VALUES (:asset,:run,1,1,:source_key,'pbev-pdf-v1','pbev-l4-2022-v1',
                    :schema_hash,'[]'::jsonb,'fixture',:row_hash,'parsed',
                    'vector_grid',:now)
            RETURNING pbev_raw_row_id"""
        ),
        {
            "asset": asset_id,
            "run": run_id,
            "source_key": f"fixture-{suffix}",
            "schema_hash": sha256(b"pbev-schema").hexdigest(),
            "row_hash": sha256(f"row-{suffix}".encode()).hexdigest(),
            "now": now,
        },
    ).scalar_one()
    mapping_id = connection.execute(
        text(
            """INSERT INTO silver.pbev_vehicle_mapping
            (pipeline_run_id,source_system,target_identity_hash,target_identity_evidence,
             target_vehicle_type,selected_raw_row_id,vehicle_sk,mapping_status,
             match_method,confidence,review_required,matcher_version,evidence,
             decision_reason,effective_at)
            VALUES (:run,'inmetro_pbev',:identity,'{}'::jsonb,'car',:raw,:vehicle,
                    'matched','exact_rule',100,FALSE,'pbev-match-v1','{}'::jsonb,
                    'fixture exact match',:now)
            RETURNING mapping_decision_id"""
        ),
        {
            "run": run_id,
            "identity": sha256(f"identity-{suffix}".encode()).hexdigest(),
            "raw": raw_id,
            "vehicle": vehicle_sk,
            "now": now,
        },
    ).scalar_one()
    observation_id = connection.execute(
        text(
            """INSERT INTO silver.vehicle_efficiency_observation
            (pipeline_run_id,vehicle_sk,mapping_decision_id,pbev_raw_row_id,cycle_year,
             source_reference_date,category_name,brand_name,model_name,version_name,
             motor_description,transmission_code,propulsion_type,fuel_type,
             emission_schema_version,emission_raw,consumption_raw,
             ethanol_city_km_l,ethanol_highway_km_l,fossil_city_km_l,
             fossil_highway_km_l,energy_mj_km,methodology_reference,quality_status,
             observed_at)
            VALUES (:run,:vehicle,:mapping,:raw,2022,'2022-01-01','Carros','Brand 1',
                    'Model 1','Flex','1.6','AUT','combustion','flex','pbev-2022-v1',
                    '{}'::jsonb,'{}'::jsonb,7.0000,10.0000,10.0000,15.0000,
                    2.0000,'PBEV fixture','passed',:now)
            RETURNING observation_id"""
        ),
        {
            "run": run_id,
            "vehicle": vehicle_sk,
            "mapping": mapping_id,
            "raw": raw_id,
            "now": now,
        },
    ).scalar_one()
    dataset_version = f"pbev-integrated-fixture-{suffix}"
    dataset_fingerprint = sha256(f"pbev-dataset-{suffix}".encode()).hexdigest()
    connection.execute(
        text(
            """INSERT INTO gold.vehicle_efficiency_dataset
            (dataset_version,publication_run_id,source_system,source_asset_manifest,
             source_asset_set_hash,parser_version,matcher_version,status,
             is_active_shadow,universe_count,eligible_count,matched_count,pending_count,
             ambiguous_count,rejected_count,not_found_count,published_count,
             coverage_percentage,coverage_report,dataset_fingerprint,quality_status)
            VALUES (:dataset,:run,'inmetro_pbev','[]'::jsonb,:asset_hash,
                    'pbev-pdf-v1','pbev-match-v1','building',FALSE,1,1,1,0,0,0,0,1,
                    100.00,'{}'::jsonb,:fingerprint,'passed')"""
        ),
        {
            "dataset": dataset_version,
            "run": run_id,
            "asset_hash": sha256(f"asset-set-{suffix}".encode()).hexdigest(),
            "fingerprint": dataset_fingerprint,
        },
    )
    connection.execute(
        text(
            """INSERT INTO gold.vehicle_efficiency_snapshot
            (dataset_version,publication_run_id,vehicle_sk,mapping_decision_id,
             observation_id,asset_id,pbev_raw_row_id,cycle_year,brand_name,model_name,
             version_name,motor_description,transmission_code,propulsion_type,fuel_type,
             emission_schema_version,ethanol_city_km_l,ethanol_highway_km_l,
             fossil_city_km_l,fossil_highway_km_l,energy_mj_km,parser_version,
             matcher_version,data_confidence,quality_status,published_at)
            VALUES (:dataset,:run,:vehicle,:mapping,:observation,:asset,:raw,2022,
                    'Brand 1','Model 1','Flex','1.6','AUT','combustion','flex',
                    'pbev-2022-v1',7.0000,10.0000,10.0000,15.0000,2.0000,
                    'pbev-pdf-v1','pbev-match-v1',100,'passed',:now)"""
        ),
        {
            "dataset": dataset_version,
            "run": run_id,
            "vehicle": vehicle_sk,
            "mapping": mapping_id,
            "observation": observation_id,
            "asset": asset_id,
            "raw": raw_id,
            "now": now,
        },
    )
    connection.execute(
        text(
            """UPDATE gold.vehicle_efficiency_dataset
            SET status='shadow_published',is_active_shadow=TRUE,published_at=:now
            WHERE dataset_version=:dataset"""
        ),
        {"dataset": dataset_version, "now": now},
    )
    return dataset_version


def _seed_anp_gold(
    connection,
    *,
    run_id,
    gasoline_price: Decimal,
    include_ethanol: bool = True,
) -> str:
    from sqlalchemy import text

    suffix = uuid4().hex[:12]
    dataset_version = f"anp-integrated-fixture-{suffix}"
    prices = [("gasoline_c_common", gasoline_price)]
    if include_ethanol:
        prices.append(("ethanol_hydrated", Decimal("4.0000")))
    connection.execute(
        text(
            """INSERT INTO gold.anp_fuel_price_dataset
            (dataset_version,publication_run_id,source_asset_manifest,
             source_asset_set_hash,parser_version,normalizer_version,
             aggregation_version,reference_period_start,reference_period_end,
             status,is_active_shadow,observation_count,snapshot_count,
             dataset_fingerprint,quality_status)
            VALUES (:dataset,:run,'[]'::jsonb,:source_hash,'anp-csv-v1','anp-normalizer-v1',
                    'anp-aggregation-v1','2026-08-03','2026-08-09','building',FALSE,
                    :count,:count,:fingerprint,'passed')"""
        ),
        {
            "dataset": dataset_version,
            "run": run_id,
            "source_hash": sha256(f"anp-source-{suffix}".encode()).hexdigest(),
            "count": len(prices),
            "fingerprint": sha256(f"anp-dataset-{suffix}".encode()).hexdigest(),
        },
    )
    for product, price in prices:
        connection.execute(
            text(
                """INSERT INTO gold.anp_fuel_price_snapshot
                (dataset_version,publication_run_id,product_code,week_start,week_end,
                 geography_level,geography_key,municipality_name,state_code,
                 currency_code,unit_code,mean_price,median_price,minimum_price,
                 maximum_price,percentile_25,percentile_75,interquartile_range,
                 observation_count,establishment_count,last_collection_date,
                 freshness_days,sampling_status,dispersion_status,quality_status,
                 snapshot_fingerprint)
                VALUES (:dataset,:run,:product,'2026-08-03','2026-08-09','municipality',
                        'sao-paulo-sp','Sao Paulo','SP','BRL','liter',:price,:price,
                        :minimum,:maximum,:p25,:p75,0.2000,10,5,'2026-08-09',0,
                        'not_calibrated','not_calibrated','passed',:fingerprint)"""
            ),
            {
                "dataset": dataset_version,
                "run": run_id,
                "product": product,
                "price": price,
                "minimum": price - Decimal("0.2000"),
                "maximum": price + Decimal("0.2000"),
                "p25": price - Decimal("0.1000"),
                "p75": price + Decimal("0.1000"),
                "fingerprint": sha256(f"{dataset_version}-{product}".encode()).hexdigest(),
            },
        )
    connection.execute(
        text(
            """UPDATE gold.anp_fuel_price_dataset
            SET status='retired',is_active_shadow=FALSE,retired_at=CURRENT_TIMESTAMP
            WHERE is_active_shadow"""
        )
    )
    connection.execute(
        text(
            """UPDATE gold.anp_fuel_price_dataset
            SET status='shadow_published',is_active_shadow=TRUE,published_at=CURRENT_TIMESTAMP
            WHERE dataset_version=:dataset"""
        ),
        {"dataset": dataset_version},
    )
    return dataset_version


def _capture_publication_cycle_fixture(
    connection,
    *,
    integrated_dataset_versions: set[str],
    pipeline_run_ids: set[UUID],
) -> dict[str, tuple[object, ...]]:
    from sqlalchemy import text

    integrated_versions = sorted(integrated_dataset_versions)
    run_ids = sorted(pipeline_run_ids, key=str)
    version_parameters = {"dataset_versions": integrated_versions}
    dataset_rows = connection.execute(
        text(
            """SELECT dataset_version,dataset_fingerprint,publication_run_id
            FROM gold.integrated_vehicle_cost_dataset
            WHERE dataset_version=ANY(CAST(:dataset_versions AS VARCHAR[]))
            ORDER BY dataset_version"""
        ),
        version_parameters,
    ).mappings().all()
    assert {str(row["dataset_version"]) for row in dataset_rows} == set(
        integrated_versions
    )

    evidence_specs = (
        ("geography_request_ids", "integrated_vehicle_cost_geography_request", "geography_request_id"),
        ("snapshot_ids", "integrated_vehicle_cost_snapshot", "snapshot_id"),
        ("projection_ids", "integrated_vehicle_cost_projection_snapshot", "projection_id"),
        ("flex_comparison_ids", "integrated_vehicle_cost_flex_comparison_snapshot", "flex_comparison_id"),
        ("exclusion_ids", "integrated_vehicle_cost_exclusion", "exclusion_id"),
        ("quality_result_ids", "integrated_vehicle_cost_quality_result", "quality_result_id"),
        ("activation_event_ids", "integrated_vehicle_cost_activation", "activation_event_id"),
        ("invalidation_event_ids", "integrated_vehicle_cost_invalidation", "invalidation_event_id"),
        ("baseline_event_ids", "integrated_vehicle_cost_coverage_baseline", "baseline_event_id"),
    )
    captured: dict[str, tuple[object, ...]] = {
        "dataset_versions": tuple(integrated_versions),
        "dataset_fingerprints": tuple(
            str(row["dataset_fingerprint"]) for row in dataset_rows
        ),
        "dataset_publication_run_ids": tuple(
            row["publication_run_id"] for row in dataset_rows
        ),
        "pipeline_run_ids": tuple(run_ids),
    }
    for key, table_name, id_column in evidence_specs:
        captured[key] = tuple(
            connection.execute(
                text(
                    f"""SELECT {id_column}
                    FROM gold.{table_name}
                    WHERE dataset_version=ANY(
                        CAST(:dataset_versions AS VARCHAR[])
                    )
                    ORDER BY {id_column}"""
                ),
                version_parameters,
            ).scalars()
        )

    activation_rows = connection.execute(
        text(
            """SELECT activation_event_id,activation_run_id,activation_type
            FROM gold.integrated_vehicle_cost_activation
            WHERE dataset_version=ANY(CAST(:dataset_versions AS VARCHAR[]))
            ORDER BY activation_event_id"""
        ),
        version_parameters,
    ).mappings().all()
    captured["activation_run_ids"] = tuple(
        row["activation_run_id"] for row in activation_rows
    )
    captured["rollback_event_ids"] = tuple(
        row["activation_event_id"]
        for row in activation_rows
        if row["activation_type"] == "rollback"
    )
    recorded_runs = set(
        connection.execute(
            text(
                """SELECT pipeline_run_id FROM meta.pipeline_run
                WHERE pipeline_run_id=ANY(CAST(:pipeline_run_ids AS UUID[]))"""
            ),
            {"pipeline_run_ids": run_ids},
        ).scalars()
    )
    assert recorded_runs == set(run_ids)
    return captured


_SIMULATION_READ_ONLY_TABLES = (
    "gold.integrated_vehicle_cost_dataset",
    "gold.integrated_vehicle_cost_geography_request",
    "gold.integrated_vehicle_cost_snapshot",
    "gold.integrated_vehicle_cost_projection_snapshot",
    "gold.integrated_vehicle_cost_flex_comparison_snapshot",
    "gold.integrated_vehicle_cost_exclusion",
    "gold.integrated_vehicle_cost_quality_result",
    "gold.integrated_vehicle_cost_activation",
    "gold.integrated_vehicle_cost_invalidation",
    "gold.integrated_vehicle_cost_coverage_baseline",
    "meta.pipeline_run",
)


def _simulation_storage_fingerprints(connection) -> dict[str, tuple[int, str]]:
    from sqlalchemy import text

    return {
        table_name: tuple(
            connection.execute(
                text(
                    f"""SELECT COUNT(*),
                               COALESCE(
                                   md5(string_agg(
                                       row_to_json(row_value)::text,
                                       '' ORDER BY row_to_json(row_value)::text
                                   )),
                                   md5('')
                               )
                        FROM {table_name} AS row_value"""
                )
            ).one()
        )
        for table_name in _SIMULATION_READ_ONLY_TABLES
    }


def _post_postgresql_simulation(connection, payload: dict[str, object]):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from app.integrated_gold.routes import (
        get_vehicle_cost_simulation_service,
        router,
    )
    from app.integrated_gold.simulation_repository import (
        VehicleCostSimulationRepository,
    )
    from app.integrated_gold.simulation_service import (
        VehicleCostSimulationService,
    )

    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    service = VehicleCostSimulationService(VehicleCostSimulationRepository(session))
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_vehicle_cost_simulation_service] = (
        lambda: service
    )
    try:
        with TestClient(application) as client:
            return client.post(
                "/api/v1/integrated-vehicle-cost/simulate",
                json=payload,
            )
    finally:
        application.dependency_overrides.clear()
        session.close()


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
        assert heads == ["20260811_0011"]
    finally:
        engine.dispose()


@pytest.mark.skipif(
    not POSTGRESQL_URL,
    reason="PostgreSQL real local descartavel nao configurado",
)
def test_postgresql_integrated_vehicle_cost_publication_cycle(monkeypatch):
    from contextlib import contextmanager

    from alembic import command
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import DBAPIError

    import data_platform.integrated_vehicle_cost.pipeline as integrated_pipeline
    import data_platform.publication.loader as gold_loader_module
    from data_platform.integrated_vehicle_cost.loader import IntegratedVehicleCostLoader
    from data_platform.integrated_vehicle_cost.pipeline import (
        IntegratedPublicationError,
        IntegratedPublicationRequest,
        IntegratedVehicleCostOptions,
        rollback_integrated_vehicle_cost,
        run_integrated_vehicle_cost_pipeline,
    )
    from data_platform.publication.loader import GoldLoader
    from data_platform.publication.pipeline import run_gold_publication
    from data_platform.tests.test_postgresql_gold import (
        _config,
        _insert_gold_scope_mapping,
        _insert_run,
        _reset_database,
    )

    config = _config(monkeypatch)
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2] / "backend"))
    _reset_database(config)
    engine = create_engine(POSTGRESQL_URL, pool_pre_ping=True)
    sentinel_run_id = uuid4()
    sentinel_at = datetime.now(UTC)
    with engine.begin() as sentinel_connection:
        sentinel_connection.execute(
            text(
                """INSERT INTO meta.pipeline_run
                (pipeline_run_id,pipeline_name,pipeline_version,dataset_version,
                 trigger_type,status,started_at,finished_at,records_received)
                VALUES (:run,'integrated_cleanup_sentinel','test-v1',:dataset,
                        'manual','succeeded',:started,:finished,0)"""
            ),
            {
                "run": sentinel_run_id,
                "dataset": f"cleanup-sentinel-{sentinel_run_id.hex[:12]}",
                "started": sentinel_at,
                "finished": sentinel_at,
            },
        )
    request = IntegratedPublicationRequest(
        geography_level="municipality",
        geography_key="sao-paulo-sp",
        week_start=date(2026, 8, 3),
        include_additized=False,
    )
    options = IntegratedVehicleCostOptions(request=request)
    integrated_dataset_versions: set[str] = set()
    fipe_dataset_versions: set[str] = set()
    pbev_dataset_versions: set[str] = set()
    anp_dataset_versions: set[str] = set()
    pipeline_run_ids: set[UUID] = set()
    captured_identifiers: dict[str, tuple[object, ...]] = {}
    fixture_connection = engine.connect().execution_options(
        isolation_level="REPEATABLE READ"
    )
    fixture_transaction = fixture_connection.begin()

    class NestedTransactionEngine:
        def __init__(self, connection):
            self.connection = connection
            self.dialect = connection.dialect

        @contextmanager
        def begin(self):
            nested = self.connection.begin_nested()
            try:
                yield self.connection
                nested.commit()
            except BaseException:
                if nested.is_active:
                    nested.rollback()
                raise

    @contextmanager
    def fixture_gold_publication_transaction():
        nested = fixture_connection.begin_nested()
        try:
            GoldLoader.acquire_lock(fixture_connection)
            yield fixture_connection
            nested.commit()
        except BaseException:
            if nested.is_active:
                nested.rollback()
            raise

    @contextmanager
    def fixture_integrated_publication_transaction():
        nested = fixture_connection.begin_nested()
        try:
            fixture_connection.execute(
                text(
                    "SELECT pg_advisory_xact_lock(hashtext('integrated_vehicle_cost'))"
                )
            )
            yield fixture_connection
            nested.commit()
        except BaseException:
            if nested.is_active:
                nested.rollback()
            raise

    transaction_timestamp = fixture_connection.execute(
        text("SELECT CURRENT_TIMESTAMP")
    ).scalar_one()

    class TransactionDateTime:
        @classmethod
        def now(cls, timezone=None):
            if timezone is None:
                return transaction_timestamp.replace(tzinfo=None)
            return transaction_timestamp.astimezone(timezone)

    monkeypatch.setattr(integrated_pipeline, "datetime", TransactionDateTime)
    monkeypatch.setattr(gold_loader_module, "datetime", TransactionDateTime)

    def capture_integrated_result(result):
        if result.dataset_version is not None:
            integrated_dataset_versions.add(result.dataset_version)
        if result.pipeline_run_id is not None:
            pipeline_run_ids.add(UUID(result.pipeline_run_id))
        return result

    try:
        silver_run = _insert_run(
            fixture_connection,
            name="integrated_fipe_fixture",
        )
        pipeline_run_ids.add(silver_run)
        _, vehicle_sk, _ = _insert_gold_scope_mapping(
            fixture_connection,
            silver_run,
            ordinal=1,
            matched=True,
        )
        assert vehicle_sk is not None

        gold_loader = GoldLoader(NestedTransactionEngine(fixture_connection))
        gold_loader.publication_transaction = fixture_gold_publication_transaction
        fipe_result = run_gold_publication(
            gold_loader,
            source_reference="integrated-publication-fixture",
        )
        if fipe_result.dataset_version is not None:
            fipe_dataset_versions.add(fipe_result.dataset_version)
        if fipe_result.pipeline_run_id is not None:
            pipeline_run_ids.add(UUID(fipe_result.pipeline_run_id))
        assert fipe_result.status == "succeeded"

        pbev_run = _insert_run(
            fixture_connection,
            name="integrated_pbev_fixture",
        )
        pipeline_run_ids.add(pbev_run)
        pbev_dataset_versions.add(
            _seed_pbev_gold(
                fixture_connection,
                run_id=pbev_run,
                vehicle_sk=vehicle_sk,
            )
        )
        anp_run = _insert_run(
            fixture_connection,
            name="integrated_anp_fixture",
        )
        pipeline_run_ids.add(anp_run)
        anp_dataset_versions.add(
            _seed_anp_gold(
                fixture_connection,
                run_id=anp_run,
                gasoline_price=Decimal("6.0000"),
            )
        )

        loader = IntegratedVehicleCostLoader(
            NestedTransactionEngine(fixture_connection)
        )
        loader.publication_transaction = fixture_integrated_publication_transaction
        first = capture_integrated_result(
            run_integrated_vehicle_cost_pipeline(loader, options)
        )
        duplicate = capture_integrated_result(
            run_integrated_vehicle_cost_pipeline(loader, options)
        )
        assert first.status == "succeeded"
        assert first.activation_type == "publish"
        assert first.published_vehicle_count == 1
        assert first.published_scenario_count == 2
        assert duplicate.status == "deduplicated"
        assert duplicate.dataset_version == first.dataset_version

        assert fixture_connection.execute(
            text("SELECT COUNT(*) FROM gold.integrated_vehicle_cost_dataset")
        ).scalar_one() == 1
        assert fixture_connection.execute(
            text("SELECT COUNT(*) FROM gold.integrated_vehicle_cost_snapshot")
        ).scalar_one() == 2
        assert fixture_connection.execute(
            text(
                "SELECT COUNT(*) FROM gold.integrated_vehicle_cost_projection_snapshot"
            )
        ).scalar_one() == 2
        assert fixture_connection.execute(
            text("SELECT COUNT(*) FROM gold.integrated_vehicle_cost_quality_result")
        ).scalar_one() == 36
        assert fixture_connection.execute(
            text("SELECT COUNT(*) FROM gold.integrated_vehicle_cost_activation")
        ).scalar_one() == 1

        unknown_vehicle_sk = fixture_connection.execute(
            text(
                """SELECT COALESCE(MAX(vehicle_sk),0) + 1000000
                FROM gold.integrated_vehicle_cost_snapshot"""
            )
        ).scalar_one()
        simulation_payload = {
            "monthly_distance_km": "1375.50",
            "city_percentage": "35.00",
            "highway_percentage": "65.00",
            "state_code": "SP",
            "municipality": "sao-paulo-sp",
            "reference_week_start": "2026-08-03",
            "fuel_strategy": "gasoline_c_common",
            "horizon_months": 12,
            "vehicle_sks": [vehicle_sk, unknown_vehicle_sk],
            "max_results": 10,
        }
        simulation_storage_before = _simulation_storage_fingerprints(
            fixture_connection
        )
        gasoline_response = _post_postgresql_simulation(
            fixture_connection,
            simulation_payload,
        )
        repeated_response = _post_postgresql_simulation(
            fixture_connection,
            simulation_payload,
        )
        ethanol_response = _post_postgresql_simulation(
            fixture_connection,
            {**simulation_payload, "fuel_strategy": "ethanol_hydrated"},
        )
        lowest_cost_response = _post_postgresql_simulation(
            fixture_connection,
            {**simulation_payload, "fuel_strategy": "lowest_projected_cost"},
        )
        longer_distance_response = _post_postgresql_simulation(
            fixture_connection,
            {**simulation_payload, "monthly_distance_km": "2000.00"},
        )
        city_heavy_response = _post_postgresql_simulation(
            fixture_connection,
            {
                **simulation_payload,
                "city_percentage": "80.00",
                "highway_percentage": "20.00",
            },
        )
        assert all(
            response.status_code == 200
            for response in (
                gasoline_response,
                repeated_response,
                ethanol_response,
                lowest_cost_response,
                longer_distance_response,
                city_heavy_response,
            )
        )
        gasoline_body = gasoline_response.json()
        repeated_body = repeated_response.json()
        ethanol_body = ethanol_response.json()
        lowest_cost_body = lowest_cost_response.json()
        longer_distance_body = longer_distance_response.json()
        city_heavy_body = city_heavy_response.json()
        assert repeated_body["fingerprint"] == gasoline_body["fingerprint"]
        assert {
            key: value
            for key, value in repeated_body.items()
            if key != "response_timestamp"
        } == {
            key: value
            for key, value in gasoline_body.items()
            if key != "response_timestamp"
        }
        assert gasoline_body["scenario"] == {
            **simulation_payload,
            "manual_fuel_price_brl": None,
            "city_consumption_km_l": None,
            "highway_consumption_km_l": None,
            "vehicle_sks": [vehicle_sk, unknown_vehicle_sk],
        }
        assert gasoline_body["results"][0]["fuel_code"] == "gasoline_c_common"
        assert gasoline_body["results"][0]["fuel_price_origin"] == "anp_gold"
        assert gasoline_body["results"][0]["canonical_scenario_code"] == (
            "mixed_1000_v1"
        )
        assert ethanol_body["results"][0]["fuel_code"] == "ethanol_hydrated"
        assert lowest_cost_body["results"][0]["fuel_code"] == "ethanol_hydrated"
        assert gasoline_body["results"][0]["sources"][
            "integrated_dataset_version"
        ] == first.dataset_version
        assert gasoline_body["evaluated_vehicle_count"] == 2
        assert gasoline_body["eligible_vehicle_count"] == 1
        assert gasoline_body["excluded_vehicle_count"] == 1
        assert gasoline_body["exclusions"] == [
            {
                "vehicle_sk": unknown_vehicle_sk,
                "reason_code": "VEHICLE_NOT_IN_ACTIVE_INTEGRATED_GOLD",
                "detail": "no published active Gold evidence exists for the vehicle",
            }
        ]
        assert Decimal(
            longer_distance_body["results"][0]["monthly_fuel_cost_brl"]
        ) > Decimal(gasoline_body["results"][0]["monthly_fuel_cost_brl"])
        assert (
            city_heavy_body["results"][0]["monthly_fuel_cost_brl"]
            != gasoline_body["results"][0]["monthly_fuel_cost_brl"]
        )
        assert longer_distance_body["fingerprint"] != gasoline_body["fingerprint"]
        assert city_heavy_body["fingerprint"] != gasoline_body["fingerprint"]
        assert _simulation_storage_fingerprints(fixture_connection) == (
            simulation_storage_before
        )

        no_active_savepoint = fixture_connection.begin_nested()
        try:
            active_timestamps = fixture_connection.execute(
                text(
                    """SELECT created_at,last_activated_at,
                              CURRENT_TIMESTAMP AS transaction_started_at,
                              clock_timestamp() AS effective_now
                    FROM gold.integrated_vehicle_cost_dataset
                    WHERE dataset_version=:dataset_version"""
                ),
                {"dataset_version": first.dataset_version},
            ).mappings().one()
            assert (
                active_timestamps["last_activated_at"]
                >= active_timestamps["created_at"]
            )
            assert (
                active_timestamps["last_activated_at"]
                > active_timestamps["transaction_started_at"]
            )
            assert (
                active_timestamps["effective_now"]
                >= active_timestamps["last_activated_at"]
            )
            retired_at = loader.lifecycle_timestamp(
                fixture_connection,
                dataset_version=first.dataset_version,
            )
            assert retired_at >= active_timestamps["last_activated_at"]
            fixture_connection.execute(
                text(
                    """UPDATE gold.integrated_vehicle_cost_dataset
                    SET status='retired',is_active_shadow=FALSE,
                        retired_at=:retired_at
                    WHERE dataset_version=:dataset_version"""
                ),
                {
                    "dataset_version": first.dataset_version,
                    "retired_at": retired_at,
                },
            )
            unavailable_response = _post_postgresql_simulation(
                fixture_connection,
                simulation_payload,
            )
            assert unavailable_response.status_code == 503
            assert unavailable_response.json() == {
                "detail": {
                    "code": "vehicle_cost_simulation_unavailable",
                    "message": "no active and eligible integrated Gold dataset",
                }
            }
        finally:
            no_active_savepoint.rollback()
        assert _simulation_storage_fingerprints(fixture_connection) == (
            simulation_storage_before
        )

        replacement_anp_run = _insert_run(
            fixture_connection,
            name="integrated_anp_replacement_fixture",
        )
        pipeline_run_ids.add(replacement_anp_run)
        anp_dataset_versions.add(
            _seed_anp_gold(
                fixture_connection,
                run_id=replacement_anp_run,
                gasoline_price=Decimal("6.1000"),
            )
        )

        replacement = capture_integrated_result(
            run_integrated_vehicle_cost_pipeline(loader, options)
        )
        replacement_duplicate = capture_integrated_result(
            run_integrated_vehicle_cost_pipeline(loader, options)
        )
        assert replacement.status == "succeeded"
        assert replacement.activation_type == "replace"
        assert replacement.previous_dataset_version == first.dataset_version
        assert replacement_duplicate.status == "deduplicated"
        assert replacement_duplicate.dataset_version == replacement.dataset_version
        replacement_response = _post_postgresql_simulation(
            fixture_connection,
            simulation_payload,
        )
        assert replacement_response.status_code == 200
        replacement_sources = replacement_response.json()["results"][0]["sources"]
        replacement_source_version = replacement_sources["integrated_dataset_version"]
        assert replacement_source_version == replacement.dataset_version
        assert replacement_source_version != first.dataset_version

        immutable_before = fixture_connection.execute(
            text(
                """SELECT row_to_json(snapshot_row)::text
                FROM gold.integrated_vehicle_cost_snapshot AS snapshot_row
                ORDER BY dataset_version,snapshot_id"""
            )
        ).scalars().all()
        rollback = capture_integrated_result(
            rollback_integrated_vehicle_cost(loader, first.dataset_version)
        )
        repeated_rollback = capture_integrated_result(
            rollback_integrated_vehicle_cost(
                loader,
                first.dataset_version,
            )
        )
        assert rollback.status == "succeeded"
        assert rollback.activation_type == "rollback"
        assert rollback.previous_dataset_version == replacement.dataset_version
        assert repeated_rollback.status == "deduplicated"

        immutable_after = fixture_connection.execute(
            text(
                """SELECT row_to_json(snapshot_row)::text
                FROM gold.integrated_vehicle_cost_snapshot AS snapshot_row
                ORDER BY dataset_version,snapshot_id"""
            )
        ).scalars().all()
        assert immutable_after == immutable_before
        counts_before_failure = fixture_connection.execute(
            text(
                """SELECT
                    (SELECT COUNT(*) FROM gold.integrated_vehicle_cost_dataset),
                    (SELECT COUNT(*) FROM gold.integrated_vehicle_cost_activation),
                    (SELECT COUNT(*) FROM gold.integrated_vehicle_cost_quality_result)"""
            )
        ).one()

        invalid_anp_run = _insert_run(
            fixture_connection,
            name="integrated_anp_missing_product_fixture",
        )
        pipeline_run_ids.add(invalid_anp_run)
        anp_dataset_versions.add(
            _seed_anp_gold(
                fixture_connection,
                run_id=invalid_anp_run,
                gasoline_price=Decimal("6.2000"),
                include_ethanol=False,
            )
        )
        with pytest.raises(IntegratedPublicationError, match="required fuel product"):
            run_integrated_vehicle_cost_pipeline(loader, options)
        counts_after_failure = fixture_connection.execute(
            text(
                """SELECT
                    (SELECT COUNT(*) FROM gold.integrated_vehicle_cost_dataset),
                    (SELECT COUNT(*) FROM gold.integrated_vehicle_cost_activation),
                    (SELECT COUNT(*) FROM gold.integrated_vehicle_cost_quality_result)"""
            )
        ).one()
        active_integrated = fixture_connection.execute(
            text(
                """SELECT dataset_version
                FROM gold.integrated_vehicle_cost_dataset
                WHERE is_active_shadow"""
            )
        ).scalar_one()
        assert counts_after_failure == counts_before_failure
        assert active_integrated == first.dataset_version

        captured_identifiers = _capture_publication_cycle_fixture(
            fixture_connection,
            integrated_dataset_versions=integrated_dataset_versions,
            pipeline_run_ids=pipeline_run_ids,
        )
        assert set(captured_identifiers["dataset_versions"]) == (
            integrated_dataset_versions
        )
        assert len(set(captured_identifiers["dataset_fingerprints"])) == 2
        assert len(captured_identifiers["snapshot_ids"]) == 4
        assert len(captured_identifiers["projection_ids"]) == 4
        assert len(captured_identifiers["quality_result_ids"]) == 72
        assert len(captured_identifiers["activation_event_ids"]) == 3
        assert len(captured_identifiers["rollback_event_ids"]) == 1

        guard_savepoint = fixture_connection.begin_nested()
        try:
            with pytest.raises(DBAPIError, match="downgrade blocked"):
                fixture_connection.execute(
                    text("SELECT gold.assert_integrated_downgrade_safe()")
                )
        finally:
            guard_savepoint.rollback()
    finally:
        try:
            if fixture_transaction.is_active:
                fixture_transaction.rollback()
        finally:
            fixture_connection.close()
            engine.dispose()

        verification_engine = create_engine(POSTGRESQL_URL, pool_pre_ping=True)
        try:
            with verification_engine.connect() as verification_connection:
                for table_name in (
                    "integrated_vehicle_cost_geography_request",
                    "integrated_vehicle_cost_snapshot",
                    "integrated_vehicle_cost_projection_snapshot",
                    "integrated_vehicle_cost_flex_comparison_snapshot",
                    "integrated_vehicle_cost_exclusion",
                    "integrated_vehicle_cost_quality_result",
                    "integrated_vehicle_cost_activation",
                    "integrated_vehicle_cost_invalidation",
                    "integrated_vehicle_cost_coverage_baseline",
                    "integrated_vehicle_cost_dataset",
                ):
                    assert verification_connection.execute(
                        text(
                            f"""SELECT COUNT(*) FROM gold.{table_name}
                            WHERE dataset_version=ANY(
                                CAST(:dataset_versions AS VARCHAR[])
                            )"""
                        ),
                        {"dataset_versions": sorted(integrated_dataset_versions)},
                    ).scalar_one() == 0
                for table_name, dataset_versions in (
                    ("vehicle_feature_dataset", fipe_dataset_versions),
                    ("vehicle_efficiency_dataset", pbev_dataset_versions),
                    ("anp_fuel_price_dataset", anp_dataset_versions),
                ):
                    assert verification_connection.execute(
                        text(
                            f"""SELECT COUNT(*) FROM gold.{table_name}
                            WHERE dataset_version=ANY(
                                CAST(:dataset_versions AS VARCHAR[])
                            )"""
                        ),
                        {"dataset_versions": sorted(dataset_versions)},
                    ).scalar_one() == 0
                assert verification_connection.execute(
                    text(
                        """SELECT COUNT(*) FROM meta.pipeline_run
                        WHERE pipeline_run_id=ANY(
                            CAST(:pipeline_run_ids AS UUID[])
                        )"""
                    ),
                    {"pipeline_run_ids": sorted(pipeline_run_ids, key=str)},
                ).scalar_one() == 0
                assert verification_connection.execute(
                    text(
                        """SELECT COUNT(*) FROM meta.pipeline_run
                        WHERE pipeline_run_id=:sentinel"""
                    ),
                    {"sentinel": sentinel_run_id},
                ).scalar_one() == 1
                verification_connection.execute(
                    text("SELECT gold.assert_integrated_downgrade_safe()")
                )
        finally:
            try:
                with verification_engine.begin() as sentinel_cleanup_connection:
                    deleted_sentinel = sentinel_cleanup_connection.execute(
                        text(
                            """DELETE FROM meta.pipeline_run
                            WHERE pipeline_run_id=:sentinel"""
                        ),
                        {"sentinel": sentinel_run_id},
                    )
                    assert deleted_sentinel.rowcount == 1
            finally:
                verification_engine.dispose()

        try:
            command.downgrade(config, "20260811_0008")
        finally:
            command.upgrade(config, "head")

        head_engine = create_engine(POSTGRESQL_URL, pool_pre_ping=True)
        try:
            with head_engine.connect() as head_connection:
                restored_head = head_connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
        finally:
            head_engine.dispose()
        assert restored_head == "20260811_0011"
