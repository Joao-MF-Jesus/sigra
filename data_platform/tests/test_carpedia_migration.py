from __future__ import annotations

from contextlib import redirect_stdout
from importlib import import_module
from io import StringIO
from pathlib import Path

from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory


MODULE = "backend.alembic.versions.20260811_0011_data_platform_carpedia_vehicle_specs"


def _offline_sql(dialect: str, operation: str) -> str:
    buffer = StringIO()
    context = MigrationContext.configure(
        dialect_name=dialect,
        opts={"as_sql": True, "output_buffer": buffer},
    )
    operations = Operations(context)
    migration = import_module(MODULE)
    original = migration.op
    migration.op = operations
    try:
        with redirect_stdout(buffer):
            getattr(migration, operation)()
    finally:
        migration.op = original
    return buffer.getvalue()


def test_carpedia_migration_chain_and_postgresql_contract():
    migration = import_module(MODULE)
    assert migration.revision == "20260811_0011"
    assert migration.down_revision == "20260811_0010"
    sql = _offline_sql("postgresql", "upgrade")
    for name in (
        "carpedia_source_asset",
        "carpedia_vehicle_raw",
        "carpedia_vehicle_mapping",
        "carpedia_vehicle_specification",
        "carpedia_vehicle_spec_dataset",
        "carpedia_vehicle_spec_snapshot",
        "carpedia_vehicle_spec_quality_result",
        "carpedia_vehicle_spec_dataset_event",
        "assert_carpedia_downgrade_safe",
    ):
        assert name in sql
    assert "approved_with_restrictions" in sql
    assert "database_json" in sql
    assert "CREATE TRIGGER" in sql

    root = Path(__file__).parents[2]
    script = ScriptDirectory.from_config(Config(str(root / "backend" / "alembic.ini")))
    assert script.get_heads() == ["20260811_0011"]


def test_carpedia_sqlite_noop_and_defensive_downgrade():
    assert _offline_sql("sqlite", "upgrade") == ""
    assert _offline_sql("sqlite", "downgrade") == ""
    sql = _offline_sql("postgresql", "downgrade")
    assert "assert_carpedia_downgrade_safe" in sql
    assert "DELETE FROM" not in sql
    assert "UPDATE " not in sql
