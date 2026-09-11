"""Executable join/lineage regressions against isolated, in-memory SQL fixtures."""
import inspect

import pytest
from sqlalchemy import create_engine, text

from app.integrated_gold.repository import IntegratedGoldStorageError
from app.recommendation_identity_repository import GoldRecommendationIdentityReader


def test_identity_reader_preserves_grain_eligibility_and_exact_fipe_lineage():
    # This is a SQL unit fixture, not a PostgreSQL validation or application fallback.
    engine = create_engine("sqlite://")
    try:
        with engine.connect() as connection:
            connection.execute(text("ATTACH DATABASE ':memory:' AS gold"))
            connection.execute(text("""CREATE TABLE gold.vehicle_features_snapshot (
                gold_record_id INTEGER, dataset_version TEXT, vehicle_sk INTEGER,
                fipe_code TEXT, year_code TEXT, brand_name TEXT, model_name TEXT,
                version_name TEXT, model_year INTEGER, fuel_type TEXT,
                transmission_type TEXT, source_vehicle_key TEXT)"""))
            connection.execute(text("""CREATE TABLE gold.integrated_vehicle_cost_snapshot (
                dataset_version TEXT, vehicle_sk INTEGER, fuel_scenario_code TEXT,
                requested_geography_level TEXT, requested_geography_key TEXT,
                anp_week_start TEXT, fipe_gold_record_id INTEGER)"""))
            connection.execute(text("""CREATE TABLE gold.eligible_fixture (
                dataset_version TEXT, vehicle_sk INTEGER, fuel_scenario_code TEXT,
                requested_geography_level TEXT, requested_geography_key TEXT,
                anp_week_start TEXT, fipe_source_dataset_version TEXT)"""))
            connection.execute(text("""CREATE VIEW gold.integrated_vehicle_cost_consumption_v1
                AS SELECT * FROM eligible_fixture"""))
            for record, dataset, vehicle, code in (
                (920, "fipe-v1", 810, "002150-4"),
                (921, "old-fipe", 810, "wrong"),
                (922, "fipe-v1", 999, "001486-9"),
                (923, "fipe-v1", 811, "002150-4"),
            ):
                connection.execute(text("""INSERT INTO gold.vehicle_features_snapshot VALUES
                    (:record,:dataset,:vehicle,:code,'2018-5','Toyota',
                    'ETIOS XLS 1.5 Flex 5p Aut.',NULL,2018,'flex',NULL,'key')"""),
                    dict(record=record, dataset=dataset, vehicle=vehicle, code=code))
            for fuel in ("gasoline_c_common", "ethanol_hydrated", "gasoline_c_additive"):
                connection.execute(text("""INSERT INTO gold.integrated_vehicle_cost_snapshot VALUES
                    ('integrated-v1',810,:fuel,'state','SP','2026-08-03',920)"""), dict(fuel=fuel))
                connection.execute(text("""INSERT INTO gold.eligible_fixture VALUES
                    ('integrated-v1',810,:fuel,'state','SP','2026-08-03','fipe-v1')"""), dict(fuel=fuel))
            # Historical, wrong-geography and wrong-version records cannot leak in.
            connection.execute(text("""INSERT INTO gold.integrated_vehicle_cost_snapshot VALUES
                ('old-integrated',999,'gasoline_c_common','state','SP','2026-08-03',922),
                ('integrated-v1',810,'gasoline_c_common','state','RJ','2026-08-03',921),
                ('integrated-v1',810,'gasoline_c_common','state','SP','2026-08-03',921),
                ('integrated-v1',810,'gasoline_c_common','state','SP','2026-08-03',922)"""))
            reader = GoldRecommendationIdentityReader(connection)
            rows = reader.recommendation_identities()
            assert len(rows) == 1  # three scenarios are one identity, not ambiguity
            assert rows[0]["gold_record_id"] == 920
            assert rows[0]["fipe_code"] == "002150-4"
            assert reader.recommendation_identities() == rows
            # A second genuinely published identity with the same FIPE key remains
            # visible to the resolver so it must reject ambiguity, never LIMIT 1.
            connection.execute(text("""INSERT INTO gold.integrated_vehicle_cost_snapshot VALUES
                ('integrated-v1',811,'gasoline_c_common','state','SP','2026-08-03',923)"""))
            connection.execute(text("""INSERT INTO gold.eligible_fixture VALUES
                ('integrated-v1',811,'gasoline_c_common','state','SP','2026-08-03','fipe-v1')"""))
            assert len(reader.recommendation_identities()) == 2
            assert connection.execute(text("SELECT COUNT(*) FROM gold.vehicle_features_snapshot")).scalar_one() == 4
    finally:
        engine.dispose()


def test_identity_reader_is_select_only_and_storage_failure_is_sanitized():
    source = inspect.getsource(GoldRecommendationIdentityReader).lower()
    assert "gold.integrated_vehicle_cost_consumption_v1" in source
    assert "feature.gold_record_id=snapshot.fipe_gold_record_id" in source
    assert "feature.dataset_version=consumption.fipe_source_dataset_version" in source
    assert "feature.vehicle_sk=consumption.vehicle_sk" in source
    for forbidden in ("insert into", "update ", "delete from", "commit(", " bronze.", " silver.", "limit 1"):
        assert forbidden not in source
    engine = create_engine("sqlite://")
    try:
        with engine.connect() as connection, pytest.raises(IntegratedGoldStorageError) as error:
            GoldRecommendationIdentityReader(connection).recommendation_identities()
        assert str(error.value) == "integrated Gold identity storage is unavailable"
    finally:
        engine.dispose()
