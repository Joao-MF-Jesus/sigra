from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from data_platform.integrated_vehicle_cost.simulation_contracts import (
    MAX_HORIZON_MONTHS,
    MIN_HORIZON_MONTHS,
    FuelStrategy,
    VehicleCostSimulationScenario,
)


class VehicleCostSimulationHttpModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        from_attributes=True,
        allow_inf_nan=False,
    )


class VehicleCostSimulationRequest(VehicleCostSimulationHttpModel):
    monthly_distance_km: Decimal
    city_percentage: Decimal
    highway_percentage: Decimal
    state_code: str = Field(min_length=2, max_length=2)
    municipality: str | None = Field(default=None, min_length=1, max_length=200)
    reference_week_start: date
    fuel_strategy: FuelStrategy
    horizon_months: int = Field(
        ge=MIN_HORIZON_MONTHS,
        le=MAX_HORIZON_MONTHS,
    )
    manual_fuel_price_brl: Decimal | None = None
    city_consumption_km_l: Decimal | None = None
    highway_consumption_km_l: Decimal | None = None
    vehicle_sks: list[int] | None = Field(default=None, min_length=1, max_length=200)
    max_results: int | None = Field(default=None, ge=1, le=200)

    @field_validator(
        "monthly_distance_km",
        "city_percentage",
        "highway_percentage",
        "manual_fuel_price_brl",
        "city_consumption_km_l",
        "highway_consumption_km_l",
        mode="before",
    )
    @classmethod
    def reject_binary_floating_point(cls, value):
        if value is not None and (
            isinstance(value, bool) or isinstance(value, float)
        ):
            raise ValueError("use a decimal string or integer, not boolean or float")
        return value

    @field_validator("vehicle_sks", mode="before")
    @classmethod
    def validate_vehicle_sks(cls, value):
        if value is None:
            return None
        if not isinstance(value, list) or any(
            isinstance(item, bool) or not isinstance(item, int) for item in value
        ):
            raise ValueError("vehicle_sks must contain integers")
        return value

    @field_validator("max_results", mode="before")
    @classmethod
    def validate_max_results(cls, value):
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int)
        ):
            raise ValueError("max_results must be an integer")
        return value

    @field_validator("horizon_months", mode="before")
    @classmethod
    def validate_horizon_months(cls, value):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("horizon_months must be an integer")
        return value

    @field_validator("state_code")
    @classmethod
    def normalize_state_code(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("municipality")
    @classmethod
    def normalize_municipality(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def validate_contract(self):
        self.to_contract()
        return self

    def to_contract(self) -> VehicleCostSimulationScenario:
        return VehicleCostSimulationScenario(
            monthly_distance_km=self.monthly_distance_km,
            city_percentage=self.city_percentage,
            highway_percentage=self.highway_percentage,
            state_code=self.state_code,
            municipality=self.municipality,
            reference_week_start=self.reference_week_start,
            fuel_strategy=self.fuel_strategy,
            horizon_months=self.horizon_months,
            manual_fuel_price_brl=self.manual_fuel_price_brl,
            city_consumption_km_l=self.city_consumption_km_l,
            highway_consumption_km_l=self.highway_consumption_km_l,
            vehicle_sks=(tuple(self.vehicle_sks) if self.vehicle_sks is not None else None),
            max_results=self.max_results,
        )


class SimulationSourceVersionsResponse(VehicleCostSimulationHttpModel):
    integrated_dataset_version: str
    fipe_dataset_version: str
    pbev_dataset_version: str
    anp_dataset_version: str


class VehicleCostSimulationScenarioResponse(VehicleCostSimulationHttpModel):
    monthly_distance_km: Decimal
    city_percentage: Decimal
    highway_percentage: Decimal
    state_code: str
    municipality: str | None
    reference_week_start: date
    fuel_strategy: FuelStrategy
    horizon_months: int
    manual_fuel_price_brl: Decimal | None
    city_consumption_km_l: Decimal | None
    highway_consumption_km_l: Decimal | None
    vehicle_sks: tuple[int, ...] | None
    max_results: int | None


class VehicleCostSimulationResultResponse(VehicleCostSimulationHttpModel):
    rank: int = Field(ge=1)
    vehicle_sk: int = Field(gt=0)
    brand_name: str
    model_name: str
    version_name: str | None
    model_year: int | None
    fuel_code: Literal[
        "gasoline_c_common",
        "gasoline_c_additized",
        "ethanol_hydrated",
    ]
    city_consumption_km_l: Decimal
    highway_consumption_km_l: Decimal
    weighted_consumption_km_l: Decimal
    estimated_monthly_liters: Decimal
    estimated_annual_liters: Decimal
    monthly_fuel_cost_brl: Decimal
    annual_fuel_cost_brl: Decimal
    fuel_cost_per_km_brl: Decimal
    fuel_price_per_liter_brl: Decimal
    fuel_price_origin: Literal["anp_gold", "user_input"]
    city_consumption_origin: Literal["pbev_gold", "user_input"]
    highway_consumption_origin: Literal["pbev_gold", "user_input"]
    canonical_comparison_origin: Literal["canonical_policy"]
    horizon_months: int
    projected_horizon_cost_brl: Decimal
    canonical_scenario_code: Literal["mixed_1000_v1"]
    canonical_monthly_distance_km: Decimal
    canonical_monthly_fuel_cost_brl: Decimal
    canonical_annual_fuel_cost_brl: Decimal
    monthly_cost_difference_brl: Decimal
    monthly_cost_difference_percentage: Decimal
    state_code: str
    municipality: str | None
    anp_week_start: date | None
    anp_week_end: date | None
    sources: SimulationSourceVersionsResponse
    simulation_policy_version: str
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]


class VehicleCostSimulationExclusionResponse(VehicleCostSimulationHttpModel):
    vehicle_sk: int = Field(gt=0)
    reason_code: str
    detail: str


class VehicleCostSimulationResponse(VehicleCostSimulationHttpModel):
    scenario: VehicleCostSimulationScenarioResponse
    results: tuple[VehicleCostSimulationResultResponse, ...]
    exclusions: tuple[VehicleCostSimulationExclusionResponse, ...]
    evaluated_vehicle_count: int = Field(ge=0)
    eligible_vehicle_count: int = Field(ge=0)
    excluded_vehicle_count: int = Field(ge=0)
    returned_vehicle_count: int = Field(ge=0)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    simulation_policy_version: str
    is_simulation: Literal[True]
    simulation_only: Literal[True]
    active_gold_unchanged: Literal[True]
    response_timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
