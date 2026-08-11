from __future__ import annotations

from contextlib import redirect_stdout
from importlib import import_module
from io import StringIO

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext


MIGRATION_MODULE = "backend.alembic.versions.20260811_0007_data_platform_anp_fuel_prices"


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


def test_anp_migration_contract_and_postgresql_offline_ddl():
    migration = import_module(MIGRATION_MODULE)
    assert migration.revision == "20260811_0007"
    assert migration.down_revision == "20260810_0006"
    sql = _offline_sql("postgresql", "upgrade")
    for object_name in (
        "anp_source_asset",
        "anp_fuel_price_raw",
        "anp_fuel_price_observation",
        "anp_fuel_price_observation_current",
        "anp_fuel_price_dataset",
        "anp_fuel_price_snapshot",
        "anp_fuel_price_quality_result",
    ):
        assert object_name in sql
    assert "metadata_only" in sql
    assert "document_bytes" not in sql
    assert "CREATE TRIGGER" in sql
    assert "NUMERIC(12, 4)" in sql


def test_anp_migration_is_sqlite_noop_and_downgrade_is_scoped():
    assert _offline_sql("sqlite", "upgrade") == ""
    assert _offline_sql("sqlite", "downgrade") == ""
    sql = _offline_sql("postgresql", "downgrade")
    assert "ANP downgrade blocked: active shadow dataset exists" in sql
    assert "anp_fuel_price_dataset" in sql
    assert "vehicle_efficiency_dataset" not in sql
    assert "vehicle_feature_dataset" not in sql
