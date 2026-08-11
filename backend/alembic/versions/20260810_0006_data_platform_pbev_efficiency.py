"""Cria a integracao interna e shadow do Inmetro PBE Veicular.

Revision ID: 20260810_0006
Revises: 20260810_0005
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260810_0006"
down_revision: Union[str, None] = "20260810_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _create_bronze() -> None:
    op.create_table(
        "pbev_source_asset",
        sa.Column("asset_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_system", sa.String(40), nullable=False, server_default="inmetro_pbev"),
        sa.Column("official_page_url", sa.Text, nullable=False),
        sa.Column("download_url_sanitized", sa.Text, nullable=False),
        sa.Column("document_title", sa.String(255), nullable=False),
        sa.Column("cycle_year", sa.SmallInteger, nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("accessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("byte_length", sa.BigInteger, nullable=False),
        sa.Column("page_count", sa.Integer, nullable=False),
        sa.Column("sha256", sa.CHAR(64), nullable=False),
        sa.Column("layout_family", sa.String(40)),
        sa.Column("document_metadata", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("document_bytes", sa.LargeBinary),
        sa.Column("storage_mode", sa.String(20), nullable=False, server_default="metadata_only"),
        sa.Column("license_code", sa.String(40), nullable=False),
        sa.Column("attribution_text", sa.Text, nullable=False),
        sa.Column("license_url", sa.Text, nullable=False),
        sa.Column("asset_status", sa.String(20), nullable=False),
        sa.Column("validation_details", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("source_system = 'inmetro_pbev'", name="ck_pbev_asset_source"),
        sa.CheckConstraint("cycle_year BETWEEN 2009 AND 2100", name="ck_pbev_asset_cycle"),
        sa.CheckConstraint("content_type = 'application/pdf'", name="ck_pbev_asset_mime"),
        sa.CheckConstraint("byte_length > 0 AND page_count > 0", name="ck_pbev_asset_size"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_pbev_asset_sha256"),
        sa.CheckConstraint("storage_mode IN ('metadata_only','internal_copy')", name="ck_pbev_asset_storage"),
        sa.CheckConstraint("asset_status IN ('accepted','quarantined','rejected')", name="ck_pbev_asset_status"),
        sa.CheckConstraint("(storage_mode='metadata_only' AND document_bytes IS NULL) OR (storage_mode='internal_copy' AND document_bytes IS NOT NULL AND octet_length(document_bytes)=byte_length)", name="ck_pbev_asset_bytes"),
        sa.UniqueConstraint("source_system", "cycle_year", "sha256", name="uq_pbev_asset_cycle_sha"),
        schema="bronze",
    )
    op.create_index("ix_pbev_asset_run", "pbev_source_asset", ["pipeline_run_id"], schema="bronze")
    op.create_index("ix_pbev_asset_status", "pbev_source_asset", ["asset_status", "cycle_year"], schema="bronze")

    op.create_table(
        "pbev_raw_row",
        sa.Column("pbev_raw_row_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("asset_id", sa.BigInteger, sa.ForeignKey("bronze.pbev_source_asset.asset_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("page_number", sa.Integer, nullable=False),
        sa.Column("row_number", sa.Integer, nullable=False),
        sa.Column("source_record_key", sa.String(180), nullable=False),
        sa.Column("parser_version", sa.String(40), nullable=False),
        sa.Column("layout_family", sa.String(40), nullable=False),
        sa.Column("schema_fingerprint", sa.CHAR(64), nullable=False),
        sa.Column("raw_cells", postgresql.JSONB, nullable=False),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column("row_hash", sa.CHAR(64), nullable=False),
        sa.Column("extraction_status", sa.String(20), nullable=False),
        sa.Column("extraction_method", sa.String(30), nullable=False),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("page_number > 0 AND row_number > 0", name="ck_pbev_raw_position"),
        sa.CheckConstraint("schema_fingerprint ~ '^[0-9a-f]{64}$' AND row_hash ~ '^[0-9a-f]{64}$'", name="ck_pbev_raw_hashes"),
        sa.CheckConstraint("jsonb_typeof(raw_cells) = 'array'", name="ck_pbev_raw_cells"),
        sa.CheckConstraint("extraction_status IN ('parsed','duplicate','invalid_header','invalid_units','invalid_row')", name="ck_pbev_raw_status"),
        sa.CheckConstraint("extraction_method IN ('vector_grid','positioned_text')", name="ck_pbev_raw_method"),
        sa.UniqueConstraint("asset_id", "page_number", "row_number", name="uq_pbev_raw_position"),
        sa.UniqueConstraint("asset_id", "source_record_key", name="uq_pbev_raw_source_key"),
        schema="bronze",
    )
    op.create_index("ix_pbev_raw_asset_page", "pbev_raw_row", ["asset_id", "page_number"], schema="bronze")
    op.create_index("ix_pbev_raw_status", "pbev_raw_row", ["extraction_status"], schema="bronze")
    op.create_index("ix_pbev_raw_hash", "pbev_raw_row", ["row_hash"], schema="bronze")


def _create_silver() -> None:
    op.create_table(
        "pbev_vehicle_mapping",
        sa.Column("mapping_decision_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_system", sa.String(40), nullable=False, server_default="inmetro_pbev"),
        sa.Column("target_identity_hash", sa.CHAR(64), nullable=False),
        sa.Column("target_identity_evidence", postgresql.JSONB, nullable=False),
        sa.Column("target_vehicle_type", sa.String(20), nullable=False, server_default="car"),
        sa.Column("selected_raw_row_id", sa.BigInteger, sa.ForeignKey("bronze.pbev_raw_row.pbev_raw_row_id", ondelete="RESTRICT")),
        sa.Column("vehicle_sk", sa.BigInteger, sa.ForeignKey("silver.vehicle_identity.vehicle_sk", ondelete="RESTRICT")),
        sa.Column("mapping_status", sa.String(20), nullable=False),
        sa.Column("match_method", sa.String(30), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 2)),
        sa.Column("review_required", sa.Boolean, nullable=False),
        sa.Column("matcher_version", sa.String(40), nullable=False),
        sa.Column("evidence", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("decision_reason", sa.Text, nullable=False),
        sa.Column("reviewed_by", sa.String(120)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supersedes_mapping_id", sa.BigInteger, sa.ForeignKey("silver.pbev_vehicle_mapping.mapping_decision_id", ondelete="RESTRICT"), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("source_system='inmetro_pbev' AND target_vehicle_type='car'", name="ck_pbev_mapping_scope"),
        sa.CheckConstraint("target_identity_hash ~ '^[0-9a-f]{64}$'", name="ck_pbev_mapping_hash"),
        sa.CheckConstraint("mapping_status IN ('matched','pending','ambiguous','rejected','not_found')", name="ck_pbev_mapping_status"),
        sa.CheckConstraint("match_method IN ('exact_rule','scored_rule','manual_review','catalog_conflict','no_candidate')", name="ck_pbev_mapping_method"),
        sa.CheckConstraint("confidence IS NULL OR confidence BETWEEN 0 AND 100", name="ck_pbev_mapping_confidence"),
        sa.CheckConstraint("(mapping_status='matched' AND vehicle_sk IS NOT NULL AND selected_raw_row_id IS NOT NULL AND confidence IS NOT NULL) OR (mapping_status<>'matched' AND vehicle_sk IS NULL)", name="ck_pbev_mapping_target"),
        sa.CheckConstraint("mapping_status<>'not_found' OR selected_raw_row_id IS NULL", name="ck_pbev_mapping_not_found"),
        sa.CheckConstraint("(reviewed_by IS NULL AND reviewed_at IS NULL) OR (NULLIF(BTRIM(reviewed_by),'') IS NOT NULL AND reviewed_at IS NOT NULL)", name="ck_pbev_mapping_review"),
        sa.CheckConstraint("supersedes_mapping_id IS NULL OR supersedes_mapping_id <> mapping_decision_id", name="ck_pbev_mapping_supersedes"),
        sa.UniqueConstraint("source_system", "target_identity_hash", "effective_at", name="uq_pbev_mapping_version"),
        schema="silver",
    )
    op.create_index("ix_pbev_mapping_status", "pbev_vehicle_mapping", ["mapping_status", "source_system"], schema="silver")
    op.create_index("ix_pbev_mapping_vehicle", "pbev_vehicle_mapping", ["vehicle_sk"], schema="silver", postgresql_where=sa.text("vehicle_sk IS NOT NULL"))
    op.create_index("ix_pbev_mapping_raw", "pbev_vehicle_mapping", ["selected_raw_row_id"], schema="silver", postgresql_where=sa.text("selected_raw_row_id IS NOT NULL"))

    op.execute(sa.text("""CREATE VIEW silver.pbev_vehicle_mapping_current AS
        SELECT decision.*
        FROM silver.pbev_vehicle_mapping AS decision
        WHERE NOT EXISTS (
            SELECT 1 FROM silver.pbev_vehicle_mapping AS successor
            WHERE successor.supersedes_mapping_id = decision.mapping_decision_id
        )"""))

    op.create_table(
        "vehicle_efficiency_observation",
        sa.Column("observation_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("vehicle_sk", sa.BigInteger, sa.ForeignKey("silver.vehicle_identity.vehicle_sk", ondelete="RESTRICT"), nullable=False),
        sa.Column("mapping_decision_id", sa.BigInteger, sa.ForeignKey("silver.pbev_vehicle_mapping.mapping_decision_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("pbev_raw_row_id", sa.BigInteger, sa.ForeignKey("bronze.pbev_raw_row.pbev_raw_row_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("cycle_year", sa.SmallInteger, nullable=False),
        sa.Column("source_reference_date", sa.Date),
        sa.Column("category_name", sa.String(120), nullable=False),
        sa.Column("brand_name", sa.String(80), nullable=False),
        sa.Column("model_name", sa.String(120), nullable=False),
        sa.Column("version_name", sa.String(255)),
        sa.Column("motor_description", sa.String(120)),
        sa.Column("body_style", sa.String(80)),
        sa.Column("transmission_code", sa.String(40)),
        sa.Column("propulsion_type", sa.String(30)),
        sa.Column("fuel_type", sa.String(30)),
        sa.Column("emission_schema_version", sa.String(50), nullable=False),
        sa.Column("emission_raw", postgresql.JSONB, nullable=False),
        sa.Column("consumption_raw", postgresql.JSONB, nullable=False),
        sa.Column("nmhc_mg_km", sa.Numeric(14, 6)),
        sa.Column("nox_mg_km", sa.Numeric(14, 6)),
        sa.Column("nmog_nox_mg_km", sa.Numeric(14, 6)),
        sa.Column("co_mg_km", sa.Numeric(14, 6)),
        sa.Column("cho_mg_km", sa.Numeric(14, 6)),
        sa.Column("co2_ethanol_g_km", sa.Numeric(14, 6)),
        sa.Column("co2_fossil_g_km", sa.Numeric(14, 6)),
        sa.Column("pollutant_reduction_class", sa.String(10)),
        sa.Column("ethanol_city_km_l", sa.Numeric(10, 4)),
        sa.Column("ethanol_highway_km_l", sa.Numeric(10, 4)),
        sa.Column("fossil_city_km_l", sa.Numeric(10, 4)),
        sa.Column("fossil_highway_km_l", sa.Numeric(10, 4)),
        sa.Column("electric_city_km_l_equivalent", sa.Numeric(10, 4)),
        sa.Column("electric_highway_km_l_equivalent", sa.Numeric(10, 4)),
        sa.Column("energy_mj_km", sa.Numeric(10, 4), nullable=False),
        sa.Column("pbe_relative_class", sa.String(10)),
        sa.Column("pbe_absolute_class", sa.String(10)),
        sa.Column("conpet_seal", sa.Boolean),
        sa.Column("methodology_reference", sa.String(120), nullable=False),
        sa.Column("quality_status", sa.String(20), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("cycle_year BETWEEN 2009 AND 2100", name="ck_pbev_observation_cycle"),
        sa.CheckConstraint("quality_status IN ('passed','warning','rejected')", name="ck_pbev_observation_quality"),
        sa.CheckConstraint("energy_mj_km > 0", name="ck_pbev_observation_energy"),
        sa.CheckConstraint("COALESCE(nmhc_mg_km,0)>=0 AND COALESCE(nox_mg_km,0)>=0 AND COALESCE(nmog_nox_mg_km,0)>=0 AND COALESCE(co_mg_km,0)>=0 AND COALESCE(cho_mg_km,0)>=0 AND COALESCE(co2_ethanol_g_km,0)>=0 AND COALESCE(co2_fossil_g_km,0)>=0", name="ck_pbev_observation_emissions"),
        sa.CheckConstraint("(ethanol_city_km_l IS NULL)=(ethanol_highway_km_l IS NULL) AND (fossil_city_km_l IS NULL)=(fossil_highway_km_l IS NULL) AND (electric_city_km_l_equivalent IS NULL)=(electric_highway_km_l_equivalent IS NULL)", name="ck_pbev_observation_pairs"),
        sa.CheckConstraint("(ethanol_city_km_l IS NOT NULL) OR (fossil_city_km_l IS NOT NULL) OR (electric_city_km_l_equivalent IS NOT NULL)", name="ck_pbev_observation_consumption"),
        sa.CheckConstraint("NOT (nmhc_mg_km IS NOT NULL AND nmog_nox_mg_km IS NOT NULL)", name="ck_pbev_observation_semantics"),
        sa.UniqueConstraint("mapping_decision_id", "pbev_raw_row_id", name="uq_pbev_observation_lineage"),
        schema="silver",
    )
    op.create_index("ix_pbev_observation_vehicle_cycle", "vehicle_efficiency_observation", ["vehicle_sk", sa.text("cycle_year DESC")], schema="silver")
    op.create_index("ix_pbev_observation_raw", "vehicle_efficiency_observation", ["pbev_raw_row_id"], schema="silver")
    op.create_index("ix_pbev_observation_quality", "vehicle_efficiency_observation", ["quality_status"], schema="silver")


def _create_gold() -> None:
    op.create_table(
        "vehicle_efficiency_dataset",
        sa.Column("dataset_version", sa.String(80), primary_key=True),
        sa.Column("publication_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("source_system", sa.String(40), nullable=False, server_default="inmetro_pbev"),
        sa.Column("source_asset_manifest", postgresql.JSONB, nullable=False),
        sa.Column("source_asset_set_hash", sa.CHAR(64), nullable=False),
        sa.Column("parser_version", sa.String(40), nullable=False),
        sa.Column("matcher_version", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("is_active_shadow", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("universe_count", sa.Integer, nullable=False),
        sa.Column("eligible_count", sa.Integer, nullable=False),
        sa.Column("matched_count", sa.Integer, nullable=False),
        sa.Column("pending_count", sa.Integer, nullable=False),
        sa.Column("ambiguous_count", sa.Integer, nullable=False),
        sa.Column("rejected_count", sa.Integer, nullable=False),
        sa.Column("not_found_count", sa.Integer, nullable=False),
        sa.Column("published_count", sa.Integer, nullable=False),
        sa.Column("coverage_percentage", sa.Numeric(5, 2), nullable=False),
        sa.Column("coverage_report", postgresql.JSONB, nullable=False),
        sa.Column("dataset_fingerprint", sa.CHAR(64), nullable=False),
        sa.Column("quality_status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("source_system='inmetro_pbev'", name="ck_pbev_dataset_source"),
        sa.CheckConstraint("source_asset_set_hash ~ '^[0-9a-f]{64}$' AND dataset_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_pbev_dataset_hashes"),
        sa.CheckConstraint("status IN ('building','shadow_published','retired')", name="ck_pbev_dataset_status"),
        sa.CheckConstraint("quality_status IN ('passed','warning','failed')", name="ck_pbev_dataset_quality"),
        sa.CheckConstraint("universe_count>=eligible_count AND eligible_count=matched_count+pending_count+ambiguous_count+rejected_count+not_found_count AND published_count>=0 AND published_count<=matched_count", name="ck_pbev_dataset_counts"),
        sa.CheckConstraint("(eligible_count=0 AND coverage_percentage=0) OR (eligible_count>0 AND coverage_percentage=ROUND(published_count::numeric*100/eligible_count,2))", name="ck_pbev_dataset_coverage"),
        sa.CheckConstraint("(status='building' AND NOT is_active_shadow AND published_at IS NULL AND retired_at IS NULL) OR (status='shadow_published' AND is_active_shadow AND published_at IS NOT NULL AND retired_at IS NULL) OR (status='retired' AND NOT is_active_shadow AND published_at IS NOT NULL AND retired_at IS NOT NULL)", name="ck_pbev_dataset_lifecycle"),
        sa.UniqueConstraint("dataset_version", "publication_run_id", name="uq_pbev_dataset_version_run"),
        schema="gold",
    )
    op.create_index("uq_pbev_dataset_active_shadow", "vehicle_efficiency_dataset", ["is_active_shadow"], unique=True, schema="gold", postgresql_where=sa.text("is_active_shadow"))
    op.create_index("ix_pbev_dataset_fingerprint", "vehicle_efficiency_dataset", ["dataset_fingerprint"], schema="gold")

    op.create_table(
        "vehicle_efficiency_snapshot",
        sa.Column("gold_record_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("dataset_version", sa.String(80), nullable=False),
        sa.Column("publication_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vehicle_sk", sa.BigInteger, sa.ForeignKey("silver.vehicle_identity.vehicle_sk", ondelete="RESTRICT"), nullable=False),
        sa.Column("mapping_decision_id", sa.BigInteger, sa.ForeignKey("silver.pbev_vehicle_mapping.mapping_decision_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("observation_id", sa.BigInteger, sa.ForeignKey("silver.vehicle_efficiency_observation.observation_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("asset_id", sa.BigInteger, sa.ForeignKey("bronze.pbev_source_asset.asset_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("pbev_raw_row_id", sa.BigInteger, sa.ForeignKey("bronze.pbev_raw_row.pbev_raw_row_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("cycle_year", sa.SmallInteger, nullable=False),
        sa.Column("brand_name", sa.String(80), nullable=False),
        sa.Column("model_name", sa.String(120), nullable=False),
        sa.Column("version_name", sa.String(255)),
        sa.Column("motor_description", sa.String(120)),
        sa.Column("transmission_code", sa.String(40)),
        sa.Column("propulsion_type", sa.String(30)),
        sa.Column("fuel_type", sa.String(30)),
        sa.Column("emission_schema_version", sa.String(50), nullable=False),
        sa.Column("nmhc_mg_km", sa.Numeric(14, 6)),
        sa.Column("nox_mg_km", sa.Numeric(14, 6)),
        sa.Column("nmog_nox_mg_km", sa.Numeric(14, 6)),
        sa.Column("co_mg_km", sa.Numeric(14, 6)),
        sa.Column("cho_mg_km", sa.Numeric(14, 6)),
        sa.Column("co2_ethanol_g_km", sa.Numeric(14, 6)),
        sa.Column("co2_fossil_g_km", sa.Numeric(14, 6)),
        sa.Column("ethanol_city_km_l", sa.Numeric(10, 4)),
        sa.Column("ethanol_highway_km_l", sa.Numeric(10, 4)),
        sa.Column("fossil_city_km_l", sa.Numeric(10, 4)),
        sa.Column("fossil_highway_km_l", sa.Numeric(10, 4)),
        sa.Column("electric_city_km_l_equivalent", sa.Numeric(10, 4)),
        sa.Column("electric_highway_km_l_equivalent", sa.Numeric(10, 4)),
        sa.Column("energy_mj_km", sa.Numeric(10, 4), nullable=False),
        sa.Column("pbe_relative_class", sa.String(10)),
        sa.Column("pbe_absolute_class", sa.String(10)),
        sa.Column("conpet_seal", sa.Boolean),
        sa.Column("parser_version", sa.String(40), nullable=False),
        sa.Column("matcher_version", sa.String(40), nullable=False),
        sa.Column("data_confidence", sa.Numeric(5, 2), nullable=False),
        sa.Column("quality_status", sa.String(20), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["dataset_version", "publication_run_id"], ["gold.vehicle_efficiency_dataset.dataset_version", "gold.vehicle_efficiency_dataset.publication_run_id"], name="fk_pbev_snapshot_dataset_run", ondelete="RESTRICT"),
        sa.CheckConstraint("data_confidence BETWEEN 0 AND 100", name="ck_pbev_snapshot_confidence"),
        sa.CheckConstraint("quality_status IN ('passed','warning')", name="ck_pbev_snapshot_quality"),
        sa.CheckConstraint("energy_mj_km > 0", name="ck_pbev_snapshot_energy"),
        sa.CheckConstraint("NOT (nmhc_mg_km IS NOT NULL AND nmog_nox_mg_km IS NOT NULL)", name="ck_pbev_snapshot_semantics"),
        sa.UniqueConstraint("dataset_version", "vehicle_sk", name="uq_pbev_snapshot_vehicle"),
        sa.UniqueConstraint("dataset_version", "observation_id", name="uq_pbev_snapshot_observation"),
        schema="gold",
    )
    op.create_index("ix_pbev_snapshot_vehicle", "vehicle_efficiency_snapshot", ["vehicle_sk", "cycle_year"], schema="gold")
    op.create_index("ix_pbev_snapshot_lineage", "vehicle_efficiency_snapshot", ["asset_id", "pbev_raw_row_id"], schema="gold")

    op.create_table(
        "vehicle_efficiency_quality_result",
        sa.Column("quality_result_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("dataset_version", sa.String(80), sa.ForeignKey("gold.vehicle_efficiency_dataset.dataset_version", ondelete="RESTRICT"), nullable=False),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("rule_code", sa.String(80), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("entity_name", sa.String(120), nullable=False),
        sa.Column("record_reference", sa.String(200)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("observed_value", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("expected_condition", sa.Text, nullable=False),
        sa.Column("details", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("severity IN ('info','warning','error','critical')", name="ck_pbev_quality_severity"),
        sa.CheckConstraint("status IN ('passed','warning','failed')", name="ck_pbev_quality_status"),
        schema="gold",
    )
    op.create_index(
        "uq_pbev_quality_result",
        "vehicle_efficiency_quality_result",
        ["dataset_version", "rule_code", sa.text("COALESCE(record_reference, '')")],
        unique=True,
        schema="gold",
    )
    op.create_index("ix_pbev_quality_dataset_status", "vehicle_efficiency_quality_result", ["dataset_version", "status"], schema="gold")


def _create_guards() -> None:
    op.execute(sa.text("""CREATE FUNCTION meta.prevent_pbev_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'PBEV lineage rows are immutable';
        END $$"""))
    for schema, table in (
        ("bronze", "pbev_source_asset"),
        ("bronze", "pbev_raw_row"),
        ("silver", "pbev_vehicle_mapping"),
        ("silver", "vehicle_efficiency_observation"),
        ("gold", "vehicle_efficiency_snapshot"),
        ("gold", "vehicle_efficiency_quality_result"),
    ):
        op.execute(sa.text(f"""CREATE TRIGGER trg_{table}_immutable
            BEFORE UPDATE OR DELETE ON {schema}.{table}
            FOR EACH ROW EXECUTE FUNCTION meta.prevent_pbev_mutation()"""))

    op.execute(sa.text("""CREATE FUNCTION gold.guard_pbev_dataset_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'PBEV datasets cannot be deleted';
            END IF;
            IF ROW(NEW.dataset_version,NEW.publication_run_id,NEW.source_system,
                   NEW.source_asset_manifest,NEW.source_asset_set_hash,
                   NEW.parser_version,NEW.matcher_version,NEW.universe_count,
                   NEW.eligible_count,NEW.matched_count,NEW.pending_count,
                   NEW.ambiguous_count,NEW.rejected_count,NEW.not_found_count,
                   NEW.published_count,NEW.coverage_percentage,NEW.coverage_report,
                   NEW.dataset_fingerprint,NEW.quality_status,NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.dataset_version,OLD.publication_run_id,OLD.source_system,
                   OLD.source_asset_manifest,OLD.source_asset_set_hash,
                   OLD.parser_version,OLD.matcher_version,OLD.universe_count,
                   OLD.eligible_count,OLD.matched_count,OLD.pending_count,
                   OLD.ambiguous_count,OLD.rejected_count,OLD.not_found_count,
                   OLD.published_count,OLD.coverage_percentage,OLD.coverage_report,
                   OLD.dataset_fingerprint,OLD.quality_status,OLD.created_at) THEN
                RAISE EXCEPTION 'PBEV dataset content is immutable';
            END IF;
            IF NOT ((OLD.status='building' AND NEW.status='shadow_published') OR
                    (OLD.status='shadow_published' AND NEW.status='retired')) THEN
                RAISE EXCEPTION 'Invalid PBEV dataset lifecycle transition';
            END IF;
            RETURN NEW;
        END $$"""))
    op.execute(sa.text("""CREATE TRIGGER trg_vehicle_efficiency_dataset_guard
        BEFORE UPDATE OR DELETE ON gold.vehicle_efficiency_dataset
        FOR EACH ROW EXECUTE FUNCTION gold.guard_pbev_dataset_mutation()"""))

    op.execute(sa.text("""CREATE FUNCTION gold.guard_pbev_snapshot_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE dataset_status VARCHAR(20);
        BEGIN
            SELECT status INTO dataset_status FROM gold.vehicle_efficiency_dataset
            WHERE dataset_version=NEW.dataset_version;
            IF dataset_status IS DISTINCT FROM 'building' THEN
                RAISE EXCEPTION 'PBEV snapshot inserts require a building dataset';
            END IF;
            RETURN NEW;
        END $$"""))
    op.execute(sa.text("""CREATE TRIGGER trg_pbev_snapshot_building
        BEFORE INSERT ON gold.vehicle_efficiency_snapshot
        FOR EACH ROW EXECUTE FUNCTION gold.guard_pbev_snapshot_insert()"""))


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
    # O preflight ocorre antes de qualquer DROP e preserva integralmente um
    # shadow publicado. O operador deve retira-lo formalmente antes do rollback.
    op.execute(sa.text("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM gold.vehicle_efficiency_dataset WHERE is_active_shadow) THEN
            RAISE EXCEPTION 'PBEV downgrade blocked: active shadow dataset exists';
        END IF;
    END $$"""))
    op.execute(sa.text("DROP TRIGGER trg_pbev_snapshot_building ON gold.vehicle_efficiency_snapshot"))
    op.execute(sa.text("DROP FUNCTION gold.guard_pbev_snapshot_insert()"))
    op.execute(sa.text("DROP TRIGGER trg_vehicle_efficiency_dataset_guard ON gold.vehicle_efficiency_dataset"))
    op.execute(sa.text("DROP FUNCTION gold.guard_pbev_dataset_mutation()"))
    for schema, table in reversed((
        ("bronze", "pbev_source_asset"),
        ("bronze", "pbev_raw_row"),
        ("silver", "pbev_vehicle_mapping"),
        ("silver", "vehicle_efficiency_observation"),
        ("gold", "vehicle_efficiency_snapshot"),
        ("gold", "vehicle_efficiency_quality_result"),
    )):
        op.execute(sa.text(f"DROP TRIGGER trg_{table}_immutable ON {schema}.{table}"))
    op.execute(sa.text("DROP FUNCTION meta.prevent_pbev_mutation()"))
    op.drop_index("uq_pbev_quality_result", table_name="vehicle_efficiency_quality_result", schema="gold")
    op.drop_index("ix_pbev_quality_dataset_status", table_name="vehicle_efficiency_quality_result", schema="gold")
    op.drop_table("vehicle_efficiency_quality_result", schema="gold")
    op.drop_index("ix_pbev_snapshot_lineage", table_name="vehicle_efficiency_snapshot", schema="gold")
    op.drop_index("ix_pbev_snapshot_vehicle", table_name="vehicle_efficiency_snapshot", schema="gold")
    op.drop_table("vehicle_efficiency_snapshot", schema="gold")
    op.drop_index("ix_pbev_dataset_fingerprint", table_name="vehicle_efficiency_dataset", schema="gold")
    op.drop_index("uq_pbev_dataset_active_shadow", table_name="vehicle_efficiency_dataset", schema="gold")
    op.drop_table("vehicle_efficiency_dataset", schema="gold")
    op.drop_index("ix_pbev_observation_quality", table_name="vehicle_efficiency_observation", schema="silver")
    op.drop_index("ix_pbev_observation_raw", table_name="vehicle_efficiency_observation", schema="silver")
    op.drop_index("ix_pbev_observation_vehicle_cycle", table_name="vehicle_efficiency_observation", schema="silver")
    op.drop_table("vehicle_efficiency_observation", schema="silver")
    op.execute(sa.text("DROP VIEW silver.pbev_vehicle_mapping_current"))
    op.drop_index("ix_pbev_mapping_raw", table_name="pbev_vehicle_mapping", schema="silver")
    op.drop_index("ix_pbev_mapping_vehicle", table_name="pbev_vehicle_mapping", schema="silver")
    op.drop_index("ix_pbev_mapping_status", table_name="pbev_vehicle_mapping", schema="silver")
    op.drop_table("pbev_vehicle_mapping", schema="silver")
    op.drop_index("ix_pbev_raw_hash", table_name="pbev_raw_row", schema="bronze")
    op.drop_index("ix_pbev_raw_status", table_name="pbev_raw_row", schema="bronze")
    op.drop_index("ix_pbev_raw_asset_page", table_name="pbev_raw_row", schema="bronze")
    op.drop_table("pbev_raw_row", schema="bronze")
    op.drop_index("ix_pbev_asset_status", table_name="pbev_source_asset", schema="bronze")
    op.drop_index("ix_pbev_asset_run", table_name="pbev_source_asset", schema="bronze")
    op.drop_table("pbev_source_asset", schema="bronze")
