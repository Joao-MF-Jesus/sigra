"""Cria a integracao interna e shadow de especificacoes Carpedia.

Revision ID: 20260811_0011
Revises: 20260811_0010
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260811_0011"
down_revision: Union[str, None] = "20260811_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _create_bronze() -> None:
    op.create_table(
        "carpedia_source_asset",
        sa.Column("asset_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_name", sa.String(40), nullable=False, server_default="carpedia_api_v1"),
        sa.Column("logical_endpoint", sa.String(60), nullable=False),
        sa.Column("external_vehicle_id", sa.BigInteger, nullable=False),
        sa.Column("source_reference", sa.String(80), nullable=False),
        sa.Column("endpoint_path", sa.Text, nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("http_status", sa.Integer, nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("byte_length", sa.BigInteger, nullable=False),
        sa.Column("sha256", sa.CHAR(64), nullable=False),
        sa.Column("schema_fingerprint", sa.CHAR(64), nullable=False),
        sa.Column("contract_version", sa.String(40), nullable=False),
        sa.Column("license_status", sa.String(40), nullable=False),
        sa.Column("storage_mode", sa.String(20), nullable=False, server_default="database_json"),
        sa.Column("payload_sanitized", postgresql.JSONB, nullable=False),
        sa.Column("ingestion_status", sa.String(20), nullable=False),
        sa.Column("error_sanitized", sa.Text),
        sa.Column("technical_metadata", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("source_name='carpedia_api_v1'", name="ck_carpedia_asset_source"),
        sa.CheckConstraint("logical_endpoint='vehicle_specification'", name="ck_carpedia_asset_endpoint"),
        sa.CheckConstraint("external_vehicle_id>0", name="ck_carpedia_asset_external_id"),
        sa.CheckConstraint("http_status BETWEEN 200 AND 299", name="ck_carpedia_asset_http"),
        sa.CheckConstraint("content_type='application/json'", name="ck_carpedia_asset_content_type"),
        sa.CheckConstraint("byte_length>0 AND byte_length<=8388608", name="ck_carpedia_asset_size"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$' AND schema_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_carpedia_asset_hashes"),
        sa.CheckConstraint("contract_version='carpedia-api-v1'", name="ck_carpedia_asset_contract"),
        sa.CheckConstraint("license_status='approved_with_restrictions'", name="ck_carpedia_asset_license"),
        sa.CheckConstraint("storage_mode='database_json'", name="ck_carpedia_asset_storage"),
        sa.CheckConstraint("jsonb_typeof(payload_sanitized)='object'", name="ck_carpedia_asset_payload"),
        sa.CheckConstraint("ingestion_status IN ('accepted','quarantined','rejected')", name="ck_carpedia_asset_status"),
        sa.UniqueConstraint("logical_endpoint", "external_vehicle_id", "source_reference", "sha256", name="uq_carpedia_asset_content"),
        schema="bronze",
    )
    op.create_index("ix_carpedia_asset_run", "carpedia_source_asset", ["pipeline_run_id"], schema="bronze")
    op.create_index("ix_carpedia_asset_lookup", "carpedia_source_asset", ["external_vehicle_id", "source_reference"], schema="bronze")

    op.create_table(
        "carpedia_vehicle_raw",
        sa.Column("raw_record_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("asset_id", sa.BigInteger, sa.ForeignKey("bronze.carpedia_source_asset.asset_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("external_vehicle_id", sa.BigInteger, nullable=False),
        sa.Column("model_year", sa.SmallInteger, nullable=False),
        sa.Column("parser_version", sa.String(40), nullable=False),
        sa.Column("source_record_key", sa.String(120), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB, nullable=False),
        sa.Column("row_hash", sa.CHAR(64), nullable=False),
        sa.Column("parsing_status", sa.String(20), nullable=False),
        sa.Column("error_sanitized", sa.Text),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("external_vehicle_id>0 AND model_year BETWEEN 1900 AND 2100", name="ck_carpedia_raw_identity"),
        sa.CheckConstraint("row_hash ~ '^[0-9a-f]{64}$'", name="ck_carpedia_raw_hash"),
        sa.CheckConstraint("jsonb_typeof(raw_payload)='object'", name="ck_carpedia_raw_payload"),
        sa.CheckConstraint("parsing_status IN ('parsed','quarantined','rejected')", name="ck_carpedia_raw_status"),
        sa.UniqueConstraint("asset_id", "source_record_key", name="uq_carpedia_raw_source_record"),
        schema="bronze",
    )
    op.create_index("ix_carpedia_raw_asset", "carpedia_vehicle_raw", ["asset_id"], schema="bronze")
    op.create_index("ix_carpedia_raw_identity", "carpedia_vehicle_raw", ["external_vehicle_id", "model_year"], schema="bronze")


def _create_silver() -> None:
    op.create_table(
        "carpedia_vehicle_mapping",
        sa.Column("mapping_decision_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("raw_record_id", sa.BigInteger, sa.ForeignKey("bronze.carpedia_vehicle_raw.raw_record_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("vehicle_sk", sa.BigInteger, sa.ForeignKey("silver.vehicle_identity.vehicle_sk", ondelete="RESTRICT")),
        sa.Column("mapping_status", sa.String(20), nullable=False),
        sa.Column("match_method", sa.String(30), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 2)),
        sa.Column("review_required", sa.Boolean, nullable=False),
        sa.Column("matcher_version", sa.String(40), nullable=False),
        sa.Column("identity_evidence", postgresql.JSONB, nullable=False),
        sa.Column("candidate_evidence", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("decision_reason", sa.Text, nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supersedes_mapping_id", sa.BigInteger, sa.ForeignKey("silver.carpedia_vehicle_mapping.mapping_decision_id", ondelete="RESTRICT"), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("mapping_status IN ('matched','ambiguous','rejected','not_found','pending')", name="ck_carpedia_mapping_status"),
        sa.CheckConstraint("match_method IN ('exact_identity','multiple_exact','identity_conflict','no_candidate','insufficient_evidence')", name="ck_carpedia_mapping_method"),
        sa.CheckConstraint("confidence IS NULL OR confidence BETWEEN 0 AND 100", name="ck_carpedia_mapping_confidence"),
        sa.CheckConstraint("(mapping_status='matched' AND vehicle_sk IS NOT NULL AND confidence=100 AND NOT review_required) OR (mapping_status<>'matched' AND vehicle_sk IS NULL)", name="ck_carpedia_mapping_target"),
        sa.CheckConstraint("jsonb_typeof(identity_evidence)='object' AND jsonb_typeof(candidate_evidence)='array'", name="ck_carpedia_mapping_evidence"),
        sa.CheckConstraint("supersedes_mapping_id IS NULL OR supersedes_mapping_id<>mapping_decision_id", name="ck_carpedia_mapping_supersedes"),
        sa.UniqueConstraint("raw_record_id", "matcher_version", "effective_at", name="uq_carpedia_mapping_version"),
        schema="silver",
    )
    op.create_index("ix_carpedia_mapping_status", "carpedia_vehicle_mapping", ["mapping_status"], schema="silver")
    op.create_index("ix_carpedia_mapping_vehicle", "carpedia_vehicle_mapping", ["vehicle_sk"], schema="silver", postgresql_where=sa.text("vehicle_sk IS NOT NULL"))
    op.execute(sa.text("""CREATE VIEW silver.carpedia_vehicle_mapping_current AS
        SELECT mapping.* FROM silver.carpedia_vehicle_mapping AS mapping
        WHERE NOT EXISTS (
            SELECT 1 FROM silver.carpedia_vehicle_mapping AS successor
            WHERE successor.supersedes_mapping_id=mapping.mapping_decision_id
        )"""))

    op.create_table(
        "carpedia_vehicle_specification",
        sa.Column("specification_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("raw_record_id", sa.BigInteger, sa.ForeignKey("bronze.carpedia_vehicle_raw.raw_record_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("mapping_decision_id", sa.BigInteger, sa.ForeignKey("silver.carpedia_vehicle_mapping.mapping_decision_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("vehicle_sk", sa.BigInteger, sa.ForeignKey("silver.vehicle_identity.vehicle_sk", ondelete="RESTRICT")),
        sa.Column("external_vehicle_id", sa.BigInteger, nullable=False),
        sa.Column("source_reference", sa.String(80), nullable=False),
        sa.Column("brand_name", sa.String(80), nullable=False),
        sa.Column("model_name", sa.String(120), nullable=False),
        sa.Column("version_name", sa.String(255), nullable=False),
        sa.Column("model_year", sa.SmallInteger, nullable=False),
        sa.Column("mapping_status", sa.String(20), nullable=False),
        sa.Column("attributes", postgresql.JSONB, nullable=False),
        sa.Column("attribute_provenance", postgresql.JSONB, nullable=False),
        sa.Column("source_fingerprint", sa.CHAR(64), nullable=False),
        sa.Column("normalized_fingerprint", sa.CHAR(64), nullable=False),
        sa.Column("quality_status", sa.String(20), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supersedes_specification_id", sa.BigInteger, sa.ForeignKey("silver.carpedia_vehicle_specification.specification_id", ondelete="RESTRICT"), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("external_vehicle_id>0 AND model_year BETWEEN 1900 AND 2100", name="ck_carpedia_spec_identity"),
        sa.CheckConstraint("mapping_status IN ('matched','ambiguous','rejected','not_found','pending')", name="ck_carpedia_spec_mapping_status"),
        sa.CheckConstraint("(mapping_status='matched' AND vehicle_sk IS NOT NULL) OR (mapping_status<>'matched' AND vehicle_sk IS NULL)", name="ck_carpedia_spec_mapping_target"),
        sa.CheckConstraint("jsonb_typeof(attributes)='object' AND jsonb_typeof(attribute_provenance)='object'", name="ck_carpedia_spec_attributes"),
        sa.CheckConstraint("source_fingerprint ~ '^[0-9a-f]{64}$' AND normalized_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_carpedia_spec_hashes"),
        sa.CheckConstraint("quality_status IN ('passed','warning','rejected')", name="ck_carpedia_spec_quality"),
        sa.CheckConstraint("supersedes_specification_id IS NULL OR supersedes_specification_id<>specification_id", name="ck_carpedia_spec_supersedes"),
        sa.UniqueConstraint("raw_record_id", "normalized_fingerprint", name="uq_carpedia_spec_raw_fingerprint"),
        schema="silver",
    )
    op.create_index("ix_carpedia_spec_vehicle", "carpedia_vehicle_specification", ["vehicle_sk", "model_year"], schema="silver")
    op.create_index("ix_carpedia_spec_external", "carpedia_vehicle_specification", ["external_vehicle_id", "model_year"], schema="silver")
    op.execute(sa.text("""CREATE VIEW silver.carpedia_vehicle_specification_current AS
        SELECT specification.* FROM silver.carpedia_vehicle_specification AS specification
        WHERE NOT EXISTS (
            SELECT 1 FROM silver.carpedia_vehicle_specification AS successor
            WHERE successor.supersedes_specification_id=specification.specification_id
        )"""))


def _create_gold() -> None:
    op.create_table(
        "carpedia_vehicle_spec_dataset",
        sa.Column("dataset_version", sa.String(96), primary_key=True),
        sa.Column("publication_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("source_asset_manifest", postgresql.JSONB, nullable=False),
        sa.Column("parser_version", sa.String(40), nullable=False),
        sa.Column("normalizer_version", sa.String(40), nullable=False),
        sa.Column("matcher_version", sa.String(40), nullable=False),
        sa.Column("publication_version", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("is_active_shadow", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("source_record_count", sa.Integer, nullable=False),
        sa.Column("matched_count", sa.Integer, nullable=False),
        sa.Column("snapshot_count", sa.Integer, nullable=False),
        sa.Column("dataset_fingerprint", sa.CHAR(64), nullable=False),
        sa.Column("quality_status", sa.String(20), nullable=False),
        sa.Column("supersedes_dataset_version", sa.String(96), sa.ForeignKey("gold.carpedia_vehicle_spec_dataset.dataset_version", ondelete="RESTRICT"), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.Column("invalidated_at", sa.DateTime(timezone=True)),
        sa.Column("invalidation_reason", sa.Text),
        sa.CheckConstraint("jsonb_typeof(source_asset_manifest)='array'", name="ck_carpedia_dataset_manifest"),
        sa.CheckConstraint("status IN ('building','shadow_published','retired','invalidated')", name="ck_carpedia_dataset_status"),
        sa.CheckConstraint("quality_status IN ('passed','failed')", name="ck_carpedia_dataset_quality"),
        sa.CheckConstraint("source_record_count>0 AND matched_count>0 AND snapshot_count=matched_count", name="ck_carpedia_dataset_counts"),
        sa.CheckConstraint("dataset_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_carpedia_dataset_fingerprint"),
        sa.CheckConstraint("(status='building' AND NOT is_active_shadow AND published_at IS NULL AND retired_at IS NULL AND invalidated_at IS NULL) OR (status='shadow_published' AND is_active_shadow AND published_at IS NOT NULL AND retired_at IS NULL AND invalidated_at IS NULL) OR (status='retired' AND NOT is_active_shadow AND published_at IS NOT NULL AND retired_at IS NOT NULL AND invalidated_at IS NULL) OR (status='invalidated' AND NOT is_active_shadow AND published_at IS NOT NULL AND invalidated_at IS NOT NULL AND NULLIF(BTRIM(invalidation_reason),'') IS NOT NULL)", name="ck_carpedia_dataset_lifecycle"),
        sa.CheckConstraint("published_at IS NULL OR created_at<=published_at", name="ck_carpedia_dataset_publish_time"),
        schema="gold",
    )
    op.create_index("uq_carpedia_dataset_active", "carpedia_vehicle_spec_dataset", ["is_active_shadow"], unique=True, schema="gold", postgresql_where=sa.text("is_active_shadow"))
    op.create_index("ix_carpedia_dataset_fingerprint", "carpedia_vehicle_spec_dataset", ["dataset_fingerprint"], schema="gold")

    op.create_table(
        "carpedia_vehicle_spec_snapshot",
        sa.Column("snapshot_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("dataset_version", sa.String(96), sa.ForeignKey("gold.carpedia_vehicle_spec_dataset.dataset_version", ondelete="RESTRICT"), nullable=False),
        sa.Column("publication_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("vehicle_sk", sa.BigInteger, sa.ForeignKey("silver.vehicle_identity.vehicle_sk", ondelete="RESTRICT"), nullable=False),
        sa.Column("specification_id", sa.BigInteger, sa.ForeignKey("silver.carpedia_vehicle_specification.specification_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("external_vehicle_id", sa.BigInteger, nullable=False),
        sa.Column("source_reference", sa.String(80), nullable=False),
        sa.Column("model_year", sa.SmallInteger, nullable=False),
        sa.Column("attributes", postgresql.JSONB, nullable=False),
        sa.Column("attribute_provenance", postgresql.JSONB, nullable=False),
        sa.Column("quality_status", sa.String(20), nullable=False),
        sa.Column("snapshot_fingerprint", sa.CHAR(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("external_vehicle_id>0 AND model_year BETWEEN 1900 AND 2100", name="ck_carpedia_snapshot_identity"),
        sa.CheckConstraint("jsonb_typeof(attributes)='object' AND jsonb_typeof(attribute_provenance)='object'", name="ck_carpedia_snapshot_attributes"),
        sa.CheckConstraint("quality_status='passed'", name="ck_carpedia_snapshot_quality"),
        sa.CheckConstraint("snapshot_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_carpedia_snapshot_fingerprint"),
        sa.UniqueConstraint("dataset_version", "vehicle_sk", name="uq_carpedia_snapshot_grain"),
        schema="gold",
    )
    op.create_index("ix_carpedia_snapshot_vehicle", "carpedia_vehicle_spec_snapshot", ["vehicle_sk", "model_year"], schema="gold")

    op.create_table(
        "carpedia_vehicle_spec_quality_result",
        sa.Column("quality_result_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("dataset_version", sa.String(96), sa.ForeignKey("gold.carpedia_vehicle_spec_dataset.dataset_version", ondelete="RESTRICT"), nullable=False),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("rule_code", sa.String(80), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("observed_value", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("expected_condition", sa.Text, nullable=False),
        sa.Column("details", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("severity IN ('info','warning','error','critical')", name="ck_carpedia_quality_severity"),
        sa.CheckConstraint("status IN ('passed','failed')", name="ck_carpedia_quality_status"),
        sa.UniqueConstraint("dataset_version", "rule_code", name="uq_carpedia_quality_rule"),
        schema="gold",
    )
    op.create_index("ix_carpedia_quality_status", "carpedia_vehicle_spec_quality_result", ["dataset_version", "status"], schema="gold")

    op.create_table(
        "carpedia_vehicle_spec_dataset_event",
        sa.Column("event_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("dataset_version", sa.String(96), sa.ForeignKey("gold.carpedia_vehicle_spec_dataset.dataset_version", ondelete="RESTRICT"), nullable=False),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("related_dataset_version", sa.String(96), sa.ForeignKey("gold.carpedia_vehicle_spec_dataset.dataset_version", ondelete="RESTRICT")),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("event_fingerprint", sa.CHAR(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("event_type IN ('activated','superseded','invalidated','rolled_back')", name="ck_carpedia_event_type"),
        sa.CheckConstraint("event_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_carpedia_event_fingerprint"),
        sa.UniqueConstraint("event_fingerprint", name="uq_carpedia_event_fingerprint"),
        schema="gold",
    )
    op.create_index("ix_carpedia_event_dataset", "carpedia_vehicle_spec_dataset_event", ["dataset_version", "occurred_at"], schema="gold")


def _create_guards() -> None:
    op.execute(sa.text("""CREATE FUNCTION meta.assert_carpedia_downgrade_safe()
        RETURNS void LANGUAGE plpgsql AS $$
        BEGIN
          IF EXISTS (SELECT 1 FROM bronze.carpedia_source_asset)
             OR EXISTS (SELECT 1 FROM bronze.carpedia_vehicle_raw)
             OR EXISTS (SELECT 1 FROM silver.carpedia_vehicle_mapping)
             OR EXISTS (SELECT 1 FROM silver.carpedia_vehicle_specification)
             OR EXISTS (SELECT 1 FROM gold.carpedia_vehicle_spec_dataset)
             OR EXISTS (SELECT 1 FROM gold.carpedia_vehicle_spec_snapshot)
             OR EXISTS (SELECT 1 FROM gold.carpedia_vehicle_spec_quality_result)
             OR EXISTS (SELECT 1 FROM gold.carpedia_vehicle_spec_dataset_event) THEN
            RAISE EXCEPTION 'Carpedia downgrade blocked: dataset or lineage history exists';
          END IF;
        END $$"""))
    op.execute(sa.text("""CREATE FUNCTION meta.prevent_carpedia_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Carpedia lineage and evidence rows are immutable';
        END $$"""))
    immutable_tables = (
        ("bronze", "carpedia_source_asset"),
        ("bronze", "carpedia_vehicle_raw"),
        ("silver", "carpedia_vehicle_mapping"),
        ("silver", "carpedia_vehicle_specification"),
        ("gold", "carpedia_vehicle_spec_snapshot"),
        ("gold", "carpedia_vehicle_spec_quality_result"),
        ("gold", "carpedia_vehicle_spec_dataset_event"),
    )
    for schema, table in immutable_tables:
        op.execute(sa.text(f"""CREATE TRIGGER trg_{table}_immutable
            BEFORE UPDATE OR DELETE ON {schema}.{table}
            FOR EACH ROW EXECUTE FUNCTION meta.prevent_carpedia_mutation()"""))

    op.execute(sa.text("""CREATE FUNCTION gold.guard_carpedia_dataset_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'Carpedia datasets cannot be deleted';
            END IF;
            IF ROW(NEW.dataset_version,NEW.publication_run_id,NEW.source_asset_manifest,
                   NEW.parser_version,NEW.normalizer_version,NEW.matcher_version,
                   NEW.publication_version,NEW.source_record_count,NEW.matched_count,
                   NEW.snapshot_count,NEW.dataset_fingerprint,NEW.quality_status,
                   NEW.supersedes_dataset_version,NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.dataset_version,OLD.publication_run_id,OLD.source_asset_manifest,
                   OLD.parser_version,OLD.normalizer_version,OLD.matcher_version,
                   OLD.publication_version,OLD.source_record_count,OLD.matched_count,
                   OLD.snapshot_count,OLD.dataset_fingerprint,OLD.quality_status,
                   OLD.supersedes_dataset_version,OLD.created_at) THEN
                RAISE EXCEPTION 'Carpedia dataset content is immutable';
            END IF;
            IF NOT ((OLD.status='building' AND NEW.status='shadow_published') OR
                    (OLD.status='shadow_published' AND NEW.status IN ('retired','invalidated')) OR
                    (OLD.status='retired' AND NEW.status='shadow_published')) THEN
                RAISE EXCEPTION 'Invalid Carpedia dataset lifecycle transition';
            END IF;
            RETURN NEW;
        END $$"""))
    op.execute(sa.text("""CREATE TRIGGER trg_carpedia_vehicle_spec_dataset_guard
        BEFORE UPDATE OR DELETE ON gold.carpedia_vehicle_spec_dataset
        FOR EACH ROW EXECUTE FUNCTION gold.guard_carpedia_dataset_mutation()"""))
    op.execute(sa.text("""CREATE FUNCTION gold.guard_carpedia_child_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE dataset_status VARCHAR(20);
        BEGIN
            SELECT status INTO dataset_status FROM gold.carpedia_vehicle_spec_dataset
            WHERE dataset_version=NEW.dataset_version;
            IF dataset_status IS DISTINCT FROM 'building' THEN
                RAISE EXCEPTION 'Carpedia child inserts require a building dataset';
            END IF;
            RETURN NEW;
        END $$"""))
    for table in ("carpedia_vehicle_spec_snapshot", "carpedia_vehicle_spec_quality_result"):
        op.execute(sa.text(f"""CREATE TRIGGER trg_{table}_building
            BEFORE INSERT ON gold.{table}
            FOR EACH ROW EXECUTE FUNCTION gold.guard_carpedia_child_insert()"""))


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
    op.execute(sa.text("SELECT meta.assert_carpedia_downgrade_safe()"))
    for table in ("carpedia_vehicle_spec_quality_result", "carpedia_vehicle_spec_snapshot"):
        op.execute(sa.text(f"DROP TRIGGER trg_{table}_building ON gold.{table}"))
    op.execute(sa.text("DROP FUNCTION gold.guard_carpedia_child_insert()"))
    op.execute(sa.text("DROP TRIGGER trg_carpedia_vehicle_spec_dataset_guard ON gold.carpedia_vehicle_spec_dataset"))
    op.execute(sa.text("DROP FUNCTION gold.guard_carpedia_dataset_mutation()"))
    immutable_tables = (
        ("bronze", "carpedia_source_asset"),
        ("bronze", "carpedia_vehicle_raw"),
        ("silver", "carpedia_vehicle_mapping"),
        ("silver", "carpedia_vehicle_specification"),
        ("gold", "carpedia_vehicle_spec_snapshot"),
        ("gold", "carpedia_vehicle_spec_quality_result"),
        ("gold", "carpedia_vehicle_spec_dataset_event"),
    )
    for schema, table in reversed(immutable_tables):
        op.execute(sa.text(f"DROP TRIGGER trg_{table}_immutable ON {schema}.{table}"))
    op.execute(sa.text("DROP FUNCTION meta.prevent_carpedia_mutation()"))
    op.drop_index("ix_carpedia_event_dataset", table_name="carpedia_vehicle_spec_dataset_event", schema="gold")
    op.drop_table("carpedia_vehicle_spec_dataset_event", schema="gold")
    op.drop_index("ix_carpedia_quality_status", table_name="carpedia_vehicle_spec_quality_result", schema="gold")
    op.drop_table("carpedia_vehicle_spec_quality_result", schema="gold")
    op.drop_index("ix_carpedia_snapshot_vehicle", table_name="carpedia_vehicle_spec_snapshot", schema="gold")
    op.drop_table("carpedia_vehicle_spec_snapshot", schema="gold")
    op.drop_index("ix_carpedia_dataset_fingerprint", table_name="carpedia_vehicle_spec_dataset", schema="gold")
    op.drop_index("uq_carpedia_dataset_active", table_name="carpedia_vehicle_spec_dataset", schema="gold")
    op.drop_table("carpedia_vehicle_spec_dataset", schema="gold")
    op.execute(sa.text("DROP VIEW silver.carpedia_vehicle_specification_current"))
    op.drop_index("ix_carpedia_spec_external", table_name="carpedia_vehicle_specification", schema="silver")
    op.drop_index("ix_carpedia_spec_vehicle", table_name="carpedia_vehicle_specification", schema="silver")
    op.drop_table("carpedia_vehicle_specification", schema="silver")
    op.execute(sa.text("DROP VIEW silver.carpedia_vehicle_mapping_current"))
    op.drop_index("ix_carpedia_mapping_vehicle", table_name="carpedia_vehicle_mapping", schema="silver")
    op.drop_index("ix_carpedia_mapping_status", table_name="carpedia_vehicle_mapping", schema="silver")
    op.drop_table("carpedia_vehicle_mapping", schema="silver")
    op.drop_index("ix_carpedia_raw_identity", table_name="carpedia_vehicle_raw", schema="bronze")
    op.drop_index("ix_carpedia_raw_asset", table_name="carpedia_vehicle_raw", schema="bronze")
    op.drop_table("carpedia_vehicle_raw", schema="bronze")
    op.drop_index("ix_carpedia_asset_lookup", table_name="carpedia_source_asset", schema="bronze")
    op.drop_index("ix_carpedia_asset_run", table_name="carpedia_source_asset", schema="bronze")
    op.drop_table("carpedia_source_asset", schema="bronze")
    op.execute(sa.text("DROP FUNCTION meta.assert_carpedia_downgrade_safe()"))
