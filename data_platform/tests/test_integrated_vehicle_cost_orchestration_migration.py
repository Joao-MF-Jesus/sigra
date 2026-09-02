from contextlib import redirect_stdout
from importlib import import_module
from io import StringIO
from pathlib import Path

from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory


MIGRATION_MODULE = (
    "backend.alembic.versions."
    "20260811_0010_data_platform_integrated_vehicle_cost_orchestration"
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


def test_migration_extends_both_enum_columns_and_keeps_single_head():
    migration = import_module(MIGRATION_MODULE)
    assert migration.revision == "20260811_0010"
    assert migration.down_revision == "20260811_0009"
    sql = _offline_sql("postgresql", "upgrade")
    assert "integrated_vehicle_cost" in sql
    assert "meta.orchestration_run" in sql
    assert "start_step" in sql
    assert "meta.orchestration_step_run" in sql
    assert "step_name" in sql
    assert "CREATE VIEW gold.integrated_vehicle_cost_consumption_v1" in sql
    for marker in (
        "dataset.is_active_shadow",
        "dataset.status='shadow_published'",
        "dataset.hard_gate_status='passed'",
        "dataset.quality_status='passed'",
        "manual_review_required",
        "integrated_vehicle_cost_invalidation",
    ):
        assert marker in sql

    root = Path(__file__).parents[2]
    script = ScriptDirectory.from_config(Config(str(root / "backend" / "alembic.ini")))
    assert script.get_heads() == ["20260811_0012"]


def test_migration_is_sqlite_noop_and_downgrade_checks_both_history_columns():
    assert _offline_sql("sqlite", "upgrade") == ""
    assert _offline_sql("sqlite", "downgrade") == ""
    downgrade_sql = _offline_sql("postgresql", "downgrade")
    assert "start_step='integrated_vehicle_cost'" in downgrade_sql
    assert "step_name='integrated_vehicle_cost'" in downgrade_sql
    assert "downgrade blocked by history" in downgrade_sql
    assert "DROP VIEW gold.integrated_vehicle_cost_consumption_v1" in downgrade_sql
    assert "DELETE FROM" not in downgrade_sql
    assert "UPDATE meta.orchestration" not in downgrade_sql
    assert "'bronze','silver','gold','pbev','anp_fuel_prices'" in downgrade_sql
