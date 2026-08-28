from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class IntegratedGoldModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class IntegratedCostItem(IntegratedGoldModel):
    dataset_version: str
    vehicle_sk: int
    brand_name: str
    model_name: str
    version_name: str | None
    model_year: int | None
    fuel_scenario_code: str
    requested_geography_level: Literal["municipality", "state"]
    requested_geography_key: str
    anp_week_start: date
    anp_week_end: date
    vehicle_price_brl: Decimal
    city_consumption_km_l: Decimal
    highway_consumption_km_l: Decimal
    fuel_price_per_liter_brl: Decimal
    city_cost_per_km_brl: Decimal
    highway_cost_per_km_brl: Decimal
    mixed_cost_per_km_brl: Decimal
    city_distance_share: Decimal
    highway_distance_share: Decimal
    analytical_scenario_code: Literal["mixed_1000_v1"]
    analytical_monthly_distance_km: Decimal
    analytical_annual_distance_km: Decimal
    analytical_projected_monthly_cost_brl: Decimal
    analytical_projected_annual_cost_brl: Decimal


class IntegratedCostPage(IntegratedGoldModel):
    items: list[IntegratedCostItem]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    dataset_version: str
    analytical_baseline_only: Literal[True] = True


class IntegratedVehicleDetail(IntegratedGoldModel):
    dataset_version: str
    vehicle_sk: int
    brand_name: str
    model_name: str
    version_name: str | None
    model_year: int | None
    scenarios: list[IntegratedCostItem]
    analytical_baseline_only: Literal[True] = True


class IntegratedDatasetMetadata(IntegratedGoldModel):
    dataset_version: str
    fipe_source_dataset_version: str
    pbev_source_dataset_version: str
    anp_source_dataset_version: str
    analytic_cutoff_at: datetime
    calculation_policy_version: str
    geography_policy_version: str
    scenario_policy_version: str
    quality_policy_version: str
    published_vehicle_count: int = Field(ge=0)
    published_scenario_count: int = Field(ge=0)
    catalog_coverage_pct: Decimal
    pbev_coverage_pct: Decimal
    first_published_at: datetime
    last_activated_at: datetime
    analytical_baseline_scenario: Literal["mixed_1000_v1"] = "mixed_1000_v1"
    personalization_requires_explicit_inputs: Literal[True] = True
    read_only: Literal[True] = True
