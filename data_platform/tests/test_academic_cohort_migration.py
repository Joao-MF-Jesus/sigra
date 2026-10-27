import importlib
import io
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import pytest


@pytest.mark.parametrize('dialect', ['postgresql','sqlite'])
def test_additive_migration_keeps_operational_and_gold_tables_untouched(dialect):
    migration = importlib.import_module('backend.alembic.versions.20261005_0013_academic_cohort_v6')
    stream = io.StringIO()
    context = MigrationContext.configure(dialect_name=dialect, opts={'as_sql': True,'output_buffer':stream})
    with Operations.context(context):
        migration.upgrade()
    sql = stream.getvalue()
    assert migration.down_revision == '20260811_0012'
    if dialect == 'sqlite':
        assert sql == ''
        return
    for name in ('academic.cohort_snapshot','academic.cohort_vehicle','academic.cohort_evaluation','ix_academic_evaluation_filter','uq_academic_vehicle_fipe'):
        assert name in sql
    for prohibited in ('TRUNCATE', 'DELETE FROM', 'UPDATE ', 'DROP ', 'INSERT INTO', 'gold.', 'public.vehicles'):
        assert prohibited not in sql
    assert 'NOT operationally_active AND NOT recommended' in sql


def test_single_new_head():
    config = Config(str(Path(__file__).resolve().parents[2]/'backend/alembic.ini'))
    assert ScriptDirectory.from_config(config).get_heads() == ['20261005_0013']
