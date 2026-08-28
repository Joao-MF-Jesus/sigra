"""Cria metadados da orquestracao Bronze, Silver e Gold.

Revision ID: 20260810_0005
Revises: 20260803_0004
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260810_0005"
down_revision: Union[str, None] = "20260803_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


STATUS_VALUES = (
    "pending",
    "running",
    "succeeded",
    "partial",
    "failed",
    "skipped",
    "cancelled",
)
STEP_VALUES = ("bronze", "silver", "gold")
TRIGGER_VALUES = ("manual", "scheduled", "retry", "backfill")


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    # A orquestracao analitica e exclusivamente PostgreSQL. O no-op mantem o
    # banco SQLite operacional isolado da plataforma de dados.
    if not _is_postgresql():
        return

    op.execute(
        "CREATE TYPE meta.orchestration_status AS ENUM "
        "('pending','running','succeeded','partial','failed','skipped','cancelled')"
    )
    op.execute(
        "CREATE TYPE meta.orchestration_step AS ENUM ('bronze','silver','gold')"
    )
    op.execute(
        "CREATE TYPE meta.orchestration_trigger AS ENUM "
        "('manual','scheduled','retry','backfill')"
    )

    status_type = postgresql.ENUM(
        *STATUS_VALUES,
        name="orchestration_status",
        schema="meta",
        create_type=False,
    )
    step_type = postgresql.ENUM(
        *STEP_VALUES,
        name="orchestration_step",
        schema="meta",
        create_type=False,
    )
    trigger_type = postgresql.ENUM(
        *TRIGGER_VALUES,
        name="orchestration_trigger",
        schema="meta",
        create_type=False,
    )

    op.create_table(
        "orchestration_run",
        sa.Column(
            "orchestration_run_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("flow_name", sa.String(100), nullable=False),
        sa.Column("flow_version", sa.String(40), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("trigger_type", trigger_type, nullable=False),
        sa.Column("start_step", step_type, nullable=False),
        sa.Column("status", status_type, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "parameters",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error_summary", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_orchestration_run_timestamps",
        ),
        sa.CheckConstraint(
            "heartbeat_at >= started_at",
            name="ck_orchestration_run_heartbeat",
        ),
        sa.CheckConstraint(
            "(status IN ('pending','running') AND finished_at IS NULL) OR "
            "(status IN ('succeeded','partial','failed','skipped','cancelled') "
            "AND finished_at IS NOT NULL)",
            name="ck_orchestration_run_terminal",
        ),
        sa.UniqueConstraint(
            "flow_name",
            "idempotency_key",
            name="uq_orchestration_run_idempotency",
        ),
        schema="meta",
    )
    op.create_index(
        "ix_orchestration_run_status_heartbeat",
        "orchestration_run",
        ["status", "heartbeat_at"],
        schema="meta",
    )
    op.create_index(
        "ix_orchestration_run_created",
        "orchestration_run",
        ["flow_name", sa.text("created_at DESC")],
        schema="meta",
    )
    op.create_index(
        "uq_orchestration_run_active_flow",
        "orchestration_run",
        ["flow_name"],
        unique=True,
        schema="meta",
        postgresql_where=sa.text("status = 'running'"),
    )

    op.create_table(
        "orchestration_step_run",
        sa.Column(
            "orchestration_step_run_id",
            sa.BigInteger,
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "orchestration_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "meta.orchestration_run.orchestration_run_id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("step_name", step_type, nullable=False),
        sa.Column("attempt_number", sa.Integer, nullable=False),
        sa.Column("status", status_type, nullable=False),
        sa.Column(
            "pipeline_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "depends_on_step_run_id",
            sa.BigInteger,
            sa.ForeignKey(
                "meta.orchestration_step_run.orchestration_step_run_id",
                ondelete="SET NULL",
            ),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "metrics_summary",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error_summary", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "attempt_number >= 1",
            name="ck_orchestration_step_attempt",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_orchestration_step_timestamps",
        ),
        sa.CheckConstraint(
            "(status IN ('pending','running') AND finished_at IS NULL) OR "
            "(status IN ('succeeded','partial','failed','skipped','cancelled') "
            "AND finished_at IS NOT NULL)",
            name="ck_orchestration_step_terminal",
        ),
        sa.CheckConstraint(
            "depends_on_step_run_id IS NULL OR "
            "depends_on_step_run_id <> orchestration_step_run_id",
            name="ck_orchestration_step_dependency",
        ),
        sa.UniqueConstraint(
            "orchestration_run_id",
            "step_name",
            "attempt_number",
            name="uq_orchestration_step_attempt",
        ),
        schema="meta",
    )
    op.create_index(
        "ix_orchestration_step_run_status",
        "orchestration_step_run",
        ["orchestration_run_id", "step_name", "status"],
        schema="meta",
    )
    op.create_index(
        "ix_orchestration_step_pipeline_run",
        "orchestration_step_run",
        ["pipeline_run_id"],
        schema="meta",
        postgresql_where=sa.text("pipeline_run_id IS NOT NULL"),
    )
    op.create_index(
        "ix_orchestration_step_dependency",
        "orchestration_step_run",
        ["depends_on_step_run_id"],
        schema="meta",
        postgresql_where=sa.text("depends_on_step_run_id IS NOT NULL"),
    )

    op.execute(
        sa.text(
            """CREATE FUNCTION meta.touch_orchestration_updated_at()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                NEW.updated_at = CURRENT_TIMESTAMP;
                RETURN NEW;
            END
            $$"""
        )
    )
    for table_name in ("orchestration_run", "orchestration_step_run"):
        op.execute(
            sa.text(
                f"""CREATE TRIGGER trg_{table_name}_updated_at
                BEFORE UPDATE ON meta.{table_name}
                FOR EACH ROW
                EXECUTE FUNCTION meta.touch_orchestration_updated_at()"""
            )
        )


def downgrade() -> None:
    if not _is_postgresql():
        return

    for table_name in ("orchestration_step_run", "orchestration_run"):
        op.execute(
            sa.text(
                f"DROP TRIGGER trg_{table_name}_updated_at ON meta.{table_name}"
            )
        )
    op.execute(sa.text("DROP FUNCTION meta.touch_orchestration_updated_at()"))
    op.drop_index(
        "ix_orchestration_step_dependency",
        table_name="orchestration_step_run",
        schema="meta",
    )
    op.drop_index(
        "ix_orchestration_step_pipeline_run",
        table_name="orchestration_step_run",
        schema="meta",
    )
    op.drop_index(
        "ix_orchestration_step_run_status",
        table_name="orchestration_step_run",
        schema="meta",
    )
    op.drop_table("orchestration_step_run", schema="meta")
    op.drop_index(
        "uq_orchestration_run_active_flow",
        table_name="orchestration_run",
        schema="meta",
    )
    op.drop_index(
        "ix_orchestration_run_created",
        table_name="orchestration_run",
        schema="meta",
    )
    op.drop_index(
        "ix_orchestration_run_status_heartbeat",
        table_name="orchestration_run",
        schema="meta",
    )
    op.drop_table("orchestration_run", schema="meta")
    op.execute("DROP TYPE meta.orchestration_trigger")
    op.execute("DROP TYPE meta.orchestration_step")
    op.execute("DROP TYPE meta.orchestration_status")
