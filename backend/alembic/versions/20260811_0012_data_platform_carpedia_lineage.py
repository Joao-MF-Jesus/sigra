"""Fortalece a linhagem CarPedia Silver para Gold.

Revision ID: 20260811_0012
Revises: 20260811_0011
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260811_0012"
down_revision: Union[str, None] = "20260811_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _create_lineage_audit() -> None:
    op.execute(sa.text("""CREATE FUNCTION meta.assert_carpedia_lineage_consistent()
        RETURNS void LANGUAGE plpgsql AS $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM silver.carpedia_vehicle_specification AS specification
            LEFT JOIN silver.carpedia_vehicle_mapping AS mapping
              ON mapping.mapping_decision_id=specification.mapping_decision_id
            WHERE mapping.mapping_decision_id IS NULL
               OR specification.raw_record_id IS DISTINCT FROM mapping.raw_record_id
               OR specification.vehicle_sk IS DISTINCT FROM mapping.vehicle_sk
               OR specification.mapping_status IS DISTINCT FROM mapping.mapping_status
          ) OR EXISTS (
            SELECT 1
            FROM silver.carpedia_vehicle_specification AS specification
            WHERE NOT EXISTS (
                    SELECT 1
                    FROM silver.carpedia_vehicle_specification AS successor
                    WHERE successor.supersedes_specification_id=specification.specification_id
                  )
              AND EXISTS (
                    SELECT 1
                    FROM silver.carpedia_vehicle_mapping AS successor
                    WHERE successor.supersedes_mapping_id=specification.mapping_decision_id
                  )
          ) OR EXISTS (
            SELECT 1
            FROM gold.carpedia_vehicle_spec_snapshot AS snapshot
            LEFT JOIN silver.carpedia_vehicle_specification AS specification
              ON specification.specification_id=snapshot.specification_id
            LEFT JOIN silver.carpedia_vehicle_mapping AS mapping
              ON mapping.mapping_decision_id=specification.mapping_decision_id
            WHERE specification.specification_id IS NULL
               OR mapping.mapping_decision_id IS NULL
               OR snapshot.vehicle_sk IS DISTINCT FROM specification.vehicle_sk
               OR snapshot.vehicle_sk IS DISTINCT FROM mapping.vehicle_sk
               OR specification.mapping_status IS DISTINCT FROM 'matched'
               OR mapping.mapping_status IS DISTINCT FROM 'matched'
               OR mapping.review_required
               OR mapping.confidence IS DISTINCT FROM 100
          ) THEN
            RAISE EXCEPTION 'Carpedia Silver-to-Gold lineage audit failed';
          END IF;
        END $$"""))
    # Falha transacionalmente diante de histórico inconsistente; nenhum dado é
    # reescrito ou corrigido silenciosamente.
    op.execute(sa.text("SELECT meta.assert_carpedia_lineage_consistent()"))


def _create_silver_insert_guard() -> None:
    op.execute(sa.text("""CREATE FUNCTION silver.guard_carpedia_specification_lineage()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE mapping_record silver.carpedia_vehicle_mapping%ROWTYPE;
        BEGIN
          SELECT * INTO mapping_record FROM silver.carpedia_vehicle_mapping
          WHERE mapping_decision_id=NEW.mapping_decision_id;
          IF NOT FOUND
             OR mapping_record.raw_record_id IS DISTINCT FROM NEW.raw_record_id
             OR mapping_record.vehicle_sk IS DISTINCT FROM NEW.vehicle_sk
             OR mapping_record.mapping_status IS DISTINCT FROM NEW.mapping_status
             OR EXISTS (
               SELECT 1 FROM silver.carpedia_vehicle_mapping AS successor
               WHERE successor.supersedes_mapping_id=NEW.mapping_decision_id
             ) THEN
            RAISE EXCEPTION 'Carpedia Silver specification lineage is inconsistent';
          END IF;
          RETURN NEW;
        END $$"""))
    op.execute(sa.text("""CREATE TRIGGER trg_carpedia_vehicle_specification_lineage
        BEFORE INSERT ON silver.carpedia_vehicle_specification
        FOR EACH ROW EXECUTE FUNCTION silver.guard_carpedia_specification_lineage()"""))


def _replace_gold_insert_guard() -> None:
    op.execute(sa.text("""CREATE OR REPLACE FUNCTION gold.guard_carpedia_child_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE dataset_status VARCHAR(20);
        BEGIN
          SELECT status INTO dataset_status FROM gold.carpedia_vehicle_spec_dataset
          WHERE dataset_version=NEW.dataset_version;
          IF dataset_status IS DISTINCT FROM 'building' THEN
            RAISE EXCEPTION 'Carpedia child inserts require a building dataset';
          END IF;
          IF TG_TABLE_NAME='carpedia_vehicle_spec_snapshot' AND NOT EXISTS (
            SELECT 1
            FROM silver.carpedia_vehicle_specification AS specification
            JOIN silver.carpedia_vehicle_mapping AS mapping
              ON mapping.mapping_decision_id=specification.mapping_decision_id
            WHERE specification.specification_id=NEW.specification_id
              AND specification.vehicle_sk=NEW.vehicle_sk
              AND mapping.vehicle_sk=NEW.vehicle_sk
              AND specification.mapping_status='matched'
              AND mapping.mapping_status='matched'
              AND mapping.confidence=100
              AND NOT mapping.review_required
              AND NOT EXISTS (
                SELECT 1 FROM silver.carpedia_vehicle_specification AS successor
                WHERE successor.supersedes_specification_id=specification.specification_id
              )
              AND NOT EXISTS (
                SELECT 1 FROM silver.carpedia_vehicle_mapping AS successor
                WHERE successor.supersedes_mapping_id=mapping.mapping_decision_id
              )
          ) THEN
            RAISE EXCEPTION 'Carpedia Gold snapshot lineage is not publishable';
          END IF;
          RETURN NEW;
        END $$"""))


def _create_defensive_downgrade_guard() -> None:
    op.execute(sa.text("""CREATE FUNCTION meta.assert_carpedia_lineage_downgrade_safe()
        RETURNS void LANGUAGE plpgsql AS $$
        BEGIN
          IF EXISTS (
            SELECT raw_record_id,normalized_fingerprint
            FROM silver.carpedia_vehicle_specification
            GROUP BY raw_record_id,normalized_fingerprint
            HAVING COUNT(*)>1
          ) THEN
            RAISE EXCEPTION 'Carpedia lineage downgrade blocked: mapping-specific history exists';
          END IF;
        END $$"""))


def upgrade() -> None:
    if not _is_postgresql():
        return
    _create_lineage_audit()
    op.drop_constraint(
        "uq_carpedia_spec_raw_fingerprint",
        "carpedia_vehicle_specification",
        schema="silver",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_carpedia_spec_raw_mapping_fingerprint",
        "carpedia_vehicle_specification",
        ["raw_record_id", "mapping_decision_id", "normalized_fingerprint"],
        schema="silver",
    )
    _create_silver_insert_guard()
    _replace_gold_insert_guard()
    _create_defensive_downgrade_guard()


def downgrade() -> None:
    if not _is_postgresql():
        return
    op.execute(sa.text("SELECT meta.assert_carpedia_lineage_consistent()"))
    op.execute(sa.text("SELECT meta.assert_carpedia_lineage_downgrade_safe()"))
    op.execute(sa.text("""CREATE OR REPLACE FUNCTION gold.guard_carpedia_child_insert()
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
    op.execute(sa.text(
        "DROP TRIGGER trg_carpedia_vehicle_specification_lineage "
        "ON silver.carpedia_vehicle_specification"
    ))
    op.execute(sa.text("DROP FUNCTION silver.guard_carpedia_specification_lineage()"))
    op.drop_constraint(
        "uq_carpedia_spec_raw_mapping_fingerprint",
        "carpedia_vehicle_specification",
        schema="silver",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_carpedia_spec_raw_fingerprint",
        "carpedia_vehicle_specification",
        ["raw_record_id", "normalized_fingerprint"],
        schema="silver",
    )
    op.execute(sa.text("DROP FUNCTION meta.assert_carpedia_lineage_downgrade_safe()"))
    op.execute(sa.text("DROP FUNCTION meta.assert_carpedia_lineage_consistent()"))
