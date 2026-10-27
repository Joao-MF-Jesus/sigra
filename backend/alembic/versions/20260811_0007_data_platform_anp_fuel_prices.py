"""Cria o pipeline shadow de precos de combustiveis da ANP.

Revision ID: 20260811_0007
Revises: 20260810_0006
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260811_0007"
down_revision: Union[str, None] = "20260810_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _create_bronze() -> None:
    op.create_table(
        "anp_source_asset",
        sa.Column("asset_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_name", sa.String(60), nullable=False, server_default="anp_fuel_prices"),
        sa.Column("source_reference", sa.String(120), nullable=False),
        sa.Column("official_page_url", sa.Text, nullable=False),
        sa.Column("download_url_sanitized", sa.Text, nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("period_start", sa.Date),
        sa.Column("period_end", sa.Date),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("http_status", sa.Integer, nullable=False),
        sa.Column("content_type", sa.String(120), nullable=False),
        sa.Column("byte_length", sa.BigInteger, nullable=False),
        sa.Column("etag", sa.String(255)),
        sa.Column("last_modified", sa.String(255)),
        sa.Column("sha256", sa.CHAR(64), nullable=False),
        sa.Column("schema_fingerprint", sa.CHAR(64), nullable=False),
        sa.Column("storage_mode", sa.String(20), nullable=False, server_default="metadata_only"),
        sa.Column("ingestion_status", sa.String(20), nullable=False),
        sa.Column("error_sanitized", sa.Text),
        sa.Column("technical_metadata", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("source_name='anp_fuel_prices'", name="ck_anp_asset_source"),
        sa.CheckConstraint("(period_start IS NULL AND period_end IS NULL) OR (period_start IS NOT NULL AND period_end IS NOT NULL AND period_start<=period_end)", name="ck_anp_asset_period"),
        sa.CheckConstraint("ingestion_status<>'accepted' OR (period_start IS NOT NULL AND period_end IS NOT NULL)", name="ck_anp_asset_accepted_period"),
        sa.CheckConstraint("http_status BETWEEN 200 AND 299", name="ck_anp_asset_http"),
        sa.CheckConstraint("byte_length>0", name="ck_anp_asset_size"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$' AND schema_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_anp_asset_hashes"),
        sa.CheckConstraint("storage_mode='metadata_only'", name="ck_anp_asset_storage"),
        sa.CheckConstraint("ingestion_status IN ('accepted','quarantined','rejected')", name="ck_anp_asset_status"),
        sa.UniqueConstraint("source_name", "source_reference", "sha256", name="uq_anp_asset_content"),
        schema="bronze",
    )
    op.create_index("ix_anp_asset_run", "anp_source_asset", ["pipeline_run_id"], schema="bronze")
    op.create_index("ix_anp_asset_period", "anp_source_asset", ["period_end", "ingestion_status"], schema="bronze")

    op.create_table(
        "anp_fuel_price_raw",
        sa.Column("anp_raw_row_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("asset_id", sa.BigInteger, sa.ForeignKey("bronze.anp_source_asset.asset_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("line_number", sa.Integer, nullable=False),
        sa.Column("parser_version", sa.String(40), nullable=False),
        sa.Column("layout_fingerprint", sa.CHAR(64), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB, nullable=False),
        sa.Column("row_hash", sa.CHAR(64), nullable=False),
        sa.Column("extraction_status", sa.String(20), nullable=False),
        sa.Column("error_sanitized", sa.Text),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("line_number>1", name="ck_anp_raw_line"),
        sa.CheckConstraint("layout_fingerprint ~ '^[0-9a-f]{64}$' AND row_hash ~ '^[0-9a-f]{64}$'", name="ck_anp_raw_hashes"),
        sa.CheckConstraint("jsonb_typeof(raw_payload)='object'", name="ck_anp_raw_payload"),
        sa.CheckConstraint("extraction_status IN ('parsed','invalid_row','duplicate')", name="ck_anp_raw_status"),
        sa.UniqueConstraint("asset_id", "line_number", name="uq_anp_raw_asset_line"),
        schema="bronze",
    )
    op.create_index("ix_anp_raw_asset", "anp_fuel_price_raw", ["asset_id", "line_number"], schema="bronze")
    op.create_index("ix_anp_raw_hash", "anp_fuel_price_raw", ["row_hash"], schema="bronze")


def _create_silver() -> None:
    op.create_table(
        "anp_fuel_price_observation",
        sa.Column("observation_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("anp_raw_row_id", sa.BigInteger, sa.ForeignKey("bronze.anp_fuel_price_raw.anp_raw_row_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("asset_id", sa.BigInteger, sa.ForeignKey("bronze.anp_source_asset.asset_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("observation_key", sa.CHAR(64), nullable=False),
        sa.Column("content_hash", sa.CHAR(64), nullable=False),
        sa.Column("supersedes_observation_id", sa.BigInteger, sa.ForeignKey("silver.anp_fuel_price_observation.observation_id", ondelete="RESTRICT"), unique=True),
        sa.Column("product_code", sa.String(40), nullable=False),
        sa.Column("currency_code", sa.CHAR(3), nullable=False, server_default="BRL"),
        sa.Column("unit_code", sa.String(20), nullable=False),
        sa.Column("sale_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("purchase_price", sa.Numeric(12, 4)),
        sa.Column("flag_name", sa.String(160)),
        sa.Column("legal_name", sa.String(255), nullable=False),
        sa.Column("establishment_key", sa.CHAR(64), nullable=False),
        sa.Column("cnpj_hash", sa.CHAR(64)),
        sa.Column("street_name", sa.String(255)),
        sa.Column("street_number", sa.String(60)),
        sa.Column("address_complement", sa.String(160)),
        sa.Column("neighborhood", sa.String(160)),
        sa.Column("postal_code", sa.String(16)),
        sa.Column("municipality_name", sa.String(160), nullable=False),
        sa.Column("municipality_normalized", sa.String(160), nullable=False),
        sa.Column("state_code", sa.CHAR(2), nullable=False),
        sa.Column("region_code", sa.CHAR(2), nullable=False),
        sa.Column("collection_date", sa.Date, nullable=False),
        sa.Column("week_start", sa.Date, nullable=False),
        sa.Column("week_end", sa.Date, nullable=False),
        sa.Column("identity_method", sa.String(30), nullable=False),
        sa.Column("quality_status", sa.String(20), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("observation_key ~ '^[0-9a-f]{64}$' AND content_hash ~ '^[0-9a-f]{64}$' AND establishment_key ~ '^[0-9a-f]{64}$'", name="ck_anp_observation_hashes"),
        sa.CheckConstraint("cnpj_hash IS NULL OR cnpj_hash ~ '^[0-9a-f]{64}$'", name="ck_anp_observation_cnpj_hash"),
        sa.CheckConstraint("product_code IN ('gasoline_c_common','gasoline_c_additized','ethanol_hydrated')", name="ck_anp_observation_product"),
        sa.CheckConstraint("currency_code='BRL' AND unit_code='liter'", name="ck_anp_observation_unit"),
        sa.CheckConstraint("sale_price>0 AND (purchase_price IS NULL OR purchase_price>=0)", name="ck_anp_observation_prices"),
        sa.CheckConstraint("state_code IN ('AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG','PA','PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO')", name="ck_anp_observation_state"),
        sa.CheckConstraint("region_code IN ('N','NE','CO','SE','S')", name="ck_anp_observation_region"),
        sa.CheckConstraint("week_start<=collection_date AND collection_date<=week_end AND week_end=week_start+6", name="ck_anp_observation_week"),
        sa.CheckConstraint("identity_method IN ('cnpj_hash','fallback_identity')", name="ck_anp_observation_identity"),
        sa.CheckConstraint("quality_status IN ('passed','warning','rejected')", name="ck_anp_observation_quality"),
        sa.CheckConstraint("supersedes_observation_id IS NULL OR supersedes_observation_id<>observation_id", name="ck_anp_observation_supersedes"),
        sa.UniqueConstraint("anp_raw_row_id", name="uq_anp_observation_raw"),
        schema="silver",
    )
    op.create_index("ix_anp_observation_key", "anp_fuel_price_observation", ["observation_key", "collection_date"], schema="silver")
    op.create_index("ix_anp_observation_geo", "anp_fuel_price_observation", ["product_code", "week_start", "state_code", "municipality_normalized"], schema="silver")
    op.execute(sa.text("""CREATE VIEW silver.anp_fuel_price_observation_current AS
        SELECT observation.*
        FROM silver.anp_fuel_price_observation AS observation
        WHERE NOT EXISTS (
            SELECT 1 FROM silver.anp_fuel_price_observation AS successor
            WHERE successor.supersedes_observation_id=observation.observation_id
        )"""))


def _create_gold() -> None:
    op.create_table(
        "anp_fuel_price_dataset",
        sa.Column("dataset_version", sa.String(80), primary_key=True),
        sa.Column("publication_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("source_asset_manifest", postgresql.JSONB, nullable=False),
        sa.Column("source_asset_set_hash", sa.CHAR(64), nullable=False),
        sa.Column("parser_version", sa.String(40), nullable=False),
        sa.Column("normalizer_version", sa.String(40), nullable=False),
        sa.Column("aggregation_version", sa.String(40), nullable=False),
        sa.Column("reference_period_start", sa.Date, nullable=False),
        sa.Column("reference_period_end", sa.Date, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("is_active_shadow", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("observation_count", sa.Integer, nullable=False),
        sa.Column("snapshot_count", sa.Integer, nullable=False),
        sa.Column("dataset_fingerprint", sa.CHAR(64), nullable=False),
        sa.Column("quality_status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("source_asset_set_hash ~ '^[0-9a-f]{64}$' AND dataset_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_anp_dataset_hashes"),
        sa.CheckConstraint("reference_period_start<=reference_period_end", name="ck_anp_dataset_period"),
        sa.CheckConstraint("status IN ('building','shadow_published','retired')", name="ck_anp_dataset_status"),
        sa.CheckConstraint("quality_status IN ('passed','failed')", name="ck_anp_dataset_quality"),
        sa.CheckConstraint("observation_count>0 AND snapshot_count>0", name="ck_anp_dataset_counts"),
        sa.CheckConstraint("(status='building' AND NOT is_active_shadow AND published_at IS NULL AND retired_at IS NULL) OR (status='shadow_published' AND is_active_shadow AND published_at IS NOT NULL AND retired_at IS NULL) OR (status='retired' AND NOT is_active_shadow AND published_at IS NOT NULL AND retired_at IS NOT NULL)", name="ck_anp_dataset_lifecycle"),
        schema="gold",
    )
    op.create_index("uq_anp_dataset_active_shadow", "anp_fuel_price_dataset", ["is_active_shadow"], unique=True, schema="gold", postgresql_where=sa.text("is_active_shadow"))
    op.create_index("ix_anp_dataset_fingerprint", "anp_fuel_price_dataset", ["dataset_fingerprint"], schema="gold")

    op.create_table(
        "anp_fuel_price_snapshot",
        sa.Column("snapshot_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("dataset_version", sa.String(80), sa.ForeignKey("gold.anp_fuel_price_dataset.dataset_version", ondelete="RESTRICT"), nullable=False),
        sa.Column("publication_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("product_code", sa.String(40), nullable=False),
        sa.Column("week_start", sa.Date, nullable=False),
        sa.Column("week_end", sa.Date, nullable=False),
        sa.Column("geography_level", sa.String(20), nullable=False),
        sa.Column("geography_key", sa.String(200), nullable=False),
        sa.Column("municipality_name", sa.String(160)),
        sa.Column("state_code", sa.CHAR(2), nullable=False),
        sa.Column("currency_code", sa.CHAR(3), nullable=False, server_default="BRL"),
        sa.Column("unit_code", sa.String(20), nullable=False, server_default="liter"),
        sa.Column("mean_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("median_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("minimum_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("maximum_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("percentile_25", sa.Numeric(12, 4), nullable=False),
        sa.Column("percentile_75", sa.Numeric(12, 4), nullable=False),
        sa.Column("interquartile_range", sa.Numeric(12, 4), nullable=False),
        sa.Column("observation_count", sa.Integer, nullable=False),
        sa.Column("establishment_count", sa.Integer, nullable=False),
        sa.Column("last_collection_date", sa.Date, nullable=False),
        sa.Column("freshness_days", sa.Integer, nullable=False),
        sa.Column("sampling_status", sa.String(20), nullable=False),
        sa.Column("dispersion_status", sa.String(20), nullable=False),
        sa.Column("quality_status", sa.String(20), nullable=False),
        sa.Column("snapshot_fingerprint", sa.CHAR(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("product_code IN ('gasoline_c_common','gasoline_c_additized','ethanol_hydrated')", name="ck_anp_snapshot_product"),
        sa.CheckConstraint("week_end=week_start+6", name="ck_anp_snapshot_week"),
        sa.CheckConstraint("geography_level IN ('municipality','state')", name="ck_anp_snapshot_geography"),
        sa.CheckConstraint("currency_code='BRL' AND unit_code='liter'", name="ck_anp_snapshot_unit"),
        sa.CheckConstraint("minimum_price>0 AND minimum_price<=percentile_25 AND percentile_25<=median_price AND median_price<=percentile_75 AND percentile_75<=maximum_price AND interquartile_range=percentile_75-percentile_25", name="ck_anp_snapshot_metrics"),
        sa.CheckConstraint("observation_count>0 AND establishment_count>0 AND freshness_days>=0", name="ck_anp_snapshot_counts"),
        sa.CheckConstraint("sampling_status='not_calibrated' AND dispersion_status='not_calibrated'", name="ck_anp_snapshot_calibration"),
        sa.CheckConstraint("quality_status='passed'", name="ck_anp_snapshot_quality"),
        sa.CheckConstraint("snapshot_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_anp_snapshot_fingerprint"),
        sa.UniqueConstraint("dataset_version", "product_code", "week_start", "geography_level", "geography_key", name="uq_anp_snapshot_grain"),
        schema="gold",
    )
    op.create_index("ix_anp_snapshot_lookup", "anp_fuel_price_snapshot", ["product_code", "week_start", "state_code"], schema="gold")

    op.create_table(
        "anp_fuel_price_quality_result",
        sa.Column("quality_result_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("dataset_version", sa.String(80), sa.ForeignKey("gold.anp_fuel_price_dataset.dataset_version", ondelete="RESTRICT"), nullable=False),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("rule_code", sa.String(80), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("observed_value", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("expected_condition", sa.Text, nullable=False),
        sa.Column("details", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("severity IN ('info','warning','error','critical')", name="ck_anp_quality_severity"),
        sa.CheckConstraint("status IN ('passed','failed','not_calibrated')", name="ck_anp_quality_status"),
        sa.UniqueConstraint("dataset_version", "rule_code", name="uq_anp_quality_rule"),
        schema="gold",
    )
    op.create_index("ix_anp_quality_dataset_status", "anp_fuel_price_quality_result", ["dataset_version", "status"], schema="gold")


def _create_guards() -> None:
    op.execute(sa.text("""CREATE FUNCTION meta.prevent_anp_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'ANP lineage rows are immutable';
        END $$"""))
    for schema, table in (
        ("bronze", "anp_source_asset"),
        ("bronze", "anp_fuel_price_raw"),
        ("silver", "anp_fuel_price_observation"),
        ("gold", "anp_fuel_price_snapshot"),
        ("gold", "anp_fuel_price_quality_result"),
    ):
        op.execute(sa.text(f"""CREATE TRIGGER trg_{table}_immutable
            BEFORE UPDATE OR DELETE ON {schema}.{table}
            FOR EACH ROW EXECUTE FUNCTION meta.prevent_anp_mutation()"""))

    op.execute(sa.text("""CREATE FUNCTION gold.guard_anp_dataset_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'ANP datasets cannot be deleted';
            END IF;
            IF ROW(NEW.dataset_version,NEW.publication_run_id,NEW.source_asset_manifest,
                   NEW.source_asset_set_hash,NEW.parser_version,NEW.normalizer_version,
                   NEW.aggregation_version,NEW.reference_period_start,
                   NEW.reference_period_end,NEW.observation_count,NEW.snapshot_count,
                   NEW.dataset_fingerprint,NEW.quality_status,NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.dataset_version,OLD.publication_run_id,OLD.source_asset_manifest,
                   OLD.source_asset_set_hash,OLD.parser_version,OLD.normalizer_version,
                   OLD.aggregation_version,OLD.reference_period_start,
                   OLD.reference_period_end,OLD.observation_count,OLD.snapshot_count,
                   OLD.dataset_fingerprint,OLD.quality_status,OLD.created_at) THEN
                RAISE EXCEPTION 'ANP dataset content is immutable';
            END IF;
            IF NOT ((OLD.status='building' AND NEW.status='shadow_published') OR
                    (OLD.status='shadow_published' AND NEW.status='retired')) THEN
                RAISE EXCEPTION 'Invalid ANP dataset lifecycle transition';
            END IF;
            RETURN NEW;
        END $$"""))
    op.execute(sa.text("""CREATE TRIGGER trg_anp_fuel_price_dataset_guard
        BEFORE UPDATE OR DELETE ON gold.anp_fuel_price_dataset
        FOR EACH ROW EXECUTE FUNCTION gold.guard_anp_dataset_mutation()"""))
    op.execute(sa.text("""CREATE FUNCTION gold.guard_anp_child_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE dataset_status VARCHAR(20);
        BEGIN
            SELECT status INTO dataset_status FROM gold.anp_fuel_price_dataset
            WHERE dataset_version=NEW.dataset_version;
            IF dataset_status IS DISTINCT FROM 'building' THEN
                RAISE EXCEPTION 'ANP child inserts require a building dataset';
            END IF;
            RETURN NEW;
        END $$"""))
    for table in ("anp_fuel_price_snapshot", "anp_fuel_price_quality_result"):
        op.execute(sa.text(f"""CREATE TRIGGER trg_{table}_building
            BEFORE INSERT ON gold.{table}
            FOR EACH ROW EXECUTE FUNCTION gold.guard_anp_child_insert()"""))


def upgrade() -> None:
    if not _is_postgresql():
        return
    _create_bronze()
    _create_silver()
    _create_gold()
    _create_guards()


def downgrade() -> None:
    if not _is_postgresql():
        return
    op.execute(sa.text("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM gold.anp_fuel_price_dataset WHERE is_active_shadow) THEN
            RAISE EXCEPTION 'ANP downgrade blocked: active shadow dataset exists';
        END IF;
    END $$"""))
    for table in ("anp_fuel_price_quality_result", "anp_fuel_price_snapshot"):
        op.execute(sa.text(f"DROP TRIGGER trg_{table}_building ON gold.{table}"))
    op.execute(sa.text("DROP FUNCTION gold.guard_anp_child_insert()"))
    op.execute(sa.text("DROP TRIGGER trg_anp_fuel_price_dataset_guard ON gold.anp_fuel_price_dataset"))
    op.execute(sa.text("DROP FUNCTION gold.guard_anp_dataset_mutation()"))
    for schema, table in reversed((
        ("bronze", "anp_source_asset"),
        ("bronze", "anp_fuel_price_raw"),
        ("silver", "anp_fuel_price_observation"),
        ("gold", "anp_fuel_price_snapshot"),
        ("gold", "anp_fuel_price_quality_result"),
    )):
        op.execute(sa.text(f"DROP TRIGGER trg_{table}_immutable ON {schema}.{table}"))
    op.execute(sa.text("DROP FUNCTION meta.prevent_anp_mutation()"))
    op.drop_index("ix_anp_quality_dataset_status", table_name="anp_fuel_price_quality_result", schema="gold")
    op.drop_table("anp_fuel_price_quality_result", schema="gold")
    op.drop_index("ix_anp_snapshot_lookup", table_name="anp_fuel_price_snapshot", schema="gold")
    op.drop_table("anp_fuel_price_snapshot", schema="gold")
    op.drop_index("ix_anp_dataset_fingerprint", table_name="anp_fuel_price_dataset", schema="gold")
    op.drop_index("uq_anp_dataset_active_shadow", table_name="anp_fuel_price_dataset", schema="gold")
    op.drop_table("anp_fuel_price_dataset", schema="gold")
    op.execute(sa.text("DROP VIEW silver.anp_fuel_price_observation_current"))
    op.drop_index("ix_anp_observation_geo", table_name="anp_fuel_price_observation", schema="silver")
    op.drop_index("ix_anp_observation_key", table_name="anp_fuel_price_observation", schema="silver")
    op.drop_table("anp_fuel_price_observation", schema="silver")
    op.drop_index("ix_anp_raw_hash", table_name="anp_fuel_price_raw", schema="bronze")
    op.drop_index("ix_anp_raw_asset", table_name="anp_fuel_price_raw", schema="bronze")
    op.drop_table("anp_fuel_price_raw", schema="bronze")
    op.drop_index("ix_anp_asset_period", table_name="anp_source_asset", schema="bronze")
    op.drop_index("ix_anp_asset_run", table_name="anp_source_asset", schema="bronze")
    op.drop_table("anp_source_asset", schema="bronze")
