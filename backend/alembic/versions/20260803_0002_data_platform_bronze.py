"""Cria a fundacao da plataforma de dados e a Bronze FIPE.

Revision ID: 20260803_0002
Revises: 20260723_0001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260803_0002"
down_revision: Union[str, None] = "20260723_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    # A plataforma analitica e exclusivamente PostgreSQL. O no-op mantem a
    # baseline SQLite e o startup atual completamente isolados desta estrutura.
    if not _is_postgresql():
        return

    for schema in ("meta", "bronze", "silver", "gold"):
        op.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))

    op.create_table(
        "pipeline_run",
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("pipeline_name", sa.String(100), nullable=False),
        sa.Column("pipeline_version", sa.String(40), nullable=False),
        sa.Column("dataset_version", sa.String(80), nullable=False),
        sa.Column("trigger_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("source_reference", sa.String(160)),
        sa.Column("records_received", sa.Integer, nullable=False, server_default="0"),
        sa.Column("records_inserted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("records_deduplicated", sa.Integer, nullable=False, server_default="0"),
        sa.Column("records_rejected", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_summary", sa.Text),
        sa.Column("git_commit", sa.String(40)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("trigger_type IN ('manual','scheduled','retry','backfill')", name="ck_pipeline_run_trigger"),
        sa.CheckConstraint("status IN ('running','succeeded','failed','partial','rejected')", name="ck_pipeline_run_status"),
        sa.CheckConstraint("records_received >= 0 AND records_inserted >= 0 AND records_deduplicated >= 0 AND records_rejected >= 0", name="ck_pipeline_run_counts"),
        sa.CheckConstraint("finished_at IS NULL OR finished_at >= started_at", name="ck_pipeline_run_timestamps"),
        sa.CheckConstraint("status <> 'succeeded' OR finished_at IS NOT NULL", name="ck_pipeline_run_succeeded_finished"),
        schema="meta",
    )
    op.create_table(
        "data_quality_issue",
        sa.Column("issue_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="CASCADE"), nullable=False),
        sa.Column("layer_name", sa.String(20), nullable=False),
        sa.Column("entity_name", sa.String(100), nullable=False),
        sa.Column("record_reference", sa.String(200)),
        sa.Column("rule_code", sa.String(80), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("details", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("resolution_status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("layer_name IN ('bronze','silver','gold')", name="ck_data_quality_layer"),
        sa.CheckConstraint("severity IN ('info','warning','error','critical')", name="ck_data_quality_severity"),
        sa.CheckConstraint("resolution_status IN ('open','accepted','resolved','ignored')", name="ck_data_quality_resolution"),
        sa.CheckConstraint("resolved_at IS NULL OR resolved_at >= created_at", name="ck_data_quality_timestamps"),
        schema="meta",
    )
    op.create_index("ix_data_quality_issue_run", "data_quality_issue", ["pipeline_run_id"], schema="meta")
    op.create_table(
        "fipe_raw",
        sa.Column("fipe_raw_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_name", sa.String(80), nullable=False),
        sa.Column("source_endpoint", sa.Text, nullable=False),
        sa.Column("vehicle_type", sa.String(20), nullable=False),
        sa.Column("source_record_key", sa.String(160), nullable=False),
        sa.Column("fipe_code", sa.String(20)),
        sa.Column("year_code", sa.String(30)),
        sa.Column("reference_month_raw", sa.String(80)),
        sa.Column("http_status", sa.Integer, nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB),
        sa.Column("payload_hash", sa.CHAR(64), nullable=False),
        sa.Column("schema_fingerprint", sa.CHAR(64)),
        sa.Column("raw_content_length", sa.Integer, nullable=False),
        sa.Column("ingestion_status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("vehicle_type IN ('car','motorcycle','truck')", name="ck_fipe_raw_vehicle_type"),
        sa.CheckConstraint("ingestion_status IN ('received','duplicate','invalid_json','http_error')", name="ck_fipe_raw_status"),
        sa.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="ck_fipe_raw_payload_hash"),
        sa.CheckConstraint("schema_fingerprint IS NULL OR schema_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_fipe_raw_schema_fingerprint"),
        sa.CheckConstraint("raw_content_length >= 0", name="ck_fipe_raw_content_length"),
        sa.CheckConstraint(
            "(ingestion_status = 'received' AND payload IS NOT NULL AND schema_fingerprint IS NOT NULL AND http_status BETWEEN 200 AND 299) OR "
            "(ingestion_status = 'invalid_json' AND payload IS NULL AND schema_fingerprint IS NULL AND http_status BETWEEN 200 AND 299) OR "
            "(ingestion_status = 'http_error' AND payload IS NULL AND schema_fingerprint IS NULL AND (http_status < 200 OR http_status >= 300)) OR "
            "ingestion_status = 'duplicate'",
            name="ck_fipe_raw_payload_by_status",
        ),
        sa.UniqueConstraint(
            "source_name",
            "source_endpoint",
            "http_status",
            "ingestion_status",
            "payload_hash",
            name="uq_fipe_raw_event_content",
        ),
        schema="bronze",
    )
    op.create_index("ix_fipe_raw_run", "fipe_raw", ["pipeline_run_id"], schema="bronze")
    op.create_index("ix_fipe_raw_identity_collected", "fipe_raw", ["fipe_code", "year_code", "collected_at"], schema="bronze")


def downgrade() -> None:
    if not _is_postgresql():
        return
    op.drop_index("ix_fipe_raw_identity_collected", table_name="fipe_raw", schema="bronze")
    op.drop_index("ix_fipe_raw_run", table_name="fipe_raw", schema="bronze")
    op.drop_table("fipe_raw", schema="bronze")
    op.drop_index("ix_data_quality_issue_run", table_name="data_quality_issue", schema="meta")
    op.drop_table("data_quality_issue", schema="meta")
    op.drop_table("pipeline_run", schema="meta")
    for schema in ("gold", "silver", "bronze", "meta"):
        op.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}"'))
