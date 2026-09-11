"""Contratos HTTP do perfil multifator, sem persistencia."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.multifactor_recommendation import MULTIFACTOR_COMPONENTS
from data_platform.integrated_vehicle_cost.simulation_contracts import (
    MAX_HORIZON_MONTHS,
    MIN_HORIZON_MONTHS,
    FuelStrategy,
    VehicleCostSimulationScenario,
)


DEFAULT_MULTIFACTOR_WEIGHTS = {
    "total_cost": Decimal("25"),
    "usage_fit": Decimal("20"),
    "comfort": Decimal("10"),
    "safety": Decimal("15"),
    "performance": Decimal("10"),
    "efficiency": Decimal("10"),
    "legacy_quality": Decimal("10"),
}


def _reject_binary_or_boolean(value):
    if isinstance(value, (bool, float)):
        raise ValueError("use a finite decimal string or integer")
    return value


class MultifactorHttpModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class MultifactorWeights(MultifactorHttpModel):
    total_cost: Decimal = DEFAULT_MULTIFACTOR_WEIGHTS["total_cost"]
    usage_fit: Decimal = DEFAULT_MULTIFACTOR_WEIGHTS["usage_fit"]
    comfort: Decimal = DEFAULT_MULTIFACTOR_WEIGHTS["comfort"]
    safety: Decimal = DEFAULT_MULTIFACTOR_WEIGHTS["safety"]
    performance: Decimal = DEFAULT_MULTIFACTOR_WEIGHTS["performance"]
    efficiency: Decimal = DEFAULT_MULTIFACTOR_WEIGHTS["efficiency"]
    legacy_quality: Decimal = DEFAULT_MULTIFACTOR_WEIGHTS["legacy_quality"]

    @field_validator(*MULTIFACTOR_COMPONENTS, mode="before")
    @classmethod
    def validate_decimal_input(cls, value):
        return _reject_binary_or_boolean(value)

    @field_validator(*MULTIFACTOR_COMPONENTS)
    @classmethod
    def validate_weight_range(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < 0 or value > Decimal("100"):
            raise ValueError("weight must be between 0 and 100")
        return value

    @model_validator(mode="after")
    def validate_positive_total(self):
        if sum((getattr(self, code) for code in MULTIFACTOR_COMPONENTS), Decimal("0")) <= 0:
            raise ValueError("at least one weight must be positive")
        return self

    def as_mapping(self) -> dict[str, Decimal]:
        return {code: getattr(self, code) for code in MULTIFACTOR_COMPONENTS}


class MultifactorScenario(MultifactorHttpModel):
    monthly_distance_km: Decimal
    city_percentage: Decimal
    highway_percentage: Decimal
    state_code: str = Field(min_length=2, max_length=2)
    municipality: str | None = Field(default=None, min_length=1, max_length=200)
    reference_week_start: date
    fuel_strategy: FuelStrategy
    horizon_months: int = Field(ge=MIN_HORIZON_MONTHS, le=MAX_HORIZON_MONTHS)
    manual_fuel_price_brl: Decimal | None = None
    city_consumption_km_l: Decimal | None = None
    highway_consumption_km_l: Decimal | None = None

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
    def validate_decimal_input(cls, value):
        if value is None:
            return value
        return _reject_binary_or_boolean(value)

    @field_validator("horizon_months", mode="before")
    @classmethod
    def validate_horizon_type(cls, value):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("horizon_months must be an integer")
        return value

    @field_validator("state_code")
    @classmethod
    def normalize_state(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("municipality")
    @classmethod
    def normalize_municipality(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def validate_scenario(self):
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
            vehicle_sks=None,
            max_results=None,
        )


class MultifactorRecommendationProfile(MultifactorHttpModel):
    enabled: Literal[True]
    scenario: MultifactorScenario
    weights: MultifactorWeights = Field(default_factory=MultifactorWeights)
