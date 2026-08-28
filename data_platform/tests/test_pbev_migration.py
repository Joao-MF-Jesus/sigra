from __future__ import annotations

from contextlib import redirect_stdout
from importlib import import_module
from io import StringIO

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext


def _offline_sql(dialect_name: str, operation: str) -> str:
    buffer = StringIO()
    context = MigrationContext.configure(
        dialect_name=dialect_name,
        opts={"as_sql": True, "output_buffer": buffer},
    )
    operations = Operations(context)
    migration = import_module(
        "backend.alembic.versions.20260810_0006_data_platform_pbev_efficiency"
    )
    original = migration.op
    migration.op = operations
    try:
        with redirect_stdout(buffer):
            getattr(migration, operation)()
    finally:
        migration.op = original
    return buffer.getvalue()


def test_migration_contract_and_postgresql_offline_ddl():
    migration = import_module(
        "backend.alembic.versions.20260810_0006_data_platform_pbev_efficiency"
    )
    assert migration.revision == "20260810_0006"
    assert migration.down_revision == "20260810_0005"
    sql = _offline_sql("postgresql", "upgrade")
    for object_name in (
        "pbev_source_asset",
        "pbev_raw_row",
        "pbev_vehicle_mapping",
        "vehicle_efficiency_observation",
        "pbev_vehicle_mapping_current",
        "vehicle_efficiency_dataset",
        "vehicle_efficiency_snapshot",
        "vehicle_efficiency_quality_result",
    ):
        assert object_name in sql
    assert "document_bytes" in sql
    assert "metadata_only" in sql
    assert "CREATE TRIGGER" in sql


def test_migration_is_sqlite_noop_and_downgrade_is_scoped():
    assert _offline_sql("sqlite", "upgrade") == ""
    assert _offline_sql("sqlite", "downgrade") == ""
    sql = _offline_sql("postgresql", "downgrade")
    assert "PBEV downgrade blocked: active shadow dataset exists" in sql
    assert "vehicle_efficiency_dataset" in sql
    assert "vehicle_feature_dataset" not in sql
