"""Add isolated academic snapshots; no operational or Gold backfill.

Revision ID: 20261005_0013
Revises: 20260811_0012
"""
from alembic import op
import sqlalchemy as sa

revision = "20261005_0013"
down_revision = "20260811_0012"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return  # Complementary SQLite tests use isolated metadata, not migration fallback.
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS academic"))
    op.execute(sa.text("""CREATE TABLE academic.cohort_snapshot (
        snapshot_id uuid PRIMARY KEY,
        cohort_version varchar(60) NOT NULL,
        cohort_fingerprint varchar(64) NOT NULL CHECK (cohort_fingerprint ~ '^[0-9a-f]{64}$'),
        method_fingerprint varchar(64) NOT NULL CHECK (method_fingerprint ~ '^[0-9a-f]{64}$'),
        source_manifest jsonb NOT NULL,
        inventory_summary jsonb NOT NULL,
        selected_count integer NOT NULL CONSTRAINT ck_academic_snapshot_selected CHECK (selected_count=60),
        profile_counts jsonb NOT NULL,
        operationally_active boolean NOT NULL DEFAULT FALSE,
        recommended boolean NOT NULL DEFAULT FALSE,
        created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_academic_cohort_version_fingerprint UNIQUE (cohort_version,cohort_fingerprint),
        CONSTRAINT ck_academic_snapshot_no_activation CHECK (NOT operationally_active AND NOT recommended)
    )"""))
    op.execute(sa.text("""CREATE TABLE academic.cohort_vehicle (
        snapshot_id uuid NOT NULL REFERENCES academic.cohort_snapshot(snapshot_id),
        catalog_id integer NOT NULL,
        canonical_identity_key varchar(64) NOT NULL,
        fipe_code varchar(8) NOT NULL CHECK (fipe_code ~ '^[0-9]{6}-[0-9]$'),
        year_code varchar(12) NOT NULL,
        label varchar(240) NOT NULL,
        purchase_price_brl numeric(16,2) NOT NULL,
        reference_month varchar(7) NOT NULL,
        payload jsonb NOT NULL,
        payload_fingerprint varchar(64) NOT NULL,
        operationally_active boolean NOT NULL DEFAULT FALSE,
        recommended boolean NOT NULL DEFAULT FALSE,
        PRIMARY KEY (snapshot_id,catalog_id),
        CONSTRAINT uq_academic_vehicle_fipe UNIQUE (snapshot_id,fipe_code),
        CONSTRAINT uq_academic_vehicle_identity UNIQUE (snapshot_id,canonical_identity_key),
        CONSTRAINT ck_academic_vehicle_identity_price CHECK (catalog_id>0 AND purchase_price_brl>0),
        CONSTRAINT ck_academic_vehicle_reference_month CHECK (reference_month IN ('2026-09','2026-10')),
        CONSTRAINT ck_academic_vehicle_no_activation CHECK (NOT operationally_active AND NOT recommended)
    )"""))
    op.execute(sa.text("""CREATE TABLE academic.cohort_evaluation (
        snapshot_id uuid NOT NULL,
        catalog_id integer NOT NULL,
        profile varchar(16) NOT NULL,
        scenario varchar(8) NOT NULL,
        academic_test_ready boolean NOT NULL,
        score numeric(16,6),
        monthly_tco_brl numeric(16,2) NOT NULL,
        payload jsonb NOT NULL,
        payload_fingerprint varchar(64) NOT NULL,
        operationally_active boolean NOT NULL DEFAULT FALSE,
        recommended boolean NOT NULL DEFAULT FALSE,
        PRIMARY KEY (snapshot_id,catalog_id,profile,scenario),
        FOREIGN KEY (snapshot_id,catalog_id) REFERENCES academic.cohort_vehicle(snapshot_id,catalog_id),
        CONSTRAINT ck_academic_evaluation_profile CHECK (profile IN ('cidade','app','trabalho','suv','familia','estrada')),
        CONSTRAINT ck_academic_evaluation_scenario CHECK (scenario IN ('low','base','high')),
        CONSTRAINT ck_academic_evaluation_values CHECK (monthly_tco_brl>=0 AND (score IS NULL OR score BETWEEN 0 AND 100)),
        CONSTRAINT ck_academic_evaluation_no_activation CHECK (NOT operationally_active AND NOT recommended)
    )"""))
    op.execute(sa.text("""CREATE INDEX ix_academic_evaluation_filter
        ON academic.cohort_evaluation(snapshot_id,profile,scenario,academic_test_ready,catalog_id)"""))


def downgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    # Even an incomplete preexisting snapshot is historical data; never delete it.
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM academic.cohort_snapshot)")).scalar_one():
        raise RuntimeError("Academic downgrade blocked: historical snapshots must be preserved")
    op.drop_table("cohort_evaluation", schema="academic")
    op.drop_table("cohort_vehicle", schema="academic")
    op.drop_table("cohort_snapshot", schema="academic")
    # Keep the namespace: it may contain unrelated preexisting academic objects.
