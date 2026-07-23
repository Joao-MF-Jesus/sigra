"""Schema inicial completo do SIGRA.

Revision ID: 20260723_0001
Revises:
Create Date: 2026-07-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260723_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MONEY = sa.Numeric(14, 2)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("email", sa.String(160), nullable=False, unique=True),
    )
    op.create_table(
        "sigra_schema_migrations",
        sa.Column("version", sa.String(40), primary_key=True),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "vehicles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("brand", sa.String(80), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("price", MONEY, nullable=False),
        sa.Column("fuel_efficiency_km_l", sa.Float(), nullable=False),
        sa.Column("annual_maintenance_cost", MONEY, nullable=False),
        sa.Column("reliability_score", sa.Float(), nullable=False),
        sa.Column("parts_availability_score", sa.Float(), nullable=False),
        sa.Column("depreciation_rate", sa.Float(), nullable=False),
        sa.Column("use_cases", sa.Text(), nullable=False),
        sa.Column("chronic_issues", sa.Text(), nullable=False),
        sa.Column("image_url", sa.String(240), nullable=False),
        sa.Column("category", sa.String(60), nullable=False),
        sa.Column("segment_level", sa.Integer(), nullable=False),
        sa.Column("comfort_score", sa.Float(), nullable=False),
        sa.Column("space_score", sa.Float(), nullable=False),
        sa.Column("safety_score", sa.Float(), nullable=False),
        sa.Column("urban_score", sa.Float(), nullable=False),
        sa.Column("road_score", sa.Float(), nullable=False),
        sa.Column("family_score", sa.Float(), nullable=False),
        sa.Column("app_score", sa.Float(), nullable=False),
        sa.Column(
            "vehicle_type",
            sa.String(20),
            nullable=False,
            server_default="car",
        ),
    )
    op.create_table(
        "motorcycles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("brand", sa.String(80), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("price", MONEY, nullable=False),
        sa.Column("city_consumption", sa.Float(), nullable=False),
        sa.Column("road_consumption", sa.Float(), nullable=False),
        sa.Column("annual_maintenance_cost", MONEY, nullable=True),
        sa.Column("reliability_score", sa.Float(), nullable=True),
        sa.Column("parts_availability_score", sa.Float(), nullable=True),
        sa.Column("depreciation_rate", sa.Float(), nullable=True),
        sa.Column("data_source", sa.String(30), nullable=True),
        sa.Column("data_confidence", sa.Float(), nullable=True),
        sa.Column("source_name", sa.String(160), nullable=True),
        sa.Column("source_reference", sa.String(240), nullable=True),
        sa.Column("source_url", sa.String(500), nullable=True),
        sa.Column("source_collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_reference_date", sa.Date(), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "vehicle_type",
            sa.String(20),
            nullable=False,
            server_default="motorcycle",
        ),
        sa.Column("image_url", sa.String(240), nullable=False, server_default=""),
        sa.Column("version", sa.String(120), nullable=True),
        sa.Column("market_condition", sa.String(20), nullable=True),
        sa.Column("fuel_type", sa.String(30), nullable=True),
        sa.Column("price_reference_date", sa.Date(), nullable=True),
        sa.Column(
            "is_demonstration",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.CheckConstraint("price > 0", name="ck_motorcycles_price_positive"),
        sa.CheckConstraint(
            "city_consumption > 0",
            name="ck_motorcycles_city_consumption_positive",
        ),
        sa.CheckConstraint(
            "road_consumption > 0",
            name="ck_motorcycles_road_consumption_positive",
        ),
        sa.CheckConstraint(
            "annual_maintenance_cost IS NULL OR annual_maintenance_cost >= 0",
            name="ck_motorcycles_maintenance_nonnegative",
        ),
        sa.CheckConstraint(
            "reliability_score IS NULL OR reliability_score BETWEEN 0 AND 100",
            name="ck_motorcycles_reliability_range",
        ),
        sa.CheckConstraint(
            "parts_availability_score IS NULL OR "
            "parts_availability_score BETWEEN 0 AND 100",
            name="ck_motorcycles_parts_range",
        ),
        sa.CheckConstraint(
            "depreciation_rate IS NULL OR depreciation_rate >= 0",
            name="ck_motorcycles_depreciation_nonnegative",
        ),
        sa.CheckConstraint(
            "data_confidence IS NULL OR data_confidence BETWEEN 0 AND 100",
            name="ck_motorcycles_confidence_range",
        ),
        sa.CheckConstraint(
            "vehicle_type = 'motorcycle'",
            name="ck_motorcycles_vehicle_type",
        ),
    )
    op.create_index(
        "ix_motorcycles_brand_model_year",
        "motorcycles",
        ["brand", "model", "year"],
    )
    op.create_index(
        "ix_motorcycles_data_source",
        "motorcycles",
        ["data_source"],
    )
    op.create_table(
        "parts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("category", sa.String(60), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("original_code", sa.String(80), nullable=False),
        sa.Column("alternative_codes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "suppliers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(140), nullable=False),
        sa.Column("website", sa.String(240), nullable=False),
        sa.Column("city", sa.String(80), nullable=False),
        sa.Column("state", sa.String(2), nullable=False),
        sa.Column("type", sa.String(60), nullable=False),
        sa.Column("reliability_score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "expenses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "vehicle_id",
            sa.Integer(),
            sa.ForeignKey("vehicles.id"),
            nullable=False,
        ),
        sa.Column("category", sa.String(60), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
    )
    op.create_table(
        "maintenances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "vehicle_id",
            sa.Integer(),
            sa.ForeignKey("vehicles.id"),
            nullable=False,
        ),
        sa.Column("service_type", sa.String(120), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("completed_date", sa.Date(), nullable=True),
        sa.Column("cost", MONEY, nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
    )
    op.create_table(
        "motorcycle_data_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "motorcycle_id",
            sa.Integer(),
            sa.ForeignKey("motorcycles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("data_group", sa.String(40), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("source_name", sa.String(160), nullable=True),
        sa.Column("source_reference", sa.String(240), nullable=True),
        sa.Column("source_url", sa.String(500), nullable=True),
        sa.Column("reference_date", sa.Date(), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("methodology_notes", sa.Text(), nullable=True),
        sa.Column(
            "is_primary",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
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
            "confidence IS NULL OR confidence BETWEEN 0 AND 100",
            name="ck_motorcycle_sources_confidence",
        ),
    )
    op.create_index(
        "ix_motorcycle_sources_group",
        "motorcycle_data_sources",
        ["motorcycle_id", "data_group"],
    )
    op.create_index(
        "uq_motorcycle_primary_source_per_group",
        "motorcycle_data_sources",
        ["motorcycle_id", "data_group"],
        unique=True,
        sqlite_where=sa.text("is_primary = 1"),
        postgresql_where=sa.text("is_primary = true"),
    )
    op.create_table(
        "motorcycle_specifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "motorcycle_id",
            sa.Integer(),
            sa.ForeignKey("motorcycles.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("engine_displacement_cc", sa.Float(), nullable=False),
        sa.Column("motorcycle_category", sa.String(30), nullable=False),
        sa.Column("wet_weight_kg", sa.Float(), nullable=False),
        sa.Column("seat_height_mm", sa.Float(), nullable=False),
        sa.Column("tank_capacity_l", sa.Float(), nullable=False),
        sa.Column("has_abs", sa.Boolean(), nullable=False),
        sa.Column("recommended_experience", sa.String(30), nullable=False),
        sa.Column("urban_score", sa.Float(), nullable=False),
        sa.Column("road_score", sa.Float(), nullable=False),
        sa.Column("passenger_comfort_score", sa.Float(), nullable=False),
        sa.Column("luggage_score", sa.Float(), nullable=False),
        sa.CheckConstraint(
            "engine_displacement_cc > 0 AND engine_displacement_cc <= 3000",
            name="ck_motorcycle_specs_displacement",
        ),
        sa.CheckConstraint(
            "wet_weight_kg >= 20 AND wet_weight_kg <= 600",
            name="ck_motorcycle_specs_weight",
        ),
        sa.CheckConstraint(
            "seat_height_mm >= 400 AND seat_height_mm <= 1200",
            name="ck_motorcycle_specs_seat",
        ),
        sa.CheckConstraint(
            "tank_capacity_l >= 1 AND tank_capacity_l <= 50",
            name="ck_motorcycle_specs_tank",
        ),
        sa.CheckConstraint(
            "urban_score BETWEEN 0 AND 100",
            name="ck_motorcycle_specs_urban",
        ),
        sa.CheckConstraint(
            "road_score BETWEEN 0 AND 100",
            name="ck_motorcycle_specs_road",
        ),
        sa.CheckConstraint(
            "passenger_comfort_score BETWEEN 0 AND 100",
            name="ck_motorcycle_specs_passenger",
        ),
        sa.CheckConstraint(
            "luggage_score BETWEEN 0 AND 100",
            name="ck_motorcycle_specs_luggage",
        ),
    )
    op.create_table(
        "motorcycle_objective_specifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "motorcycle_id",
            sa.Integer(),
            sa.ForeignKey("motorcycles.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("engine_displacement_cc", sa.Float(), nullable=False),
        sa.Column("motorcycle_category", sa.String(30), nullable=False),
        sa.Column("wet_weight_kg", sa.Float(), nullable=False),
        sa.Column("seat_height_mm", sa.Float(), nullable=False),
        sa.Column("tank_capacity_l", sa.Float(), nullable=False),
        sa.Column("has_abs", sa.Boolean(), nullable=False),
        sa.Column("power_cv", sa.Float(), nullable=True),
        sa.Column("torque_nm", sa.Float(), nullable=True),
        sa.Column("transmission_type", sa.String(30), nullable=True),
        sa.Column("gear_count", sa.Integer(), nullable=True),
        sa.Column("final_drive_type", sa.String(30), nullable=True),
        sa.Column("payload_capacity_kg", sa.Float(), nullable=True),
        sa.Column("oil_change_interval_km", sa.Integer(), nullable=True),
        sa.Column("abs_channels", sa.Integer(), nullable=True),
        sa.Column("has_cbs", sa.Boolean(), nullable=True),
        sa.Column("has_traction_control", sa.Boolean(), nullable=True),
        sa.CheckConstraint(
            "engine_displacement_cc > 0 AND engine_displacement_cc <= 3000",
            name="ck_motorcycle_objective_displacement",
        ),
        sa.CheckConstraint(
            "wet_weight_kg >= 20 AND wet_weight_kg <= 600",
            name="ck_motorcycle_objective_weight",
        ),
        sa.CheckConstraint(
            "seat_height_mm >= 400 AND seat_height_mm <= 1200",
            name="ck_motorcycle_objective_seat",
        ),
        sa.CheckConstraint(
            "tank_capacity_l >= 1 AND tank_capacity_l <= 50",
            name="ck_motorcycle_objective_tank",
        ),
        sa.CheckConstraint(
            "power_cv IS NULL OR power_cv > 0",
            name="ck_motorcycle_objective_power",
        ),
        sa.CheckConstraint(
            "torque_nm IS NULL OR torque_nm > 0",
            name="ck_motorcycle_objective_torque",
        ),
        sa.CheckConstraint(
            "gear_count IS NULL OR gear_count BETWEEN 1 AND 12",
            name="ck_motorcycle_objective_gears",
        ),
        sa.CheckConstraint(
            "payload_capacity_kg IS NULL OR payload_capacity_kg > 0",
            name="ck_motorcycle_objective_payload",
        ),
        sa.CheckConstraint(
            "oil_change_interval_km IS NULL OR oil_change_interval_km > 0",
            name="ck_motorcycle_objective_oil_interval",
        ),
        sa.CheckConstraint(
            "abs_channels IS NULL OR abs_channels BETWEEN 0 AND 2",
            name="ck_motorcycle_objective_abs_channels",
        ),
    )
    op.create_table(
        "part_prices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("part_id", sa.Integer(), sa.ForeignKey("parts.id"), nullable=False),
        sa.Column(
            "supplier_id",
            sa.Integer(),
            sa.ForeignKey("suppliers.id"),
            nullable=False,
        ),
        sa.Column(
            "vehicle_id",
            sa.Integer(),
            sa.ForeignKey("vehicles.id"),
            nullable=False,
        ),
        sa.Column("price", MONEY, nullable=False),
        sa.Column("brand", sa.String(80), nullable=False),
        sa.Column("condition", sa.String(40), nullable=False),
        sa.Column("url", sa.String(300), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
    )
    op.create_table(
        "user_vehicles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "vehicle_id",
            sa.Integer(),
            sa.ForeignKey("vehicles.id"),
            nullable=False,
        ),
        sa.Column("year_model", sa.Integer(), nullable=False),
        sa.Column("current_km", sa.Integer(), nullable=False),
        sa.Column("purchase_km", sa.Integer(), nullable=False),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("main_usage", sa.String(40), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "vehicle_part_compatibility",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "vehicle_id",
            sa.Integer(),
            sa.ForeignKey("vehicles.id"),
            nullable=False,
        ),
        sa.Column("part_id", sa.Integer(), sa.ForeignKey("parts.id"), nullable=False),
        sa.Column(
            "compatible_vehicle_id",
            sa.Integer(),
            sa.ForeignKey("vehicles.id"),
            nullable=False,
        ),
        sa.Column("compatibility_type", sa.String(60), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("confidence_level", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "fuel_consumption_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_vehicle_id",
            sa.Integer(),
            sa.ForeignKey("user_vehicles.id"),
            nullable=False,
        ),
        sa.Column(
            "vehicle_id",
            sa.Integer(),
            sa.ForeignKey("vehicles.id"),
            nullable=False,
        ),
        sa.Column("km_per_liter", sa.Float(), nullable=False),
        sa.Column("usage_type", sa.String(40), nullable=False),
        sa.Column("fuel_type", sa.String(40), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "vehicle_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_vehicle_id",
            sa.Integer(),
            sa.ForeignKey("user_vehicles.id"),
            nullable=False,
        ),
        sa.Column(
            "vehicle_id",
            sa.Integer(),
            sa.ForeignKey("vehicles.id"),
            nullable=False,
        ),
        sa.Column("problem_category", sa.String(60), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("occurrence_km", sa.Integer(), nullable=False),
        sa.Column("repair_cost", MONEY, nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("occurrence_date", sa.Date(), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "motorcycle_derived_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "motorcycle_id",
            sa.Integer(),
            sa.ForeignKey("motorcycles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric_name", sa.String(60), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=True),
        sa.Column("metric_text_value", sa.String(60), nullable=True),
        sa.Column("metric_status", sa.String(30), nullable=False),
        sa.Column("method_version", sa.String(80), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "source_group_id",
            sa.Integer(),
            sa.ForeignKey("motorcycle_data_sources.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "metric_value IS NULL OR metric_value BETWEEN 0 AND 100",
            name="ck_motorcycle_metrics_value",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 100",
            name="ck_motorcycle_metrics_confidence",
        ),
        sa.CheckConstraint(
            "(metric_value IS NOT NULL AND metric_text_value IS NULL) OR "
            "(metric_value IS NULL AND metric_text_value IS NOT NULL)",
            name="ck_motorcycle_metrics_single_value",
        ),
        sa.UniqueConstraint(
            "motorcycle_id",
            "metric_name",
            "method_version",
            name="uq_motorcycle_metric_method",
        ),
    )
    op.create_index(
        "ix_motorcycle_metrics_name",
        "motorcycle_derived_metrics",
        ["motorcycle_id", "metric_name"],
    )
    op.create_table(
        "motorcycle_economic_estimates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "motorcycle_id",
            sa.Integer(),
            sa.ForeignKey("motorcycles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("estimate_name", sa.String(80), nullable=False),
        sa.Column("estimate_value", MONEY, nullable=False),
        sa.Column("unit", sa.String(40), nullable=False),
        sa.Column("method_version", sa.String(80), nullable=False),
        sa.Column("reference_date", sa.Date(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "source_group_id",
            sa.Integer(),
            sa.ForeignKey("motorcycle_data_sources.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "estimate_value >= 0",
            name="ck_motorcycle_estimates_value_nonnegative",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 100",
            name="ck_motorcycle_estimates_confidence",
        ),
        sa.UniqueConstraint(
            "motorcycle_id",
            "estimate_name",
            "method_version",
            "reference_date",
            name="uq_motorcycle_estimate_version",
        ),
    )
    op.create_index(
        "ix_motorcycle_estimates_name",
        "motorcycle_economic_estimates",
        ["motorcycle_id", "estimate_name"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_motorcycle_estimates_name",
        table_name="motorcycle_economic_estimates",
    )
    op.drop_table("motorcycle_economic_estimates")
    op.drop_index(
        "ix_motorcycle_metrics_name",
        table_name="motorcycle_derived_metrics",
    )
    op.drop_table("motorcycle_derived_metrics")
    op.drop_table("vehicle_reports")
    op.drop_table("fuel_consumption_reports")
    op.drop_table("vehicle_part_compatibility")
    op.drop_table("user_vehicles")
    op.drop_table("part_prices")
    op.drop_table("motorcycle_objective_specifications")
    op.drop_table("motorcycle_specifications")
    op.drop_index(
        "uq_motorcycle_primary_source_per_group",
        table_name="motorcycle_data_sources",
    )
    op.drop_index(
        "ix_motorcycle_sources_group",
        table_name="motorcycle_data_sources",
    )
    op.drop_table("motorcycle_data_sources")
    op.drop_table("maintenances")
    op.drop_table("expenses")
    op.drop_table("suppliers")
    op.drop_table("parts")
    op.drop_index("ix_motorcycles_data_source", table_name="motorcycles")
    op.drop_index("ix_motorcycles_brand_model_year", table_name="motorcycles")
    op.drop_table("motorcycles")
    op.drop_table("vehicles")
    op.drop_table("sigra_schema_migrations")
    op.drop_table("users")
