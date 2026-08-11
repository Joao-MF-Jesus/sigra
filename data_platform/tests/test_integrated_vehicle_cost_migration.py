from __future__ import annotations

from contextlib import redirect_stdout
from importlib import import_module
from io import StringIO
import re

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext


MIGRATION_MODULE = (
    "backend.alembic.versions."
    "20260811_0009_data_platform_integrated_vehicle_cost"
)


def _offline_sql(dialect_name: str, operation: str) -> str:
    buffer = StringIO()
    context = MigrationContext.configure(
        dialect_name=dialect_name,
        opts={"as_sql": True, "output_buffer": buffer},
    )
    operations = Operations(context)
    migration = import_module(MIGRATION_MODULE)
    original = migration.op
    migration.op = operations
    try:
        with redirect_stdout(buffer):
            getattr(migration, operation)()
    finally:
        migration.op = original
    return buffer.getvalue()


def test_integrated_migration_contract_and_canonical_objects():
    migration = import_module(MIGRATION_MODULE)
    assert migration.revision == "20260811_0009"
    assert migration.down_revision == "20260811_0008"
    sql = _offline_sql("postgresql", "upgrade")
    for object_name in (
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
    ):
        assert object_name in sql
    assert "gold.vehicle_features_snapshot(gold_record_id)" in sql
    assert "gold.vehicle_efficiency_snapshot(gold_record_id)" in sql
    assert "gold.anp_fuel_price_snapshot(snapshot_id)" in sql
    assert "gold.vehicle_feature_snapshot" not in sql
    assert "dataset_version VARCHAR(96)" in sql
    assert "fipe_source_dataset_version VARCHAR(80)" in sql


def test_snapshot_and_projection_grains_are_not_conflated():
    sql = _offline_sql("postgresql", "upgrade")
    snapshot_sql = sql.split(
        "CREATE TABLE gold.integrated_vehicle_cost_snapshot", 1
    )[1].split("CREATE TABLE gold.integrated_vehicle_cost_projection_snapshot", 1)[0]
    projection_sql = sql.split(
        "CREATE TABLE gold.integrated_vehicle_cost_projection_snapshot", 1
    )[1].split("CREATE TABLE gold.integrated_vehicle_cost_flex_comparison_snapshot", 1)[0]
    assert re.search(r"(?m)^\s*scenario_code\s", snapshot_sql) is None
    assert "fuel_scenario_code" in snapshot_sql
    assert "scenario_code='mixed_1000_v1'" in projection_sql
    assert "UNIQUE (dataset_version,snapshot_id,scenario_code)" in projection_sql
    assert "monthly_distance_km=1000.00" in projection_sql
    assert "annual_distance_km=12000.00" in projection_sql


def test_reconciliation_uses_complete_sets_and_projection_is_publication_source():
    sql = _offline_sql("postgresql", "upgrade")
    function_sql = sql.split("CREATE FUNCTION gold.reconcile_integrated_sets", 1)[1]
    assert "EXCEPT" in function_sql
    assert "UNION" in function_sql
    assert "INTERSECT" in function_sql
    assert "integrated_vehicle_cost_projection_snapshot AS projection" in function_sql
    assert "JOIN gold.integrated_vehicle_cost_snapshot AS snapshot" in function_sql
    assert "missing_keys JSONB" in function_sql
    assert "unexpected_keys JSONB" in function_sql


def test_quality_policy_activation_and_regression_contracts_are_explicit():
    sql = _offline_sql("postgresql", "upgrade")
    assert sql.count("'hard_gate','critical',TRUE,'passed'") == 29
    assert sql.count("'statistical_control','info',TRUE,'not_calibrated'") == 7
    for rule_code in (
        "INTEGRATED_COUNTS_RECONCILED",
        "INTEGRATED_VEHICLE_COVERAGE_RECONCILED",
        "INTEGRATED_SCENARIO_COVERAGE_RECONCILED",
        "INTEGRATED_COVERAGE_NON_REGRESSION",
    ):
        assert rule_code in sql
    assert "dataset_version,quality_policy_version,rule_code" in sql
    assert "coverage_regression_status IN ('not_applicable','passed','manual_review_required')" in sql
    assert "coverage_regression_status='manual_review_required'" in sql
    assert "activation_type IN ('publish','replace','rollback')" in sql
    assert "activation_type='publish' AND previous_dataset_version IS NULL" in sql
    assert "DEFERRABLE INITIALLY DEFERRED" in sql


def test_exclusions_are_gold_only_bidirectionally_guarded_and_evidence_is_immutable():
    sql = _offline_sql("postgresql", "upgrade")
    assert "fipe_gold_record_id" in sql
    assert "pbev_gold_record_id" in sql
    assert "silver.vehicle_identity" not in sql
    assert "Integrated projection conflicts with an exclusion" in sql
    assert "Integrated exclusion conflicts with a projection" in sql
    assert "Integrated analytical evidence is immutable" in sql
    assert "Integrated vehicle cost downgrade blocked: datasets or evidence exist" in sql
    assert "assert_integrated_downgrade_safe" in _offline_sql("postgresql", "downgrade")


def test_integrated_migration_is_sqlite_noop_and_downgrade_is_scoped():
    assert _offline_sql("sqlite", "upgrade") == ""
    assert _offline_sql("sqlite", "downgrade") == ""
    downgrade_sql = _offline_sql("postgresql", "downgrade")
    assert "integrated_vehicle_cost_dataset" in downgrade_sql
    assert "DROP TABLE gold.vehicle_feature_dataset" not in downgrade_sql
    assert "DROP TABLE gold.vehicle_efficiency_dataset" not in downgrade_sql
    assert "DROP TABLE gold.anp_fuel_price_dataset" not in downgrade_sql
