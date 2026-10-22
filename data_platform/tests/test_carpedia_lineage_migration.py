from __future__ import annotations

from contextlib import redirect_stdout
from importlib import import_module
from io import StringIO
from pathlib import Path

from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory


MODULE = "backend.alembic.versions.20260811_0012_data_platform_carpedia_lineage"


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


def test_carpedia_lineage_migration_is_additive_and_defensive():
    migration = import_module(MODULE)
    assert migration.revision == "20260811_0012"
    assert migration.down_revision == "20260811_0011"

    upgrade = _offline_sql("postgresql", "upgrade")
    assert "assert_carpedia_lineage_consistent" in upgrade
    assert "successor.supersedes_mapping_id=specification.mapping_decision_id" in upgrade
    assert "guard_carpedia_specification_lineage" in upgrade
    assert "Carpedia Gold snapshot lineage is not publishable" in upgrade
    assert "DROP CONSTRAINT uq_carpedia_spec_raw_fingerprint" in upgrade
    assert "uq_carpedia_spec_raw_mapping_fingerprint" in upgrade
    assert "raw_record_id, mapping_decision_id, normalized_fingerprint" in upgrade
    assert "HAVING COUNT(*)>1" in upgrade
    assert "DELETE FROM" not in upgrade
    assert "UPDATE " not in upgrade

    downgrade = _offline_sql("postgresql", "downgrade")
    assert "assert_carpedia_lineage_consistent" in downgrade
    assert "assert_carpedia_lineage_downgrade_safe" in downgrade
    assert "uq_carpedia_spec_raw_fingerprint" in downgrade
    assert "DELETE FROM" not in downgrade
    assert "UPDATE " not in downgrade


def test_carpedia_lineage_migration_is_sqlite_noop_and_single_head():
    assert _offline_sql("sqlite", "upgrade") == ""
    assert _offline_sql("sqlite", "downgrade") == ""
    root = Path(__file__).parents[2]
    script = ScriptDirectory.from_config(Config(str(root / "backend" / "alembic.ini")))
    assert script.get_heads() == ["20261005_0013"]
