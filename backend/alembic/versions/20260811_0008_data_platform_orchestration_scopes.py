"""Adiciona unidades PBEV e ANP aos metadados de orquestracao.

Revision ID: 20260811_0008
Revises: 20260811_0007
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260811_0008"
down_revision: Union[str, None] = "20260811_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _replace_step_enum(values: tuple[str, ...]) -> None:
    labels = ",".join(f"'{value}'" for value in values)
    op.execute(
        "ALTER TABLE meta.orchestration_run "
        "ALTER COLUMN start_step TYPE TEXT USING start_step::text"
    )
    op.execute(
        "ALTER TABLE meta.orchestration_step_run "
        "ALTER COLUMN step_name TYPE TEXT USING step_name::text"
    )
    op.execute("DROP TYPE meta.orchestration_step")
    op.execute(f"CREATE TYPE meta.orchestration_step AS ENUM ({labels})")
    op.execute(
        "ALTER TABLE meta.orchestration_run ALTER COLUMN start_step "
        "TYPE meta.orchestration_step "
        "USING start_step::meta.orchestration_step"
    )
    op.execute(
        "ALTER TABLE meta.orchestration_step_run ALTER COLUMN step_name "
        "TYPE meta.orchestration_step "
        "USING step_name::meta.orchestration_step"
    )


def upgrade() -> None:
    # A orquestracao analitica permanece PostgreSQL-only; SQLite e no-op.
    if not _is_postgresql():
        return
    _replace_step_enum(
        ("bronze", "silver", "gold", "pbev", "anp_fuel_prices")
    )


def downgrade() -> None:
    if not _is_postgresql():
        return
    op.execute(
        sa.text(
            """DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM meta.orchestration_run
                    WHERE start_step IN ('pbev','anp_fuel_prices')
                ) OR EXISTS (
                    SELECT 1 FROM meta.orchestration_step_run
                    WHERE step_name IN ('pbev','anp_fuel_prices')
                ) THEN
                    RAISE EXCEPTION
                        'orchestration scope downgrade blocked by PBEV or ANP history';
                END IF;
            END $$"""
        )
    )
    _replace_step_enum(("bronze", "silver", "gold"))
