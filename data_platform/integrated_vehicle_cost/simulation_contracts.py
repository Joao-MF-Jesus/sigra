"""Contratos puros da simulacao configuravel de custo veicular."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import StrEnum
import hashlib
import json
import re
from typing import Iterable

from data_platform.contracts.integrated_vehicle_cost import (
    MIXED_1000_V1,
    FuelScenarioCode,
)


SIMULATION_POLICY_VERSION = "user-configurable-vehicle-cost-v1"
DISTANCE_QUANTUM = Decimal("0.01")
PERCENT_QUANTUM = Decimal("0.01")
CONSUMPTION_QUANTUM = Decimal("0.0001")
LITERS_QUANTUM = Decimal("0.0001")
COST_PER_KM_QUANTUM = Decimal("0.00000001")
MONEY_QUANTUM = Decimal("0.0001")
DIFFERENCE_PERCENT_QUANTUM = Decimal("0.01")
MAX_MONTHLY_DISTANCE_KM = Decimal("100000.00")
MAX_FUEL_PRICE_BRL = Decimal("1000.0000")
MAX_CONSUMPTION_KM_L = Decimal("1000.0000")
MIN_HORIZON_MONTHS = 1
MAX_HORIZON_MONTHS = 120
_HUNDRED = Decimal("100.00")
_STATE_CODE = re.compile(r"^[A-Z]{2}$")


class FuelStrategy(StrEnum):
    GASOLINE_C_COMMON = "gasoline_c_common"
    GASOLINE_C_ADDITIZED = "gasoline_c_additized"
    ETHANOL_HYDRATED = "ethanol_hydrated"
    LOWEST_PROJECTED_COST = "lowest_projected_cost"


class SimulationEvidenceOrigin(StrEnum):
    PBEV_GOLD = "pbev_gold"
    ANP_GOLD = "anp_gold"
    USER_INPUT = "user_input"
    CANONICAL_POLICY = "canonical_policy"


def _finite_decimal(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")
    return value


def _exact_quantum(value: Decimal, quantum: Decimal, field_name: str) -> Decimal:
    value = _finite_decimal(value, field_name)
    try:
        normalized = value.quantize(quantum, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} exceeds the supported range") from exc
    if normalized != value:
        raise ValueError(f"{field_name} exceeds the supported precision")
    return normalized


def _positive_decimal(value: Decimal, field_name: str) -> None:
    if _finite_decimal(value, field_name) <= 0:
        raise ValueError(f"{field_name} must be greater than zero")


def _bounded_positive_decimal(
    value: Decimal,
    quantum: Decimal,
    maximum: Decimal,
    field_name: str,
) -> Decimal:
    normalized = _exact_quantum(value, quantum, field_name)
    if normalized <= 0:
        raise ValueError(f"{field_name} must be greater than zero")
    if normalized > maximum:
        raise ValueError(f"{field_name} exceeds the defensive maximum")
    return normalized


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


@dataclass(frozen=True)
class SimulationSourceVersions:
    integrated_dataset_version: str
    fipe_dataset_version: str
    pbev_dataset_version: str
    anp_dataset_version: str

    def __post_init__(self) -> None:
        for field_name in (
            "integrated_dataset_version",
            "fipe_dataset_version",
            "pbev_dataset_version",
            "anp_dataset_version",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} is required")


@dataclass(frozen=True)
class VehicleCostSimulationScenario:
    monthly_distance_km: Decimal
    city_percentage: Decimal
    highway_percentage: Decimal
    state_code: str
    municipality: str | None
    reference_week_start: date
    fuel_strategy: FuelStrategy
    horizon_months: int
    manual_fuel_price_brl: Decimal | None = None
    city_consumption_km_l: Decimal | None = None
    highway_consumption_km_l: Decimal | None = None
    vehicle_sks: tuple[int, ...] | None = None
    max_results: int | None = None

    def __post_init__(self) -> None:
        monthly = _bounded_positive_decimal(
            self.monthly_distance_km,
            DISTANCE_QUANTUM,
            MAX_MONTHLY_DISTANCE_KM,
            "monthly_distance_km",
        )
        city = _exact_quantum(
            self.city_percentage,
            PERCENT_QUANTUM,
            "city_percentage",
        )
        highway = _exact_quantum(
            self.highway_percentage,
            PERCENT_QUANTUM,
            "highway_percentage",
        )
        if not Decimal("0") <= city <= _HUNDRED:
            raise ValueError("city_percentage must be between 0 and 100")
        if not Decimal("0") <= highway <= _HUNDRED:
            raise ValueError("highway_percentage must be between 0 and 100")
        if city + highway != _HUNDRED:
            raise ValueError("city and highway percentages must sum exactly to 100")
        state = self.state_code.strip().upper() if isinstance(self.state_code, str) else ""
        if not _STATE_CODE.fullmatch(state):
            raise ValueError("state_code must contain two letters")
        municipality = self.municipality
        if municipality is not None:
            municipality = municipality.strip()
            if not municipality or len(municipality) > 200:
                raise ValueError("municipality must contain between 1 and 200 characters")
        if isinstance(self.reference_week_start, bool) or not isinstance(
            self.reference_week_start, date
        ):
            raise ValueError("reference_week_start must be a date")
        if not isinstance(self.fuel_strategy, FuelStrategy):
            raise ValueError("fuel_strategy is invalid")
        if (
            isinstance(self.horizon_months, bool)
            or not isinstance(self.horizon_months, int)
            or not MIN_HORIZON_MONTHS
            <= self.horizon_months
            <= MAX_HORIZON_MONTHS
        ):
            raise ValueError(
                f"horizon_months must be between {MIN_HORIZON_MONTHS} "
                f"and {MAX_HORIZON_MONTHS}"
            )
        manual_price = self.manual_fuel_price_brl
        if manual_price is not None:
            manual_price = _bounded_positive_decimal(
                manual_price,
                MONEY_QUANTUM,
                MAX_FUEL_PRICE_BRL,
                "manual_fuel_price_brl",
            )
            if self.fuel_strategy is FuelStrategy.LOWEST_PROJECTED_COST:
                raise ValueError(
                    "manual fuel price requires one explicitly selected fuel"
                )
        city_consumption = self.city_consumption_km_l
        if city_consumption is not None:
            city_consumption = _bounded_positive_decimal(
                city_consumption,
                CONSUMPTION_QUANTUM,
                MAX_CONSUMPTION_KM_L,
                "city_consumption_km_l",
            )
        highway_consumption = self.highway_consumption_km_l
        if highway_consumption is not None:
            highway_consumption = _bounded_positive_decimal(
                highway_consumption,
                CONSUMPTION_QUANTUM,
                MAX_CONSUMPTION_KM_L,
                "highway_consumption_km_l",
            )
        vehicle_sks = self.vehicle_sks
        if vehicle_sks is not None:
            if not isinstance(vehicle_sks, tuple) or not vehicle_sks:
                raise ValueError("vehicle_sks must be a non-empty tuple when provided")
            if any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
                for value in vehicle_sks
            ):
                raise ValueError("vehicle_sks must contain positive integers")
            vehicle_sks = tuple(sorted(set(vehicle_sks)))
        if self.max_results is not None and (
            isinstance(self.max_results, bool)
            or not isinstance(self.max_results, int)
            or self.max_results <= 0
        ):
            raise ValueError("max_results must be a positive integer")
        object.__setattr__(self, "monthly_distance_km", monthly)
        object.__setattr__(self, "city_percentage", city)
        object.__setattr__(self, "highway_percentage", highway)
        object.__setattr__(self, "state_code", state)
        object.__setattr__(self, "municipality", municipality)
        object.__setattr__(self, "manual_fuel_price_brl", manual_price)
        object.__setattr__(self, "city_consumption_km_l", city_consumption)
        object.__setattr__(
            self,
            "highway_consumption_km_l",
            highway_consumption,
        )
        object.__setattr__(self, "vehicle_sks", vehicle_sks)

    @property
    def uses_manual_price(self) -> bool:
        return self.manual_fuel_price_brl is not None

    @property
    def city_share(self) -> Decimal:
        return self.city_percentage / _HUNDRED

    @property
    def highway_share(self) -> Decimal:
        return self.highway_percentage / _HUNDRED

    @property
    def geography_level(self) -> str:
        return "municipality" if self.municipality is not None else "state"

    @property
    def geography_key(self) -> str:
        return self.municipality or self.state_code

    def canonical_payload(self) -> dict[str, object]:
        return {
            "monthly_distance_km": _decimal_text(self.monthly_distance_km),
            "city_percentage": _decimal_text(self.city_percentage),
            "highway_percentage": _decimal_text(self.highway_percentage),
            "state_code": self.state_code,
            "municipality": self.municipality,
            "reference_week_start": self.reference_week_start.isoformat(),
            "fuel_strategy": self.fuel_strategy.value,
            "horizon_months": self.horizon_months,
            "manual_fuel_price_brl": (
                _decimal_text(self.manual_fuel_price_brl)
                if self.manual_fuel_price_brl is not None
                else None
            ),
            "city_consumption_km_l": (
                _decimal_text(self.city_consumption_km_l)
                if self.city_consumption_km_l is not None
                else None
            ),
            "highway_consumption_km_l": (
                _decimal_text(self.highway_consumption_km_l)
                if self.highway_consumption_km_l is not None
                else None
            ),
            "vehicle_sks": list(self.vehicle_sks) if self.vehicle_sks else None,
            "max_results": self.max_results,
        }


@dataclass(frozen=True)
class VehicleCostEvidence:
    sources: SimulationSourceVersions
    vehicle_sk: int
    brand_name: str
    model_name: str
    version_name: str | None
    model_year: int | None
    fuel_code: FuelScenarioCode
    requested_geography_level: str
    requested_geography_key: str
    anp_week_start: date
    anp_week_end: date
    city_consumption_km_l: Decimal
    highway_consumption_km_l: Decimal
    fuel_price_per_liter_brl: Decimal
    analytical_scenario_code: str
    analytical_monthly_distance_km: Decimal
    analytical_annual_distance_km: Decimal
    analytical_projected_monthly_cost_brl: Decimal
    analytical_projected_annual_cost_brl: Decimal

    def __post_init__(self) -> None:
        if isinstance(self.vehicle_sk, bool) or self.vehicle_sk <= 0:
            raise ValueError("vehicle_sk must be positive")
        if not self.brand_name or not self.model_name:
            raise ValueError("vehicle identification is required")
        if self.requested_geography_level not in {"municipality", "state"}:
            raise ValueError("requested geography level is invalid")
        if not self.requested_geography_key:
            raise ValueError("requested geography key is required")
        if self.anp_week_end != self.anp_week_start + timedelta(days=6):
            raise ValueError("ANP reference week must contain seven days")
        if not isinstance(self.fuel_code, FuelScenarioCode):
            raise ValueError("fuel_code is invalid")
        for field_name in (
            "city_consumption_km_l",
            "highway_consumption_km_l",
            "fuel_price_per_liter_brl",
        ):
            _positive_decimal(getattr(self, field_name), field_name)
        if self.analytical_scenario_code != MIXED_1000_V1:
            raise ValueError(f"analytical scenario must be {MIXED_1000_V1}")
        for field_name in (
            "analytical_monthly_distance_km",
            "analytical_annual_distance_km",
            "analytical_projected_monthly_cost_brl",
            "analytical_projected_annual_cost_brl",
        ):
            _positive_decimal(getattr(self, field_name), field_name)


@dataclass(frozen=True)
class PublishedVehicleExclusion:
    vehicle_sk: int
    reason_code: str

    def __post_init__(self) -> None:
        if isinstance(self.vehicle_sk, bool) or self.vehicle_sk <= 0:
            raise ValueError("vehicle_sk must be positive")
        if not self.reason_code:
            raise ValueError("reason_code is required")


@dataclass(frozen=True)
class VehicleCostSimulationExclusion:
    vehicle_sk: int
    reason_code: str
    detail: str


@dataclass(frozen=True)
class VehicleCostSimulationResult:
    rank: int
    vehicle_sk: int
    brand_name: str
    model_name: str
    version_name: str | None
    model_year: int | None
    fuel_code: FuelScenarioCode
    city_consumption_km_l: Decimal
    highway_consumption_km_l: Decimal
    weighted_consumption_km_l: Decimal
    estimated_monthly_liters: Decimal
    estimated_annual_liters: Decimal
    monthly_fuel_cost_brl: Decimal
    annual_fuel_cost_brl: Decimal
    fuel_cost_per_km_brl: Decimal
    fuel_price_per_liter_brl: Decimal
    fuel_price_origin: SimulationEvidenceOrigin
    city_consumption_origin: SimulationEvidenceOrigin
    highway_consumption_origin: SimulationEvidenceOrigin
    canonical_comparison_origin: SimulationEvidenceOrigin
    horizon_months: int
    projected_horizon_cost_brl: Decimal
    canonical_scenario_code: str
    canonical_monthly_distance_km: Decimal
    canonical_monthly_fuel_cost_brl: Decimal
    canonical_annual_fuel_cost_brl: Decimal
    monthly_cost_difference_brl: Decimal
    monthly_cost_difference_percentage: Decimal
    state_code: str
    municipality: str | None
    anp_week_start: date | None
    anp_week_end: date | None
    sources: SimulationSourceVersions
    simulation_policy_version: str
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class VehicleCostSimulationBatch:
    scenario: VehicleCostSimulationScenario
    results: tuple[VehicleCostSimulationResult, ...]
    exclusions: tuple[VehicleCostSimulationExclusion, ...]
    evaluated_vehicle_count: int
    eligible_vehicle_count: int
    excluded_vehicle_count: int
    returned_vehicle_count: int
    fingerprint: str
    simulation_policy_version: str = SIMULATION_POLICY_VERSION
    is_simulation: bool = True
    simulation_only: bool = True
    active_gold_unchanged: bool = True


def canonical_fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def result_fingerprint_payload(
    scenario: VehicleCostSimulationScenario,
    results: Iterable[VehicleCostSimulationResult],
    exclusions: Iterable[VehicleCostSimulationExclusion],
    *,
    evaluated_vehicle_count: int,
    eligible_vehicle_count: int,
) -> dict[str, object]:
    return {
        "policy_version": SIMULATION_POLICY_VERSION,
        "scenario": scenario.canonical_payload(),
        "evaluated_vehicle_count": evaluated_vehicle_count,
        "eligible_vehicle_count": eligible_vehicle_count,
        "results": [
            {
                "rank": item.rank,
                "vehicle_sk": item.vehicle_sk,
                "brand_name": item.brand_name,
                "model_name": item.model_name,
                "version_name": item.version_name,
                "model_year": item.model_year,
                "fuel_code": item.fuel_code.value,
                "city_consumption_km_l": _decimal_text(
                    item.city_consumption_km_l
                ),
                "highway_consumption_km_l": _decimal_text(
                    item.highway_consumption_km_l
                ),
                "weighted_consumption_km_l": _decimal_text(
                    item.weighted_consumption_km_l
                ),
                "estimated_monthly_liters": _decimal_text(
                    item.estimated_monthly_liters
                ),
                "estimated_annual_liters": _decimal_text(
                    item.estimated_annual_liters
                ),
                "monthly_fuel_cost_brl": _decimal_text(item.monthly_fuel_cost_brl),
                "annual_fuel_cost_brl": _decimal_text(item.annual_fuel_cost_brl),
                "fuel_cost_per_km_brl": _decimal_text(item.fuel_cost_per_km_brl),
                "fuel_price_per_liter_brl": _decimal_text(
                    item.fuel_price_per_liter_brl
                ),
                "fuel_price_origin": item.fuel_price_origin.value,
                "city_consumption_origin": item.city_consumption_origin.value,
                "highway_consumption_origin": item.highway_consumption_origin.value,
                "canonical_comparison_origin": (
                    item.canonical_comparison_origin.value
                ),
                "horizon_months": item.horizon_months,
                "projected_horizon_cost_brl": _decimal_text(
                    item.projected_horizon_cost_brl
                ),
                "canonical_scenario_code": item.canonical_scenario_code,
                "canonical_monthly_distance_km": _decimal_text(
                    item.canonical_monthly_distance_km
                ),
                "canonical_monthly_fuel_cost_brl": _decimal_text(
                    item.canonical_monthly_fuel_cost_brl
                ),
                "canonical_annual_fuel_cost_brl": _decimal_text(
                    item.canonical_annual_fuel_cost_brl
                ),
                "monthly_cost_difference_brl": _decimal_text(
                    item.monthly_cost_difference_brl
                ),
                "monthly_cost_difference_percentage": _decimal_text(
                    item.monthly_cost_difference_percentage
                ),
                "state_code": item.state_code,
                "municipality": item.municipality,
                "anp_week_start": (
                    item.anp_week_start.isoformat()
                    if item.anp_week_start is not None
                    else None
                ),
                "anp_week_end": (
                    item.anp_week_end.isoformat()
                    if item.anp_week_end is not None
                    else None
                ),
                "sources": {
                    "integrated": item.sources.integrated_dataset_version,
                    "fipe": item.sources.fipe_dataset_version,
                    "pbev": item.sources.pbev_dataset_version,
                    "anp": item.sources.anp_dataset_version,
                },
                "warnings": list(item.warnings),
                "limitations": list(item.limitations),
            }
            for item in results
        ],
        "exclusions": [
            {
                "vehicle_sk": item.vehicle_sk,
                "reason_code": item.reason_code,
                "detail": item.detail,
            }
            for item in exclusions
        ],
    }
