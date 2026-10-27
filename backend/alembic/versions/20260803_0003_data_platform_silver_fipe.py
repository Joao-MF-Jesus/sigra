"""Cria a primeira fatia Silver para identidade e precos FIPE.

Revision ID: 20260803_0003
Revises: 20260803_0002
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260803_0003"
down_revision: Union[str, None] = "20260803_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    # A camada analitica continua exclusivamente PostgreSQL. O no-op preserva
    # o banco SQLite operacional e os testes atuais do SIGRA.
    if not _is_postgresql():
        return

    op.create_table(
        "vehicle_identity",
        sa.Column("vehicle_sk", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("vehicle_type", sa.String(20), nullable=False),
        sa.Column("brand_name", sa.String(80), nullable=False),
        sa.Column("model_name", sa.String(120), nullable=False),
        sa.Column("version_name", sa.String(180)),
        sa.Column("model_year", sa.SmallInteger),
        sa.Column("is_zero_km", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("fuel_type", sa.String(30), nullable=False),
        sa.Column("transmission_type", sa.String(30)),
        sa.Column("canonical_key", sa.CHAR(64), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("is_current", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "bronze_record_id",
            sa.BigInteger,
            sa.ForeignKey("bronze.fipe_raw.fipe_raw_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "pipeline_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_by_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "updated_by_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "vehicle_type IN ('car','motorcycle','truck')",
            name="ck_vehicle_identity_type",
        ),
        sa.CheckConstraint(
            "fuel_type IN ('gasoline','ethanol','flex','diesel','electric','hybrid','cng')",
            name="ck_vehicle_identity_fuel",
        ),
        sa.CheckConstraint(
            "(is_zero_km AND model_year IS NULL) OR "
            "(NOT is_zero_km AND model_year BETWEEN 1900 AND 2100)",
            name="ck_vehicle_identity_year",
        ),
        sa.CheckConstraint(
            "canonical_key ~ '^[0-9a-f]{64}$'",
            name="ck_vehicle_identity_canonical_key",
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_vehicle_identity_validity",
        ),
        sa.CheckConstraint(
            "(is_current AND valid_to IS NULL) OR "
            "(NOT is_current AND valid_to IS NOT NULL)",
            name="ck_vehicle_identity_current",
        ),
        sa.UniqueConstraint(
            "canonical_key",
            "valid_from",
            name="uq_vehicle_identity_version",
        ),
        schema="silver",
    )
    op.create_index(
        "uq_vehicle_identity_current",
        "vehicle_identity",
        ["canonical_key"],
        unique=True,
        schema="silver",
        postgresql_where=sa.text("is_current"),
    )
    op.create_index(
        "ix_vehicle_identity_lookup",
        "vehicle_identity",
        ["vehicle_type", "brand_name", "model_name", "model_year", "fuel_type"],
        schema="silver",
    )

    op.create_table(
        "vehicle_source_mapping",
        sa.Column("mapping_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "vehicle_sk",
            sa.BigInteger,
            sa.ForeignKey("silver.vehicle_identity.vehicle_sk", ondelete="RESTRICT"),
        ),
        sa.Column("source_name", sa.String(80), nullable=False),
        sa.Column("source_vehicle_key", sa.String(160), nullable=False),
        sa.Column("fipe_code", sa.String(20), nullable=False),
        sa.Column("year_code", sa.String(30), nullable=False),
        sa.Column("mapping_status", sa.String(20), nullable=False),
        sa.Column("match_method", sa.String(30)),
        sa.Column("confidence", sa.Numeric(5, 2)),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column(
            "pipeline_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "bronze_record_id",
            sa.BigInteger,
            sa.ForeignKey("bronze.fipe_raw.fipe_raw_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("review_notes", sa.Text),
        sa.CheckConstraint(
            "mapping_status IN ('matched','pending','ambiguous','rejected')",
            name="ck_vehicle_source_mapping_status",
        ),
        sa.CheckConstraint(
            "match_method IS NULL OR match_method IN ('manual','exact','rule','reviewed')",
            name="ck_vehicle_source_mapping_method",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 100",
            name="ck_vehicle_source_mapping_confidence",
        ),
        sa.CheckConstraint(
            "(mapping_status = 'matched' AND vehicle_sk IS NOT NULL AND "
            "match_method IS NOT NULL AND confidence IS NOT NULL) OR "
            "(mapping_status IN ('pending','ambiguous','rejected') AND vehicle_sk IS NULL)",
            name="ck_vehicle_source_mapping_target",
        ),
        sa.CheckConstraint(
            "(mapping_status <> 'ambiguous' AND "
            "COALESCE(match_method, '') NOT IN ('manual','reviewed')) OR "
            "NULLIF(BTRIM(review_notes), '') IS NOT NULL",
            name="ck_vehicle_source_mapping_review_notes",
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_vehicle_source_mapping_validity",
        ),
        sa.UniqueConstraint(
            "bronze_record_id",
            name="uq_vehicle_source_mapping_bronze",
        ),
        sa.UniqueConstraint(
            "source_name",
            "source_vehicle_key",
            "valid_from",
            name="uq_vehicle_source_mapping_version",
        ),
        schema="silver",
    )
    op.create_index(
        "uq_vehicle_source_mapping_current_key",
        "vehicle_source_mapping",
        ["source_name", "source_vehicle_key"],
        unique=True,
        schema="silver",
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.create_index(
        "uq_vehicle_source_mapping_current_fipe",
        "vehicle_source_mapping",
        ["source_name", "fipe_code", "year_code"],
        unique=True,
        schema="silver",
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.create_index(
        "ix_vehicle_source_mapping_vehicle",
        "vehicle_source_mapping",
        ["vehicle_sk"],
        schema="silver",
        postgresql_where=sa.text("vehicle_sk IS NOT NULL"),
    )
    op.create_index(
        "ix_vehicle_source_mapping_review",
        "vehicle_source_mapping",
        ["mapping_status", "source_name"],
        schema="silver",
        postgresql_where=sa.text("valid_to IS NULL"),
    )

    op.create_table(
        "vehicle_price_history",
        sa.Column("vehicle_price_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "vehicle_sk",
            sa.BigInteger,
            sa.ForeignKey("silver.vehicle_identity.vehicle_sk", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_name", sa.String(80), nullable=False),
        sa.Column(
            "source_mapping_id",
            sa.BigInteger,
            sa.ForeignKey("silver.vehicle_source_mapping.mapping_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("price_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False, server_default="BRL"),
        sa.Column("reference_month", sa.Date, nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("is_current", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("data_confidence", sa.Numeric(5, 2), nullable=False),
        sa.Column(
            "bronze_record_id",
            sa.BigInteger,
            sa.ForeignKey("bronze.fipe_raw.fipe_raw_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "pipeline_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.CheckConstraint("price_amount > 0", name="ck_vehicle_price_positive"),
        sa.CheckConstraint("currency = 'BRL'", name="ck_vehicle_price_currency"),
        sa.CheckConstraint(
            "EXTRACT(DAY FROM reference_month) = 1",
            name="ck_vehicle_price_reference_month",
        ),
        sa.CheckConstraint(
            "data_confidence BETWEEN 0 AND 100",
            name="ck_vehicle_price_confidence",
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_vehicle_price_validity",
        ),
        sa.CheckConstraint(
            "(is_current AND valid_to IS NULL) OR "
            "(NOT is_current AND valid_to IS NOT NULL)",
            name="ck_vehicle_price_current",
        ),
        sa.UniqueConstraint("bronze_record_id", name="uq_vehicle_price_bronze"),
        sa.UniqueConstraint(
            "vehicle_sk",
            "source_name",
            "reference_month",
            name="uq_vehicle_price_vehicle_source_month",
        ),
        schema="silver",
    )
    op.create_index(
        "uq_vehicle_price_current",
        "vehicle_price_history",
        ["vehicle_sk", "source_name"],
        unique=True,
        schema="silver",
        postgresql_where=sa.text("is_current"),
    )
    op.create_index(
        "ix_vehicle_price_reference",
        "vehicle_price_history",
        ["vehicle_sk", "source_name", sa.text("reference_month DESC")],
        schema="silver",
    )
    op.create_index(
        "ix_vehicle_price_mapping",
        "vehicle_price_history",
        ["source_mapping_id"],
        schema="silver",
    )

    op.create_index(
        "uq_data_quality_issue_open_silver",
        "data_quality_issue",
        ["layer_name", "entity_name", "record_reference", "rule_code"],
        unique=True,
        schema="meta",
        postgresql_where=sa.text(
            "layer_name = 'silver' AND resolution_status = 'open'"
        ),
    )


def downgrade() -> None:
    if not _is_postgresql():
        return

    op.drop_index(
        "uq_data_quality_issue_open_silver",
        table_name="data_quality_issue",
        schema="meta",
    )
    op.drop_index(
        "ix_vehicle_price_mapping",
        table_name="vehicle_price_history",
        schema="silver",
    )
    op.drop_index(
        "ix_vehicle_price_reference",
        table_name="vehicle_price_history",
        schema="silver",
    )
    op.drop_index(
        "uq_vehicle_price_current",
        table_name="vehicle_price_history",
        schema="silver",
    )
    op.drop_table("vehicle_price_history", schema="silver")
    op.drop_index(
        "ix_vehicle_source_mapping_review",
        table_name="vehicle_source_mapping",
        schema="silver",
    )
    op.drop_index(
        "ix_vehicle_source_mapping_vehicle",
        table_name="vehicle_source_mapping",
        schema="silver",
    )
    op.drop_index(
        "uq_vehicle_source_mapping_current_fipe",
        table_name="vehicle_source_mapping",
        schema="silver",
    )
    op.drop_index(
        "uq_vehicle_source_mapping_current_key",
        table_name="vehicle_source_mapping",
        schema="silver",
    )
    op.drop_table("vehicle_source_mapping", schema="silver")
    op.drop_index(
        "ix_vehicle_identity_lookup",
        table_name="vehicle_identity",
        schema="silver",
    )
    op.drop_index(
        "uq_vehicle_identity_current",
        table_name="vehicle_identity",
        schema="silver",
    )
    op.drop_table("vehicle_identity", schema="silver")
