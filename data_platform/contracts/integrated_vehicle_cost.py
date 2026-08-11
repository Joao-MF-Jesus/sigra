"""Contratos puros da Gold analitica integrada FIPE + PBEV + ANP."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum
from typing import FrozenSet, Hashable, Iterable


INTEGRATED_QUALITY_POLICY_VERSION = "integrated-vehicle-cost-quality-v1"
MIXED_1000_V1 = "mixed_1000_v1"
MONEY_QUANTUM = Decimal("0.0001")
RATE_QUANTUM = Decimal("0.00000001")
PERCENT_QUANTUM = Decimal("0.01")


class IntegratedDatasetStatus(StrEnum):
    BUILDING = "building"
    SHADOW_PUBLISHED = "shadow_published"
    RETIRED = "retired"


class IntegratedActivationType(StrEnum):
    PUBLISH = "publish"
    REPLACE = "replace"
    ROLLBACK = "rollback"


class CoverageRegressionStatus(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    PASSED = "passed"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"


class QualityRuleKind(StrEnum):
    HARD_GATE = "hard_gate"
    STATISTICAL_CONTROL = "statistical_control"


class QualitySeverity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class QualityExpectedStatus(StrEnum):
    PASSED = "passed"
    NOT_CALIBRATED = "not_calibrated"


class FuelScenarioCode(StrEnum):
    GASOLINE_C_COMMON = "gasoline_c_common"
    GASOLINE_C_ADDITIZED = "gasoline_c_additized"
    ETHANOL_HYDRATED = "ethanol_hydrated"


class ExclusionScope(StrEnum):
    VEHICLE = "vehicle"
    SCENARIO = "scenario"


def _require_positive(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or value <= 0:
        raise ValueError(f"{field_name} must be a positive Decimal")


def _require_version(value: str, field_name: str, maximum: int) -> None:
    if not value or len(value) > maximum:
        raise ValueError(f"{field_name} must contain between 1 and {maximum} characters")


@dataclass(frozen=True)
class DistanceScenario:
    scenario_code: str = MIXED_1000_V1
    monthly_distance_km: Decimal = Decimal("1000.00")
    annual_distance_km: Decimal = Decimal("12000.00")
    city_distance_share: Decimal = Decimal("0.5000")
    highway_distance_share: Decimal = Decimal("0.5000")

    def __post_init__(self) -> None:
        if self.scenario_code != MIXED_1000_V1:
            raise ValueError(f"scenario_code must be {MIXED_1000_V1}")
        if self.monthly_distance_km != Decimal("1000.00"):
            raise ValueError("monthly_distance_km must be 1000.00")
        if self.annual_distance_km != self.monthly_distance_km * Decimal("12"):
            raise ValueError("annual_distance_km must be twelve monthly distances")
        if not all(
            isinstance(value, Decimal)
            for value in (self.monthly_distance_km, self.annual_distance_km,
                          self.city_distance_share, self.highway_distance_share)
        ):
            raise ValueError("scenario arithmetic must use Decimal")
        if self.city_distance_share < 0 or self.highway_distance_share < 0:
            raise ValueError("distance shares cannot be negative")
        if self.city_distance_share + self.highway_distance_share != Decimal("1.0000"):
            raise ValueError("distance shares must sum to 1.0000")


DEFAULT_DISTANCE_SCENARIO = DistanceScenario()


@dataclass(frozen=True)
class IntegratedDatasetIdentity:
    dataset_version: str
    fipe_source_dataset_version: str
    pbev_source_dataset_version: str
    anp_source_dataset_version: str
    quality_policy_version: str = INTEGRATED_QUALITY_POLICY_VERSION

    def __post_init__(self) -> None:
        _require_version(self.dataset_version, "dataset_version", 96)
        for field_name in (
            "fipe_source_dataset_version",
            "pbev_source_dataset_version",
            "anp_source_dataset_version",
        ):
            _require_version(getattr(self, field_name), field_name, 80)
        _require_version(self.quality_policy_version, "quality_policy_version", 80)


@dataclass(frozen=True)
class IntegratedActivation:
    dataset_version: str
    activation_type: IntegratedActivationType
    previous_dataset_version: str | None

    def __post_init__(self) -> None:
        _require_version(self.dataset_version, "dataset_version", 96)
        if self.activation_type is IntegratedActivationType.PUBLISH:
            if self.previous_dataset_version is not None:
                raise ValueError("publish requires no previous dataset")
            return
        if self.previous_dataset_version is None:
            raise ValueError("replace and rollback require a previous dataset")
        _require_version(self.previous_dataset_version, "previous_dataset_version", 96)
        if self.previous_dataset_version == self.dataset_version:
            raise ValueError("previous dataset must differ from the activation target")


@dataclass(frozen=True)
class IntegratedSnapshotGrain:
    dataset_version: str
    vehicle_sk: int
    fuel_scenario_code: FuelScenarioCode
    requested_geography_level: str
    requested_geography_key: str
    anp_week_start: date

    def __post_init__(self) -> None:
        _require_version(self.dataset_version, "dataset_version", 96)
        if self.vehicle_sk <= 0:
            raise ValueError("vehicle_sk must be positive")
        if self.requested_geography_level not in {"municipality", "state"}:
            raise ValueError("requested geography must be municipality or state")
        if not self.requested_geography_key:
            raise ValueError("requested_geography_key is required")


@dataclass(frozen=True)
class IntegratedProjectionGrain:
    snapshot: IntegratedSnapshotGrain
    scenario_code: str = MIXED_1000_V1

    def __post_init__(self) -> None:
        if self.scenario_code != MIXED_1000_V1:
            raise ValueError(f"scenario_code must be {MIXED_1000_V1}")


@dataclass(frozen=True)
class IntegratedExclusion:
    dataset_version: str
    vehicle_sk: int
    scope: ExclusionScope
    scenario_code: str | None = None
    fuel_scenario_code: FuelScenarioCode | None = None
    requested_geography_level: str | None = None
    requested_geography_key: str | None = None
    anp_week_start: date | None = None

    def __post_init__(self) -> None:
        _require_version(self.dataset_version, "dataset_version", 96)
        if self.vehicle_sk <= 0:
            raise ValueError("vehicle_sk must be positive")
        scenario_values = (
            self.fuel_scenario_code,
            self.requested_geography_level,
            self.requested_geography_key,
            self.anp_week_start,
        )
        if self.scope is ExclusionScope.VEHICLE:
            if self.scenario_code is not None or any(value is not None for value in scenario_values):
                raise ValueError("vehicle exclusions cannot carry a scenario grain")
        else:
            if self.scenario_code != MIXED_1000_V1 or any(
                value is None for value in scenario_values
            ):
                raise ValueError("scenario exclusions require the complete mixed_1000_v1 grain")


@dataclass(frozen=True)
class CostProjection:
    city_cost_per_km_brl: Decimal
    highway_cost_per_km_brl: Decimal
    mixed_cost_per_km_brl: Decimal
    projected_monthly_cost_brl: Decimal
    projected_annual_cost_brl: Decimal


def calculate_projection(
    *,
    fuel_price_per_liter_brl: Decimal,
    city_consumption_km_l: Decimal,
    highway_consumption_km_l: Decimal,
    scenario: DistanceScenario = DEFAULT_DISTANCE_SCENARIO,
) -> CostProjection:
    """Calcula custos sem converter valores monetarios para float."""
    for field_name, value in (
        ("fuel_price_per_liter_brl", fuel_price_per_liter_brl),
        ("city_consumption_km_l", city_consumption_km_l),
        ("highway_consumption_km_l", highway_consumption_km_l),
    ):
        _require_positive(value, field_name)
    city = (fuel_price_per_liter_brl / city_consumption_km_l).quantize(
        RATE_QUANTUM, rounding=ROUND_HALF_UP
    )
    highway = (fuel_price_per_liter_brl / highway_consumption_km_l).quantize(
        RATE_QUANTUM, rounding=ROUND_HALF_UP
    )
    mixed = (
        city * scenario.city_distance_share
        + highway * scenario.highway_distance_share
    ).quantize(RATE_QUANTUM, rounding=ROUND_HALF_UP)
    monthly = (mixed * scenario.monthly_distance_km).quantize(
        MONEY_QUANTUM, rounding=ROUND_HALF_UP
    )
    annual = (monthly * Decimal("12")).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    return CostProjection(city, highway, mixed, monthly, annual)


def coverage_pct(published_count: int, universe_count: int) -> Decimal:
    if published_count < 0 or universe_count < 0 or published_count > universe_count:
        raise ValueError("coverage counts are inconsistent")
    if universe_count == 0:
        return Decimal("0.00")
    return (Decimal(published_count) * Decimal("100") / Decimal(universe_count)).quantize(
        PERCENT_QUANTUM, rounding=ROUND_HALF_UP
    )


def coverage_regression_status(
    *,
    catalog_coverage_pct: Decimal,
    pbev_coverage_pct: Decimal,
    baseline_catalog_coverage_pct: Decimal | None,
    baseline_pbev_coverage_pct: Decimal | None,
) -> CoverageRegressionStatus:
    values = (catalog_coverage_pct, pbev_coverage_pct)
    if not all(isinstance(value, Decimal) for value in values):
        raise ValueError("coverage arithmetic must use Decimal")
    if baseline_catalog_coverage_pct is None and baseline_pbev_coverage_pct is None:
        return CoverageRegressionStatus.NOT_APPLICABLE
    if baseline_catalog_coverage_pct is None or baseline_pbev_coverage_pct is None:
        raise ValueError("coverage baseline must provide both percentages")
    if not all(
        isinstance(value, Decimal)
        for value in (baseline_catalog_coverage_pct, baseline_pbev_coverage_pct)
    ):
        raise ValueError("coverage baseline arithmetic must use Decimal")
    if (
        catalog_coverage_pct < baseline_catalog_coverage_pct
        or pbev_coverage_pct < baseline_pbev_coverage_pct
    ):
        return CoverageRegressionStatus.MANUAL_REVIEW_REQUIRED
    return CoverageRegressionStatus.PASSED


@dataclass(frozen=True)
class SetReconciliation:
    expected: FrozenSet[Hashable]
    published: FrozenSet[Hashable]
    excluded: FrozenSet[Hashable]
    missing: FrozenSet[Hashable]
    unexpected: FrozenSet[Hashable]

    @property
    def passed(self) -> bool:
        return not self.missing and not self.unexpected

    @classmethod
    def build(
        cls,
        *,
        expected: Iterable[Hashable],
        published: Iterable[Hashable],
        excluded: Iterable[Hashable],
    ) -> "SetReconciliation":
        expected_set = frozenset(expected)
        published_set = frozenset(published)
        excluded_set = frozenset(excluded)
        overlap = published_set & excluded_set
        if overlap:
            raise ValueError("published and excluded sets must be disjoint")
        accounted = published_set | excluded_set
        return cls(
            expected=expected_set,
            published=published_set,
            excluded=excluded_set,
            missing=expected_set - accounted,
            unexpected=accounted - expected_set,
        )


@dataclass(frozen=True)
class QualityRuleContract:
    quality_policy_version: str
    rule_code: str
    rule_kind: QualityRuleKind
    severity: QualitySeverity
    required_for_activation: bool
    expected_status: QualityExpectedStatus

    def __post_init__(self) -> None:
        if self.rule_kind is QualityRuleKind.HARD_GATE:
            if self.severity is not QualitySeverity.CRITICAL:
                raise ValueError("hard gates must be critical")
            if self.expected_status is not QualityExpectedStatus.PASSED:
                raise ValueError("hard gates must expect passed")
        elif self.expected_status is not QualityExpectedStatus.NOT_CALIBRATED:
            raise ValueError("statistical controls must remain not_calibrated")


@dataclass(frozen=True)
class QualityResultIdentity:
    dataset_version: str
    quality_policy_version: str
    rule_code: str

    def __post_init__(self) -> None:
        _require_version(self.dataset_version, "dataset_version", 96)
        _require_version(self.quality_policy_version, "quality_policy_version", 80)
        _require_version(self.rule_code, "rule_code", 80)
