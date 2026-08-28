"""Adiciona a Gold integrada como unidade canonica de orquestracao.

Revision ID: 20260811_0010
Revises: 20260811_0009
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260811_0010"
down_revision: Union[str, None] = "20260811_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_STEP_VALUES = (
    "bronze",
    "silver",
    "gold",
    "pbev",
    "anp_fuel_prices",
    "integrated_vehicle_cost",
)


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


def _create_consumption_view() -> None:
    op.execute(
        """CREATE VIEW gold.integrated_vehicle_cost_consumption_v1 AS
        SELECT dataset.dataset_version,
               dataset.fipe_source_dataset_version,
               dataset.pbev_source_dataset_version,
               dataset.anp_source_dataset_version,
               dataset.analytic_cutoff_at,
               dataset.calculation_policy_version,
               dataset.geography_policy_version,
               dataset.scenario_policy_version,
               dataset.quality_policy_version,
               dataset.published_vehicle_count,
               dataset.published_scenario_count,
               dataset.catalog_coverage_pct,
               dataset.pbev_coverage_pct,
               dataset.first_published_at,
               dataset.last_activated_at,
               snapshot.vehicle_sk,
               feature.brand_name,
               feature.model_name,
               feature.version_name,
               feature.model_year,
               snapshot.fuel_scenario_code,
               snapshot.requested_geography_level,
               snapshot.requested_geography_key,
               snapshot.anp_week_start,
               snapshot.anp_week_end,
               snapshot.vehicle_price_brl,
               snapshot.city_consumption_km_l,
               snapshot.highway_consumption_km_l,
               snapshot.fuel_price_per_liter_brl,
               snapshot.city_cost_per_km_brl,
               snapshot.highway_cost_per_km_brl,
               snapshot.mixed_cost_per_km_brl,
               snapshot.city_distance_share,
               snapshot.highway_distance_share,
               projection.scenario_code AS analytical_scenario_code,
               projection.monthly_distance_km AS analytical_monthly_distance_km,
               projection.annual_distance_km AS analytical_annual_distance_km,
               projection.projected_monthly_cost_brl
                   AS analytical_projected_monthly_cost_brl,
               projection.projected_annual_cost_brl
                   AS analytical_projected_annual_cost_brl
        FROM gold.integrated_vehicle_cost_dataset AS dataset
        JOIN gold.integrated_vehicle_cost_snapshot AS snapshot
          ON snapshot.dataset_version=dataset.dataset_version
        JOIN gold.integrated_vehicle_cost_projection_snapshot AS projection
          ON projection.dataset_version=snapshot.dataset_version
         AND projection.snapshot_id=snapshot.snapshot_id
        JOIN gold.vehicle_features_snapshot AS feature
          ON feature.gold_record_id=snapshot.fipe_gold_record_id
        WHERE dataset.is_active_shadow
          AND dataset.status='shadow_published'
          AND dataset.hard_gate_status='passed'
          AND dataset.quality_status='passed'
          AND dataset.coverage_regression_status<>'manual_review_required'
          AND NOT EXISTS (
              SELECT 1
              FROM gold.integrated_vehicle_cost_invalidation AS invalidation
              WHERE invalidation.dataset_version=dataset.dataset_version
          )"""
    )


def upgrade() -> None:
    # A orquestracao analitica permanece PostgreSQL-only; SQLite e no-op.
    if not _is_postgresql():
        return
    _replace_step_enum(_STEP_VALUES)
    _create_consumption_view()


def downgrade() -> None:
    if not _is_postgresql():
        return
    op.execute(
        sa.text(
            """DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM meta.orchestration_run
                    WHERE start_step='integrated_vehicle_cost'
                ) OR EXISTS (
                    SELECT 1 FROM meta.orchestration_step_run
                    WHERE step_name='integrated_vehicle_cost'
                ) THEN
                    RAISE EXCEPTION
                        'integrated vehicle cost orchestration downgrade blocked by history';
                END IF;
            END $$"""
        )
    )
    op.execute("DROP VIEW gold.integrated_vehicle_cost_consumption_v1")
    _replace_step_enum(_STEP_VALUES[:-1])
