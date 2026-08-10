"""Cria a primeira fatia Gold de atributos FIPE de veiculos.

Revision ID: 20260803_0004
Revises: 20260803_0003
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260803_0004"
down_revision: Union[str, None] = "20260803_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SOURCE_NAME = "Tabela FIPE via API Parallelum"


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _upgrade_silver_mapping_type() -> None:
    op.add_column(
        "vehicle_source_mapping",
        sa.Column("vehicle_type", sa.String(20), nullable=True),
        schema="silver",
    )
    op.execute(
        sa.text(
            """UPDATE silver.vehicle_source_mapping AS mapping
            SET vehicle_type = bronze.vehicle_type
            FROM bronze.fipe_raw AS bronze
            WHERE bronze.fipe_raw_id = mapping.bronze_record_id
              AND mapping.vehicle_type IS NULL"""
        )
    )
    # A chave bruta pode divergir em registros ambiguos. A validacao usa a
    # chave Silver deterministica e preserva a evidencia Bronze sem reescreve-la.
    op.execute(
        sa.text(
            """DO $$
            DECLARE
                invalid_count BIGINT;
            BEGIN
                SELECT COUNT(*)
                  INTO invalid_count
                  FROM silver.vehicle_source_mapping AS mapping
                  LEFT JOIN bronze.fipe_raw AS bronze
                    ON bronze.fipe_raw_id = mapping.bronze_record_id
                  LEFT JOIN silver.vehicle_identity AS identity
                    ON identity.vehicle_sk = mapping.vehicle_sk
                 WHERE bronze.fipe_raw_id IS NULL
                    OR mapping.vehicle_type IS NULL
                    OR mapping.vehicle_type NOT IN ('car','motorcycle','truck')
                    OR bronze.vehicle_type IS DISTINCT FROM mapping.vehicle_type
                    OR bronze.source_name IS DISTINCT FROM mapping.source_name
                    OR bronze.fipe_code IS DISTINCT FROM mapping.fipe_code
                    OR bronze.year_code IS DISTINCT FROM mapping.year_code
                    OR bronze.ingestion_status <> 'received'
                    OR bronze.http_status NOT BETWEEN 200 AND 299
                    OR bronze.payload IS NULL
                    OR mapping.source_vehicle_key IS DISTINCT FROM
                       (mapping.fipe_code || ':' || mapping.year_code)
                    OR (
                        mapping.vehicle_sk IS NOT NULL
                        AND (
                            identity.vehicle_sk IS NULL
                            OR identity.vehicle_type IS DISTINCT FROM mapping.vehicle_type
                        )
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM silver.vehicle_price_history AS price
                        WHERE price.source_mapping_id = mapping.mapping_id
                          AND (
                              price.vehicle_sk IS DISTINCT FROM mapping.vehicle_sk
                              OR price.source_name IS DISTINCT FROM mapping.source_name
                          )
                    );

                IF invalid_count > 0 THEN
                    RAISE EXCEPTION USING
                        ERRCODE = 'check_violation',
                        MESSAGE = format(
                            'Silver vehicle_type backfill aborted: invalid lineage rows=%s',
                            invalid_count
                        );
                END IF;
            END
            $$"""
        )
    )
    op.execute(
        sa.text(
            """ALTER TABLE silver.vehicle_source_mapping
            ADD CONSTRAINT ck_vehicle_source_mapping_vehicle_type
            CHECK (vehicle_type IN ('car','motorcycle','truck')) NOT VALID"""
        )
    )
    op.execute(
        sa.text(
            """ALTER TABLE silver.vehicle_source_mapping
            VALIDATE CONSTRAINT ck_vehicle_source_mapping_vehicle_type"""
        )
    )
    op.alter_column(
        "vehicle_source_mapping",
        "vehicle_type",
        existing_type=sa.String(20),
        nullable=False,
        schema="silver",
    )

    op.drop_index(
        "ix_vehicle_source_mapping_review",
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
    op.drop_constraint(
        "uq_vehicle_source_mapping_version",
        "vehicle_source_mapping",
        schema="silver",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_vehicle_source_mapping_version",
        "vehicle_source_mapping",
        ["source_name", "vehicle_type", "source_vehicle_key", "valid_from"],
        schema="silver",
    )
    op.create_index(
        "uq_vehicle_source_mapping_current_key",
        "vehicle_source_mapping",
        ["source_name", "vehicle_type", "source_vehicle_key"],
        unique=True,
        schema="silver",
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.create_index(
        "uq_vehicle_source_mapping_current_fipe",
        "vehicle_source_mapping",
        ["source_name", "vehicle_type", "fipe_code", "year_code"],
        unique=True,
        schema="silver",
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.create_index(
        "ix_vehicle_source_mapping_review",
        "vehicle_source_mapping",
        ["source_name", "vehicle_type", "mapping_status"],
        schema="silver",
        postgresql_where=sa.text("valid_to IS NULL"),
    )


def _create_gold_tables() -> None:
    op.execute(
        sa.text(
            """DO $$
            DECLARE
                invalid_count BIGINT;
            BEGIN
                SELECT COUNT(*)
                  INTO invalid_count
                  FROM meta.data_quality_issue
                 WHERE (resolution_status = 'open' AND resolved_at IS NOT NULL)
                    OR (resolution_status <> 'open' AND resolved_at IS NULL);
                IF invalid_count > 0 THEN
                    RAISE EXCEPTION USING
                        ERRCODE = 'check_violation',
                        MESSAGE = format(
                            'Gold migration aborted: invalid issue resolution rows=%s',
                            invalid_count
                        );
                END IF;
            END
            $$"""
        )
    )
    op.execute(
        sa.text(
            """ALTER TABLE meta.data_quality_issue
            ADD CONSTRAINT ck_data_quality_issue_resolution_timestamp
            CHECK (
                (resolution_status = 'open' AND resolved_at IS NULL)
                OR (resolution_status <> 'open' AND resolved_at IS NOT NULL)
            ) NOT VALID"""
        )
    )
    op.execute(
        sa.text(
            """ALTER TABLE meta.data_quality_issue
            VALIDATE CONSTRAINT ck_data_quality_issue_resolution_timestamp"""
        )
    )
    op.create_index(
        "uq_data_quality_issue_open_gold",
        "data_quality_issue",
        ["layer_name", "entity_name", "record_reference", "rule_code"],
        unique=True,
        schema="meta",
        postgresql_where=sa.text(
            "layer_name = 'gold' AND resolution_status = 'open'"
        ),
    )

    op.create_table(
        "vehicle_feature_dataset",
        sa.Column("dataset_version", sa.String(80), primary_key=True),
        sa.Column(
            "publication_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("dataset_fingerprint", sa.CHAR(64), nullable=False),
        sa.Column("scope_vehicle_type", sa.String(20), nullable=False),
        sa.Column("source_name", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("expected_vehicle_count", sa.Integer, nullable=False),
        sa.Column("published_vehicle_count", sa.Integer, nullable=False),
        sa.Column("blocked_vehicle_count", sa.Integer, nullable=False),
        sa.Column("coverage_percentage", sa.Numeric(5, 2), nullable=False),
        sa.Column("minimum_reference_month", sa.Date, nullable=False),
        sa.Column("maximum_reference_month", sa.Date, nullable=False),
        sa.Column("base_quality_status", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.Column("last_activation_event_id", sa.BigInteger),
        sa.Column("activation_run_id", postgresql.UUID(as_uuid=True)),
        sa.CheckConstraint(
            "dataset_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_gold_dataset_fingerprint",
        ),
        sa.CheckConstraint(
            "scope_vehicle_type = 'car'",
            name="ck_gold_dataset_vehicle_type",
        ),
        sa.CheckConstraint(
            f"source_name = '{SOURCE_NAME}'",
            name="ck_gold_dataset_source",
        ),
        sa.CheckConstraint(
            "status IN ('building','published','retired')",
            name="ck_gold_dataset_status",
        ),
        sa.CheckConstraint(
            "base_quality_status IN ('passed','warning')",
            name="ck_gold_dataset_quality",
        ),
        sa.CheckConstraint(
            "expected_vehicle_count > 0 AND published_vehicle_count > 0 "
            "AND published_vehicle_count <= expected_vehicle_count "
            "AND blocked_vehicle_count = expected_vehicle_count - published_vehicle_count",
            name="ck_gold_dataset_counts",
        ),
        sa.CheckConstraint(
            "coverage_percentage = ROUND("
            "published_vehicle_count::numeric * 100 / expected_vehicle_count, 2) "
            "AND coverage_percentage BETWEEN 80.00 AND 100.00",
            name="ck_gold_dataset_coverage",
        ),
        sa.CheckConstraint(
            "minimum_reference_month <= maximum_reference_month "
            "AND EXTRACT(DAY FROM minimum_reference_month) = 1 "
            "AND EXTRACT(DAY FROM maximum_reference_month) = 1",
            name="ck_gold_dataset_reference_range",
        ),
        sa.CheckConstraint(
            "(status = 'building' AND NOT is_active AND published_at IS NULL "
            " AND retired_at IS NULL AND last_activation_event_id IS NULL "
            " AND activation_run_id IS NULL) OR "
            "(status = 'published' AND is_active AND published_at IS NOT NULL "
            " AND retired_at IS NULL AND last_activation_event_id IS NOT NULL "
            " AND activation_run_id IS NOT NULL) OR "
            "(status = 'retired' AND NOT is_active AND published_at IS NOT NULL "
            " AND retired_at IS NOT NULL AND last_activation_event_id IS NOT NULL "
            " AND activation_run_id IS NOT NULL)",
            name="ck_gold_dataset_lifecycle",
        ),
        sa.CheckConstraint(
            "published_at IS NULL OR published_at >= created_at",
            name="ck_gold_dataset_published_at",
        ),
        sa.CheckConstraint(
            "retired_at IS NULL OR retired_at >= published_at",
            name="ck_gold_dataset_retired_at",
        ),
        sa.UniqueConstraint(
            "dataset_version",
            "publication_run_id",
            name="uq_gold_dataset_version_run",
        ),
        schema="gold",
    )
    op.create_index(
        "uq_gold_vehicle_feature_dataset_active",
        "vehicle_feature_dataset",
        ["is_active"],
        unique=True,
        schema="gold",
        postgresql_where=sa.text("is_active"),
    )
    op.create_index(
        "ix_gold_vehicle_feature_dataset_fingerprint",
        "vehicle_feature_dataset",
        ["dataset_fingerprint"],
        schema="gold",
    )

    op.create_table(
        "vehicle_features_snapshot",
        sa.Column("gold_record_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("dataset_version", sa.String(80), nullable=False),
        sa.Column("vehicle_sk", sa.BigInteger, sa.ForeignKey("silver.vehicle_identity.vehicle_sk", ondelete="RESTRICT"), nullable=False),
        sa.Column("vehicle_type", sa.String(20), nullable=False),
        sa.Column("brand_name", sa.String(80), nullable=False),
        sa.Column("model_name", sa.String(120), nullable=False),
        sa.Column("version_name", sa.String(180)),
        sa.Column("model_year", sa.SmallInteger),
        sa.Column("is_zero_km", sa.Boolean, nullable=False),
        sa.Column("fuel_type", sa.String(30), nullable=False),
        sa.Column("transmission_type", sa.String(30)),
        sa.Column("source_mapping_id", sa.BigInteger, sa.ForeignKey("silver.vehicle_source_mapping.mapping_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("silver_price_id", sa.BigInteger, sa.ForeignKey("silver.vehicle_price_history.vehicle_price_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("fipe_code", sa.String(20), nullable=False),
        sa.Column("year_code", sa.String(30), nullable=False),
        sa.Column("source_vehicle_key", sa.String(160), nullable=False),
        sa.Column("current_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("price_source", sa.String(80), nullable=False),
        sa.Column("price_reference_month", sa.Date, nullable=False),
        sa.Column("price_collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_confidence", sa.Numeric(5, 2), nullable=False),
        sa.Column("base_quality_status", sa.String(20), nullable=False),
        sa.Column("silver_identity_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("silver_mapping_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("silver_price_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("publication_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_version", "publication_run_id"],
            ["gold.vehicle_feature_dataset.dataset_version", "gold.vehicle_feature_dataset.publication_run_id"],
            name="fk_gold_snapshot_dataset_run",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("vehicle_type = 'car'", name="ck_gold_snapshot_vehicle_type"),
        sa.CheckConstraint(f"price_source = '{SOURCE_NAME}'", name="ck_gold_snapshot_source"),
        sa.CheckConstraint("current_price > 0", name="ck_gold_snapshot_price"),
        sa.CheckConstraint("currency = 'BRL'", name="ck_gold_snapshot_currency"),
        sa.CheckConstraint("data_confidence BETWEEN 0 AND 100", name="ck_gold_snapshot_confidence"),
        sa.CheckConstraint("base_quality_status IN ('passed','warning')", name="ck_gold_snapshot_quality"),
        sa.CheckConstraint(
            "EXTRACT(DAY FROM price_reference_month) = 1 "
            "AND price_reference_month <= published_at::date",
            name="ck_gold_snapshot_reference_month",
        ),
        sa.CheckConstraint(
            "price_collected_at <= published_at",
            name="ck_gold_snapshot_collection_time",
        ),
        sa.CheckConstraint(
            "(is_zero_km AND model_year IS NULL) OR "
            "(NOT is_zero_km AND model_year BETWEEN 1900 AND 2100)",
            name="ck_gold_snapshot_model_year",
        ),
        sa.UniqueConstraint("dataset_version", "vehicle_sk", name="uq_gold_snapshot_vehicle"),
        sa.UniqueConstraint("dataset_version", "source_mapping_id", name="uq_gold_snapshot_mapping"),
        sa.UniqueConstraint("dataset_version", "silver_price_id", name="uq_gold_snapshot_price"),
        schema="gold",
    )
    op.create_index(
        "ix_gold_snapshot_vehicle",
        "vehicle_features_snapshot",
        ["vehicle_sk"],
        schema="gold",
    )
    op.create_index(
        "ix_gold_snapshot_reference",
        "vehicle_features_snapshot",
        ["price_reference_month"],
        schema="gold",
    )
    op.create_index(
        "ix_gold_snapshot_mapping_lineage",
        "vehicle_features_snapshot",
        ["source_mapping_id", "silver_price_id"],
        schema="gold",
    )

    op.create_table(
        "vehicle_feature_dataset_activation",
        sa.Column("activation_event_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("dataset_version", sa.String(80), sa.ForeignKey("gold.vehicle_feature_dataset.dataset_version", ondelete="RESTRICT"), nullable=False),
        sa.Column("activation_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meta.pipeline_run.pipeline_run_id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("previous_dataset_version", sa.String(80), sa.ForeignKey("gold.vehicle_feature_dataset.dataset_version", ondelete="RESTRICT")),
        sa.Column("activation_type", sa.String(20), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("activation_type IN ('initial','replacement','rollback')", name="ck_gold_activation_type"),
        sa.CheckConstraint(
            "(activation_type = 'initial' AND previous_dataset_version IS NULL) OR "
            "(activation_type IN ('replacement','rollback') "
            " AND previous_dataset_version IS NOT NULL "
            " AND previous_dataset_version <> dataset_version)",
            name="ck_gold_activation_previous",
        ),
        sa.UniqueConstraint(
            "dataset_version",
            "activation_event_id",
            "activation_run_id",
            name="uq_gold_activation_dataset_event_run",
        ),
        schema="gold",
    )
    op.create_index(
        "ix_gold_activation_dataset_time",
        "vehicle_feature_dataset_activation",
        ["dataset_version", sa.text("activated_at DESC")],
        schema="gold",
    )
    op.create_index(
        "ix_gold_activation_timeline",
        "vehicle_feature_dataset_activation",
        ["activated_at", "activation_event_id"],
        schema="gold",
    )
    op.create_foreign_key(
        "fk_gold_dataset_last_activation",
        "vehicle_feature_dataset",
        "vehicle_feature_dataset_activation",
        ["dataset_version", "last_activation_event_id", "activation_run_id"],
        ["dataset_version", "activation_event_id", "activation_run_id"],
        source_schema="gold",
        referent_schema="gold",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )

    op.execute(
        sa.text(
            """CREATE FUNCTION gold.guard_vehicle_features_snapshot()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                dataset_status VARCHAR(20);
            BEGIN
                IF TG_OP <> 'INSERT' THEN
                    RAISE EXCEPTION 'Gold snapshots are immutable';
                END IF;
                SELECT status INTO dataset_status
                FROM gold.vehicle_feature_dataset
                WHERE dataset_version = NEW.dataset_version;
                IF dataset_status IS DISTINCT FROM 'building' THEN
                    RAISE EXCEPTION 'Gold snapshot inserts require a building dataset';
                END IF;
                RETURN NEW;
            END
            $$"""
        )
    )
    op.execute(
        sa.text(
            """CREATE TRIGGER trg_gold_snapshot_immutable
            BEFORE INSERT OR UPDATE OR DELETE ON gold.vehicle_features_snapshot
            FOR EACH ROW EXECUTE FUNCTION gold.guard_vehicle_features_snapshot()"""
        )
    )
    op.execute(
        sa.text(
            """CREATE FUNCTION gold.prevent_activation_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'Gold activation events are immutable';
            END
            $$"""
        )
    )
    op.execute(
        sa.text(
            """CREATE TRIGGER trg_gold_activation_immutable
            BEFORE UPDATE OR DELETE ON gold.vehicle_feature_dataset_activation
            FOR EACH ROW EXECUTE FUNCTION gold.prevent_activation_mutation()"""
        )
    )

    op.execute(
        sa.text(
            """CREATE VIEW gold.vehicle_features_current AS
            SELECT
                snapshot.gold_record_id,
                snapshot.dataset_version,
                snapshot.vehicle_sk,
                snapshot.vehicle_type,
                snapshot.brand_name,
                snapshot.model_name,
                snapshot.version_name,
                snapshot.model_year,
                snapshot.is_zero_km,
                snapshot.fuel_type,
                snapshot.transmission_type,
                snapshot.source_mapping_id,
                snapshot.silver_price_id,
                snapshot.fipe_code,
                snapshot.year_code,
                snapshot.source_vehicle_key,
                snapshot.current_price,
                snapshot.currency,
                snapshot.price_source,
                snapshot.price_reference_month,
                snapshot.price_collected_at,
                GREATEST(CURRENT_DATE - snapshot.price_reference_month, 0)::integer
                    AS price_age_days,
                CASE
                    WHEN CURRENT_DATE - snapshot.price_reference_month <= 45 THEN 'current'
                    WHEN CURRENT_DATE - snapshot.price_reference_month <= 90 THEN 'stale'
                    ELSE 'expired'
                END AS freshness_status,
                snapshot.data_confidence,
                snapshot.base_quality_status,
                CASE
                    WHEN snapshot.base_quality_status = 'passed'
                     AND CURRENT_DATE - snapshot.price_reference_month <= 45
                    THEN 'passed'
                    ELSE 'warning'
                END AS quality_status,
                snapshot.silver_identity_run_id,
                snapshot.silver_mapping_run_id,
                snapshot.silver_price_run_id,
                snapshot.publication_run_id,
                snapshot.published_at,
                dataset.coverage_percentage,
                TRUE AS is_current_dataset
            FROM gold.vehicle_features_snapshot AS snapshot
            JOIN gold.vehicle_feature_dataset AS dataset
              ON dataset.dataset_version = snapshot.dataset_version
            WHERE dataset.is_active
              AND dataset.status = 'published'"""
        )
    )


def upgrade() -> None:
    if not _is_postgresql():
        return
    _upgrade_silver_mapping_type()
    _create_gold_tables()


def _abort_incompatible_downgrade() -> None:
    op.execute(
        sa.text(
            """DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM silver.vehicle_source_mapping
                    GROUP BY source_name,source_vehicle_key,valid_from
                    HAVING COUNT(*) > 1
                ) OR EXISTS (
                    SELECT 1
                    FROM silver.vehicle_source_mapping
                    WHERE valid_to IS NULL
                    GROUP BY source_name,source_vehicle_key
                    HAVING COUNT(*) > 1
                ) OR EXISTS (
                    SELECT 1
                    FROM silver.vehicle_source_mapping
                    WHERE valid_to IS NULL
                    GROUP BY source_name,fipe_code,year_code
                    HAVING COUNT(*) > 1
                ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = 'unique_violation',
                        MESSAGE = 'Downgrade to 20260803_0003 aborted: mappings collide under the previous identity contract';
                END IF;
            END
            $$"""
        )
    )


def _drop_gold_tables() -> None:
    op.execute(sa.text("DROP VIEW gold.vehicle_features_current"))
    op.drop_constraint(
        "fk_gold_dataset_last_activation",
        "vehicle_feature_dataset",
        schema="gold",
        type_="foreignkey",
    )
    op.execute(sa.text("DROP TRIGGER trg_gold_activation_immutable ON gold.vehicle_feature_dataset_activation"))
    op.execute(sa.text("DROP FUNCTION gold.prevent_activation_mutation()"))
    op.execute(sa.text("DROP TRIGGER trg_gold_snapshot_immutable ON gold.vehicle_features_snapshot"))
    op.execute(sa.text("DROP FUNCTION gold.guard_vehicle_features_snapshot()"))
    op.drop_index("ix_gold_activation_timeline", table_name="vehicle_feature_dataset_activation", schema="gold")
    op.drop_index("ix_gold_activation_dataset_time", table_name="vehicle_feature_dataset_activation", schema="gold")
    op.drop_table("vehicle_feature_dataset_activation", schema="gold")
    op.drop_index("ix_gold_snapshot_mapping_lineage", table_name="vehicle_features_snapshot", schema="gold")
    op.drop_index("ix_gold_snapshot_reference", table_name="vehicle_features_snapshot", schema="gold")
    op.drop_index("ix_gold_snapshot_vehicle", table_name="vehicle_features_snapshot", schema="gold")
    op.drop_table("vehicle_features_snapshot", schema="gold")
    op.drop_index("ix_gold_vehicle_feature_dataset_fingerprint", table_name="vehicle_feature_dataset", schema="gold")
    op.drop_index("uq_gold_vehicle_feature_dataset_active", table_name="vehicle_feature_dataset", schema="gold")
    op.drop_table("vehicle_feature_dataset", schema="gold")
    op.drop_index("uq_data_quality_issue_open_gold", table_name="data_quality_issue", schema="meta")
    op.drop_constraint(
        "ck_data_quality_issue_resolution_timestamp",
        "data_quality_issue",
        schema="meta",
        type_="check",
    )


def _downgrade_silver_mapping_type() -> None:
    op.drop_index("ix_vehicle_source_mapping_review", table_name="vehicle_source_mapping", schema="silver")
    op.drop_index("uq_vehicle_source_mapping_current_fipe", table_name="vehicle_source_mapping", schema="silver")
    op.drop_index("uq_vehicle_source_mapping_current_key", table_name="vehicle_source_mapping", schema="silver")
    op.drop_constraint(
        "uq_vehicle_source_mapping_version",
        "vehicle_source_mapping",
        schema="silver",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_vehicle_source_mapping_version",
        "vehicle_source_mapping",
        ["source_name", "source_vehicle_key", "valid_from"],
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
        "ix_vehicle_source_mapping_review",
        "vehicle_source_mapping",
        ["mapping_status", "source_name"],
        schema="silver",
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.drop_constraint(
        "ck_vehicle_source_mapping_vehicle_type",
        "vehicle_source_mapping",
        schema="silver",
        type_="check",
    )
    op.drop_column("vehicle_source_mapping", "vehicle_type", schema="silver")


def downgrade() -> None:
    if not _is_postgresql():
        return
    # O preflight ocorre antes de qualquer DROP. Uma colisao deixa a revision
    # 0004 e todos os dados completamente intactos.
    _abort_incompatible_downgrade()
    _drop_gold_tables()
    _downgrade_silver_mapping_type()
