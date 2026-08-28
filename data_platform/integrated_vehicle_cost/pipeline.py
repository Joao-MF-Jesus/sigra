from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
import hashlib
import json
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4

from data_platform.contracts.integrated_vehicle_cost import (
    DEFAULT_DISTANCE_SCENARIO,
    INTEGRATED_QUALITY_POLICY_VERSION,
    MIXED_1000_V1,
    CoverageRegressionStatus,
    FuelScenarioCode,
    calculate_projection,
    coverage_pct,
    coverage_regression_status,
)
from data_platform.quality.integrated_checks import (
    INTEGRATED_HARD_GATE_RULES,
    build_integrated_quality_catalog,
    reconcile_integrated_grains,
)


PIPELINE_NAME = "integrated_vehicle_cost_gold"
PIPELINE_VERSION = "integrated-vehicle-cost-publication-v1"
CALCULATION_POLICY_VERSION = "integrated-decimal-v1"
GEOGRAPHY_POLICY_VERSION = "exact-geography-v1"
SCENARIO_POLICY_VERSION = "mixed-1000-v1"
REQUIRED_PRODUCT_CODES = (
    FuelScenarioCode.ETHANOL_HYDRATED,
    FuelScenarioCode.GASOLINE_C_COMMON,
)
OPTIONAL_PRODUCT_CODE = FuelScenarioCode.GASOLINE_C_ADDITIZED
PERCENT_QUANTUM = Decimal("0.0001")


class IntegratedPublicationError(RuntimeError):
    """Falha deterministica e sanitizada da publicacao integrada."""


def _json_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        _json_value(payload),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class IntegratedPublicationRequest:
    geography_level: str
    geography_key: str
    week_start: date
    include_additized: bool = True

    def __post_init__(self) -> None:
        if self.geography_level not in {"municipality", "state"}:
            raise ValueError("integrated geography must be municipality or state")
        if not self.geography_key or len(self.geography_key) > 200:
            raise ValueError("integrated geography key must contain 1 to 200 characters")
        if not isinstance(self.week_start, date):
            raise ValueError("integrated ANP week_start must be a date")

    @property
    def week_end(self) -> date:
        return self.week_start + timedelta(days=6)

    @property
    def optional_product_codes(self) -> tuple[FuelScenarioCode, ...]:
        return (OPTIONAL_PRODUCT_CODE,) if self.include_additized else ()

    def manifest(self) -> dict[str, object]:
        return {
            "geography_level": self.geography_level,
            "geography_key": self.geography_key,
            "week_start": self.week_start,
            "week_end": self.week_end,
            "required_product_codes": tuple(
                sorted(item.value for item in REQUIRED_PRODUCT_CODES)
            ),
            "optional_product_codes": tuple(
                sorted(item.value for item in self.optional_product_codes)
            ),
        }


@dataclass(frozen=True)
class ActiveGoldSources:
    fipe_dataset_version: str
    fipe_fingerprint: str
    pbev_dataset_version: str
    pbev_fingerprint: str
    anp_dataset_version: str
    anp_fingerprint: str

    def __post_init__(self) -> None:
        for field_name in (
            "fipe_dataset_version",
            "pbev_dataset_version",
            "anp_dataset_version",
        ):
            value = getattr(self, field_name)
            if not value or len(value) > 80:
                raise ValueError(f"{field_name} must contain 1 to 80 characters")
        for field_name in (
            "fipe_fingerprint",
            "pbev_fingerprint",
            "anp_fingerprint",
        ):
            value = getattr(self, field_name)
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"{field_name} must be a lowercase SHA-256")


@dataclass(frozen=True)
class GoldVehicleInput:
    vehicle_sk: int
    fipe_gold_record_id: int
    vehicle_price_brl: Decimal
    price_reference_month: date
    fipe_published_at: datetime
    fipe_currency: str
    pbev_gold_record_id: int | None
    pbev_cycle_year: int | None
    fossil_city_km_l: Decimal | None
    fossil_highway_km_l: Decimal | None
    ethanol_city_km_l: Decimal | None
    ethanol_highway_km_l: Decimal | None
    pbev_published_at: datetime | None


@dataclass(frozen=True)
class GoldFuelPriceInput:
    anp_gold_snapshot_id: int
    product_code: FuelScenarioCode
    week_start: date
    week_end: date
    geography_level: str
    geography_key: str
    median_price: Decimal
    currency_code: str
    unit_code: str


@dataclass(frozen=True)
class IntegratedSnapshotCandidate:
    vehicle_sk: int
    fuel_scenario_code: FuelScenarioCode
    requested_geography_level: str
    requested_geography_key: str
    anp_week_start: date
    anp_week_end: date
    fipe_gold_record_id: int
    pbev_gold_record_id: int
    anp_gold_snapshot_id: int
    vehicle_price_brl: Decimal
    price_reference_month: date
    pbev_cycle_year: int
    city_consumption_km_l: Decimal
    highway_consumption_km_l: Decimal
    fuel_price_per_liter_brl: Decimal
    city_cost_per_km_brl: Decimal
    highway_cost_per_km_brl: Decimal
    mixed_cost_per_km_brl: Decimal
    projected_monthly_cost_brl: Decimal
    projected_annual_cost_brl: Decimal
    snapshot_fingerprint: str
    projection_fingerprint: str

    @property
    def key(self) -> tuple[int, str, str, str, date]:
        return (
            self.vehicle_sk,
            self.fuel_scenario_code.value,
            self.requested_geography_level,
            self.requested_geography_key,
            self.anp_week_start,
        )


@dataclass(frozen=True)
class IntegratedExclusionCandidate:
    vehicle_sk: int
    fipe_gold_record_id: int
    pbev_gold_record_id: int | None
    reason_code: str
    details: Mapping[str, object]
    exclusion_fingerprint: str


@dataclass(frozen=True)
class IntegratedFlexComparisonCandidate:
    vehicle_sk: int
    requested_geography_level: str
    requested_geography_key: str
    anp_week_start: date
    gasoline_snapshot_key: tuple[int, str, str, str, date]
    ethanol_snapshot_key: tuple[int, str, str, str, date]
    city_cost_difference_brl: Decimal
    highway_cost_difference_brl: Decimal
    mixed_cost_difference_brl: Decimal
    mixed_cost_difference_pct: Decimal
    lower_cost_product_code: str
    comparison_fingerprint: str


@dataclass(frozen=True)
class IntegratedQualityResultCandidate:
    rule_code: str
    rule_kind: str
    severity: str
    status: str
    observed_value: Mapping[str, object]
    expected_condition: str
    details: Mapping[str, object]


@dataclass(frozen=True)
class IntegratedMaterializationPlan:
    sources: ActiveGoldSources
    request: IntegratedPublicationRequest
    analytic_cutoff_at: datetime
    snapshots: tuple[IntegratedSnapshotCandidate, ...]
    exclusions: tuple[IntegratedExclusionCandidate, ...]
    flex_comparisons: tuple[IntegratedFlexComparisonCandidate, ...]
    quality_results: tuple[IntegratedQualityResultCandidate, ...]
    catalog_universe_count: int
    pbev_matched_universe_count: int
    eligible_vehicle_count: int
    published_vehicle_count: int
    excluded_vehicle_count: int
    requested_scenario_count: int
    published_scenario_count: int
    excluded_scenario_count: int
    catalog_coverage_pct: Decimal
    pbev_coverage_pct: Decimal
    coverage_baseline_event_id_used: int | None
    coverage_regression_status: CoverageRegressionStatus
    dataset_fingerprint: str

    @property
    def activation_authorized(self) -> bool:
        return self.coverage_regression_status is not CoverageRegressionStatus.MANUAL_REVIEW_REQUIRED


@dataclass(frozen=True)
class IntegratedVehicleCostOptions:
    request: IntegratedPublicationRequest | None = None
    dry_run: bool = False
    trigger_type: str = "manual"
    git_commit: str | None = None

    def __post_init__(self) -> None:
        if self.trigger_type not in {"manual", "scheduled", "retry", "backfill"}:
            raise ValueError("unsupported integrated trigger_type")


@dataclass(frozen=True)
class IntegratedPipelineResult:
    status: str
    dataset_version: str | None
    pipeline_run_id: str | None
    previous_dataset_version: str | None
    activation_type: str | None
    published_vehicle_count: int
    excluded_vehicle_count: int
    published_scenario_count: int
    catalog_coverage_pct: Decimal
    pbev_coverage_pct: Decimal
    plan: Mapping[str, object] | None = None

    def to_json(self) -> str:
        return json.dumps(
            _json_value(
                {
                    "status": self.status,
                    "dataset_version": self.dataset_version,
                    "pipeline_run_id": self.pipeline_run_id,
                    "previous_dataset_version": self.previous_dataset_version,
                    "activation_type": self.activation_type,
                    "published_vehicle_count": self.published_vehicle_count,
                    "excluded_vehicle_count": self.excluded_vehicle_count,
                    "published_scenario_count": self.published_scenario_count,
                    "catalog_coverage_pct": self.catalog_coverage_pct,
                    "pbev_coverage_pct": self.pbev_coverage_pct,
                    "plan": self.plan,
                }
            ),
            ensure_ascii=False,
            sort_keys=True,
        )


def _positive_decimal(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal) or value <= 0:
        raise IntegratedPublicationError(f"{field_name} must be a positive Decimal")
    return value


def _consumption_pair(
    vehicle: GoldVehicleInput,
    product_code: FuelScenarioCode,
) -> tuple[Decimal | None, Decimal | None]:
    if product_code is FuelScenarioCode.ETHANOL_HYDRATED:
        return vehicle.ethanol_city_km_l, vehicle.ethanol_highway_km_l
    return vehicle.fossil_city_km_l, vehicle.fossil_highway_km_l


def _quality_results(
    *,
    catalog_count: int,
    pbev_count: int,
    published_vehicle_count: int,
    published_scenario_count: int,
    excluded_vehicle_count: int,
    regression_status: CoverageRegressionStatus,
) -> tuple[IntegratedQualityResultCandidate, ...]:
    counts = {
        "catalog_universe_count": catalog_count,
        "pbev_matched_universe_count": pbev_count,
        "published_vehicle_count": published_vehicle_count,
        "published_scenario_count": published_scenario_count,
        "excluded_vehicle_count": excluded_vehicle_count,
    }
    results = []
    for rule in build_integrated_quality_catalog():
        status = rule.expected_status.value
        if (
            rule.rule_code == "INTEGRATED_COVERAGE_NON_REGRESSION"
            and regression_status is CoverageRegressionStatus.MANUAL_REVIEW_REQUIRED
        ):
            status = "failed"
        results.append(
            IntegratedQualityResultCandidate(
                rule_code=rule.rule_code,
                rule_kind=rule.rule_kind.value,
                severity=rule.severity.value,
                status=status,
                observed_value={
                    "status": status,
                    "counts": counts,
                    "coverage_regression_status": regression_status.value,
                },
                expected_condition=f"status must be {rule.expected_status.value}",
                details={"quality_policy_version": INTEGRATED_QUALITY_POLICY_VERSION},
            )
        )
    return tuple(results)


def build_materialization_plan(
    *,
    sources: ActiveGoldSources,
    request: IntegratedPublicationRequest,
    vehicles: Sequence[GoldVehicleInput],
    fuel_prices: Sequence[GoldFuelPriceInput],
    analytic_cutoff_at: datetime,
    baseline_event_id: int | None = None,
    baseline_catalog_coverage_pct: Decimal | None = None,
    baseline_pbev_coverage_pct: Decimal | None = None,
) -> IntegratedMaterializationPlan:
    if analytic_cutoff_at.tzinfo is None:
        raise ValueError("analytic_cutoff_at must be timezone-aware")
    if not vehicles:
        raise IntegratedPublicationError("active FIPE Gold dataset is empty")
    vehicle_ids = [item.vehicle_sk for item in vehicles]
    if len(vehicle_ids) != len(set(vehicle_ids)) or any(item <= 0 for item in vehicle_ids):
        raise IntegratedPublicationError("FIPE Gold vehicle grain is not unique")

    selected_codes = set(REQUIRED_PRODUCT_CODES) | set(request.optional_product_codes)
    prices_by_code: dict[FuelScenarioCode, GoldFuelPriceInput] = {}
    for item in fuel_prices:
        if item.product_code not in selected_codes:
            raise IntegratedPublicationError("ANP Gold returned an undeclared product")
        if item.product_code in prices_by_code:
            raise IntegratedPublicationError("ANP Gold product grain is not unique")
        if (
            item.week_start != request.week_start
            or item.week_end != request.week_end
            or item.geography_level != request.geography_level
            or item.geography_key != request.geography_key
        ):
            raise IntegratedPublicationError("ANP Gold does not match the exact request grain")
        if item.currency_code != "BRL" or item.unit_code != "liter":
            raise IntegratedPublicationError("ANP Gold currency or unit is unsupported")
        _positive_decimal(item.median_price, "ANP median price")
        prices_by_code[item.product_code] = item
    if not set(REQUIRED_PRODUCT_CODES).issubset(prices_by_code):
        raise IntegratedPublicationError("ANP Gold lacks a required fuel product")

    snapshots: list[IntegratedSnapshotCandidate] = []
    exclusions: list[IntegratedExclusionCandidate] = []
    flex_comparisons: list[IntegratedFlexComparisonCandidate] = []
    pbev_count = 0
    for vehicle in sorted(vehicles, key=lambda item: item.vehicle_sk):
        _positive_decimal(vehicle.vehicle_price_brl, "FIPE vehicle price")
        if vehicle.fipe_currency != "BRL":
            raise IntegratedPublicationError("FIPE Gold currency is unsupported")
        if vehicle.fipe_published_at > analytic_cutoff_at:
            raise IntegratedPublicationError("FIPE Gold contains future evidence")
        if vehicle.pbev_gold_record_id is None:
            payload = {
                "vehicle_sk": vehicle.vehicle_sk,
                "reason_code": "PBEV_MATCHED_GOLD_NOT_AVAILABLE",
                "fipe_gold_record_id": vehicle.fipe_gold_record_id,
            }
            exclusions.append(
                IntegratedExclusionCandidate(
                    vehicle_sk=vehicle.vehicle_sk,
                    fipe_gold_record_id=vehicle.fipe_gold_record_id,
                    pbev_gold_record_id=None,
                    reason_code="PBEV_MATCHED_GOLD_NOT_AVAILABLE",
                    details={"source": "gold.vehicle_efficiency_snapshot"},
                    exclusion_fingerprint=canonical_hash(payload),
                )
            )
            continue
        pbev_count += 1
        if vehicle.pbev_published_at is None or vehicle.pbev_published_at > analytic_cutoff_at:
            raise IntegratedPublicationError("PBEV Gold contains future or incomplete evidence")
        if vehicle.pbev_cycle_year is None:
            raise IntegratedPublicationError("PBEV Gold cycle year is missing")

        vehicle_snapshots: list[IntegratedSnapshotCandidate] = []
        for product_code, price in sorted(prices_by_code.items(), key=lambda item: item[0].value):
            city_consumption, highway_consumption = _consumption_pair(vehicle, product_code)
            if (city_consumption is None) != (highway_consumption is None):
                raise IntegratedPublicationError("PBEV Gold consumption pair is incomplete")
            if city_consumption is None:
                continue
            _positive_decimal(city_consumption, "PBEV city consumption")
            _positive_decimal(highway_consumption, "PBEV highway consumption")
            projection = calculate_projection(
                fuel_price_per_liter_brl=price.median_price,
                city_consumption_km_l=city_consumption,
                highway_consumption_km_l=highway_consumption,
            )
            material = {
                "vehicle_sk": vehicle.vehicle_sk,
                "fuel_scenario_code": product_code,
                "geography_level": request.geography_level,
                "geography_key": request.geography_key,
                "week_start": request.week_start,
                "fipe_gold_record_id": vehicle.fipe_gold_record_id,
                "pbev_gold_record_id": vehicle.pbev_gold_record_id,
                "anp_gold_snapshot_id": price.anp_gold_snapshot_id,
                "vehicle_price_brl": vehicle.vehicle_price_brl,
                "price_reference_month": vehicle.price_reference_month,
                "pbev_cycle_year": vehicle.pbev_cycle_year,
                "city_consumption_km_l": city_consumption,
                "highway_consumption_km_l": highway_consumption,
                "fuel_price_per_liter_brl": price.median_price,
                "city_cost_per_km_brl": projection.city_cost_per_km_brl,
                "highway_cost_per_km_brl": projection.highway_cost_per_km_brl,
                "mixed_cost_per_km_brl": projection.mixed_cost_per_km_brl,
            }
            snapshot_fingerprint = canonical_hash(material)
            projection_fingerprint = canonical_hash(
                {
                    "snapshot_fingerprint": snapshot_fingerprint,
                    "scenario_code": MIXED_1000_V1,
                    "monthly_distance_km": DEFAULT_DISTANCE_SCENARIO.monthly_distance_km,
                    "annual_distance_km": DEFAULT_DISTANCE_SCENARIO.annual_distance_km,
                    "projected_monthly_cost_brl": projection.projected_monthly_cost_brl,
                    "projected_annual_cost_brl": projection.projected_annual_cost_brl,
                }
            )
            vehicle_snapshots.append(
                IntegratedSnapshotCandidate(
                    vehicle_sk=vehicle.vehicle_sk,
                    fuel_scenario_code=product_code,
                    requested_geography_level=request.geography_level,
                    requested_geography_key=request.geography_key,
                    anp_week_start=request.week_start,
                    anp_week_end=request.week_end,
                    fipe_gold_record_id=vehicle.fipe_gold_record_id,
                    pbev_gold_record_id=vehicle.pbev_gold_record_id,
                    anp_gold_snapshot_id=price.anp_gold_snapshot_id,
                    vehicle_price_brl=vehicle.vehicle_price_brl,
                    price_reference_month=vehicle.price_reference_month,
                    pbev_cycle_year=vehicle.pbev_cycle_year,
                    city_consumption_km_l=city_consumption,
                    highway_consumption_km_l=highway_consumption,
                    fuel_price_per_liter_brl=price.median_price,
                    city_cost_per_km_brl=projection.city_cost_per_km_brl,
                    highway_cost_per_km_brl=projection.highway_cost_per_km_brl,
                    mixed_cost_per_km_brl=projection.mixed_cost_per_km_brl,
                    projected_monthly_cost_brl=projection.projected_monthly_cost_brl,
                    projected_annual_cost_brl=projection.projected_annual_cost_brl,
                    snapshot_fingerprint=snapshot_fingerprint,
                    projection_fingerprint=projection_fingerprint,
                )
            )
        if not vehicle_snapshots:
            payload = {
                "vehicle_sk": vehicle.vehicle_sk,
                "reason_code": "PBEV_CONSUMPTION_NOT_AVAILABLE",
                "fipe_gold_record_id": vehicle.fipe_gold_record_id,
                "pbev_gold_record_id": vehicle.pbev_gold_record_id,
            }
            exclusions.append(
                IntegratedExclusionCandidate(
                    vehicle_sk=vehicle.vehicle_sk,
                    fipe_gold_record_id=vehicle.fipe_gold_record_id,
                    pbev_gold_record_id=vehicle.pbev_gold_record_id,
                    reason_code="PBEV_CONSUMPTION_NOT_AVAILABLE",
                    details={"scenario_code": MIXED_1000_V1},
                    exclusion_fingerprint=canonical_hash(payload),
                )
            )
            continue
        snapshots.extend(vehicle_snapshots)
        by_product = {item.fuel_scenario_code: item for item in vehicle_snapshots}
        gasoline = by_product.get(FuelScenarioCode.GASOLINE_C_COMMON)
        ethanol = by_product.get(FuelScenarioCode.ETHANOL_HYDRATED)
        if gasoline is not None and ethanol is not None:
            city_difference = gasoline.city_cost_per_km_brl - ethanol.city_cost_per_km_brl
            highway_difference = (
                gasoline.highway_cost_per_km_brl - ethanol.highway_cost_per_km_brl
            )
            mixed_difference = gasoline.mixed_cost_per_km_brl - ethanol.mixed_cost_per_km_brl
            mixed_difference_pct = (
                mixed_difference * Decimal("100") / gasoline.mixed_cost_per_km_brl
            ).quantize(PERCENT_QUANTUM, rounding=ROUND_HALF_UP)
            lower = (
                gasoline.fuel_scenario_code.value
                if gasoline.mixed_cost_per_km_brl < ethanol.mixed_cost_per_km_brl
                else ethanol.fuel_scenario_code.value
                if ethanol.mixed_cost_per_km_brl < gasoline.mixed_cost_per_km_brl
                else "tie"
            )
            comparison_payload = {
                "gasoline_projection_fingerprint": gasoline.projection_fingerprint,
                "ethanol_projection_fingerprint": ethanol.projection_fingerprint,
                "city_difference": city_difference,
                "highway_difference": highway_difference,
                "mixed_difference": mixed_difference,
                "mixed_difference_pct": mixed_difference_pct,
                "lower_cost_product_code": lower,
            }
            flex_comparisons.append(
                IntegratedFlexComparisonCandidate(
                    vehicle_sk=vehicle.vehicle_sk,
                    requested_geography_level=request.geography_level,
                    requested_geography_key=request.geography_key,
                    anp_week_start=request.week_start,
                    gasoline_snapshot_key=gasoline.key,
                    ethanol_snapshot_key=ethanol.key,
                    city_cost_difference_brl=city_difference,
                    highway_cost_difference_brl=highway_difference,
                    mixed_cost_difference_brl=mixed_difference,
                    mixed_cost_difference_pct=mixed_difference_pct,
                    lower_cost_product_code=lower,
                    comparison_fingerprint=canonical_hash(comparison_payload),
                )
            )

    snapshots = sorted(snapshots, key=lambda item: item.key)
    exclusions = sorted(exclusions, key=lambda item: item.vehicle_sk)
    published_vehicles = {item.vehicle_sk for item in snapshots}
    excluded_vehicles = {item.vehicle_sk for item in exclusions}
    scenario_keys = {
        (
            item.vehicle_sk,
            MIXED_1000_V1,
            item.fuel_scenario_code.value,
            item.requested_geography_level,
            item.requested_geography_key,
            item.anp_week_start,
        )
        for item in snapshots
    }
    vehicles_reconciliation, scenarios_reconciliation = reconcile_integrated_grains(
        expected_vehicles=set(vehicle_ids),
        published_vehicles=published_vehicles,
        excluded_vehicles=excluded_vehicles,
        expected_scenarios=scenario_keys,
        published_scenarios=scenario_keys,
        excluded_scenarios=set(),
    )
    if not vehicles_reconciliation.passed or not scenarios_reconciliation.passed:
        raise IntegratedPublicationError("integrated set reconciliation failed")

    catalog_count = len(vehicle_ids)
    published_vehicle_count = len(published_vehicles)
    catalog_coverage = coverage_pct(published_vehicle_count, catalog_count)
    pbev_coverage = coverage_pct(published_vehicle_count, pbev_count)
    regression_status = coverage_regression_status(
        catalog_coverage_pct=catalog_coverage,
        pbev_coverage_pct=pbev_coverage,
        baseline_catalog_coverage_pct=baseline_catalog_coverage_pct,
        baseline_pbev_coverage_pct=baseline_pbev_coverage_pct,
    )
    if regression_status is CoverageRegressionStatus.NOT_APPLICABLE:
        baseline_event_id = None
    elif baseline_event_id is None:
        raise IntegratedPublicationError("integrated coverage baseline identity is missing")
    quality_results = _quality_results(
        catalog_count=catalog_count,
        pbev_count=pbev_count,
        published_vehicle_count=published_vehicle_count,
        published_scenario_count=len(snapshots),
        excluded_vehicle_count=len(exclusions),
        regression_status=regression_status,
    )
    fingerprint_payload = {
        "sources": sources,
        "request": request.manifest(),
        "calculation_policy_version": CALCULATION_POLICY_VERSION,
        "geography_policy_version": GEOGRAPHY_POLICY_VERSION,
        "scenario_policy_version": SCENARIO_POLICY_VERSION,
        "quality_policy_version": INTEGRATED_QUALITY_POLICY_VERSION,
        "snapshot_fingerprints": tuple(item.snapshot_fingerprint for item in snapshots),
        "projection_fingerprints": tuple(item.projection_fingerprint for item in snapshots),
        "exclusion_fingerprints": tuple(item.exclusion_fingerprint for item in exclusions),
        "comparison_fingerprints": tuple(
            item.comparison_fingerprint for item in flex_comparisons
        ),
        "quality": tuple((item.rule_code, item.status) for item in quality_results),
        "coverage_baseline_event_id_used": baseline_event_id,
        "coverage_regression_status": regression_status,
    }
    return IntegratedMaterializationPlan(
        sources=sources,
        request=request,
        analytic_cutoff_at=analytic_cutoff_at,
        snapshots=tuple(snapshots),
        exclusions=tuple(exclusions),
        flex_comparisons=tuple(flex_comparisons),
        quality_results=quality_results,
        catalog_universe_count=catalog_count,
        pbev_matched_universe_count=pbev_count,
        eligible_vehicle_count=pbev_count,
        published_vehicle_count=published_vehicle_count,
        excluded_vehicle_count=len(exclusions),
        requested_scenario_count=len(snapshots),
        published_scenario_count=len(snapshots),
        excluded_scenario_count=0,
        catalog_coverage_pct=catalog_coverage,
        pbev_coverage_pct=pbev_coverage,
        coverage_baseline_event_id_used=baseline_event_id,
        coverage_regression_status=regression_status,
        dataset_fingerprint=canonical_hash(fingerprint_payload),
    )


def dataset_version_for(plan: IntegratedMaterializationPlan, run_id: UUID) -> str:
    return f"integrated-cost-v1-{plan.dataset_fingerprint[:20]}-{run_id.hex[:8]}"


def dry_run_plan(request: IntegratedPublicationRequest) -> dict[str, object]:
    return {
        "operation": "publish",
        "pipeline_name": PIPELINE_NAME,
        "pipeline_version": PIPELINE_VERSION,
        "request": request.manifest(),
        "source_layers": ("gold_fipe", "gold_pbev", "gold_anp"),
        "isolation_level": "REPEATABLE READ",
        "advisory_lock": "integrated_vehicle_cost",
        "calculation_policy_version": CALCULATION_POLICY_VERSION,
        "geography_policy_version": GEOGRAPHY_POLICY_VERSION,
        "scenario_policy_version": SCENARIO_POLICY_VERSION,
        "quality_policy_version": INTEGRATED_QUALITY_POLICY_VERSION,
        "hard_gate_count": len(INTEGRATED_HARD_GATE_RULES),
        "writes": False,
    }


def _counts_from_dataset(dataset: Mapping[str, object]) -> tuple[int, int, int, Decimal, Decimal]:
    return (
        int(dataset["published_vehicle_count"]),
        int(dataset["excluded_vehicle_count"]),
        int(dataset["published_scenario_count"]),
        Decimal(str(dataset["catalog_coverage_pct"])),
        Decimal(str(dataset["pbev_coverage_pct"])),
    )


def run_integrated_vehicle_cost_pipeline(
    loader: Any | None,
    options: IntegratedVehicleCostOptions,
) -> IntegratedPipelineResult:
    if options.request is None:
        raise ValueError("integrated publication request is required")
    if options.dry_run:
        return IntegratedPipelineResult(
            status="dry_run",
            dataset_version=None,
            pipeline_run_id=None,
            previous_dataset_version=None,
            activation_type=None,
            published_vehicle_count=0,
            excluded_vehicle_count=0,
            published_scenario_count=0,
            catalog_coverage_pct=Decimal("0.00"),
            pbev_coverage_pct=Decimal("0.00"),
            plan=dry_run_plan(options.request),
        )
    if loader is None:
        raise ValueError("integrated loader is required outside dry-run")
    if not loader.is_postgresql:
        return IntegratedPipelineResult(
            status="skipped",
            dataset_version=None,
            pipeline_run_id=None,
            previous_dataset_version=None,
            activation_type=None,
            published_vehicle_count=0,
            excluded_vehicle_count=0,
            published_scenario_count=0,
            catalog_coverage_pct=Decimal("0.00"),
            pbev_coverage_pct=Decimal("0.00"),
        )

    with loader.publication_transaction() as connection:
        cutoff = loader.transaction_timestamp(connection)
        sources = loader.load_active_sources(connection)
        vehicles = loader.load_vehicle_inputs(connection, sources)
        fuel_prices = loader.load_fuel_prices(connection, sources, options.request)
        baseline = loader.load_current_baseline(connection)
        plan = build_materialization_plan(
            sources=sources,
            request=options.request,
            vehicles=vehicles,
            fuel_prices=fuel_prices,
            analytic_cutoff_at=cutoff,
            baseline_event_id=(int(baseline["baseline_event_id"]) if baseline else None),
            baseline_catalog_coverage_pct=(
                Decimal(str(baseline["catalog_coverage_pct"])) if baseline else None
            ),
            baseline_pbev_coverage_pct=(
                Decimal(str(baseline["pbev_coverage_pct"])) if baseline else None
            ),
        )
        existing = loader.find_dataset_by_fingerprint(connection, plan.dataset_fingerprint)
        if existing is not None:
            if not bool(existing["is_active_shadow"]):
                raise IntegratedPublicationError(
                    "matching integrated evidence exists but is not active; explicit review or rollback is required"
                )
            run_id = uuid4()
            dataset_version = str(existing["dataset_version"])
            loader.start_run(
                connection,
                run_id=run_id,
                dataset_version=dataset_version,
                trigger_type=options.trigger_type,
                git_commit=options.git_commit,
            )
            loader.finish_run(
                connection,
                run_id=run_id,
                status="succeeded",
                received=plan.catalog_universe_count,
                inserted=0,
                deduplicated=plan.published_scenario_count,
                rejected=plan.excluded_vehicle_count,
            )
            counts = _counts_from_dataset(existing)
            return IntegratedPipelineResult(
                status="deduplicated",
                dataset_version=dataset_version,
                pipeline_run_id=str(run_id),
                previous_dataset_version=dataset_version,
                activation_type=None,
                published_vehicle_count=counts[0],
                excluded_vehicle_count=counts[1],
                published_scenario_count=counts[2],
                catalog_coverage_pct=counts[3],
                pbev_coverage_pct=counts[4],
            )

        active = loader.find_active_dataset(connection)
        run_id = uuid4()
        dataset_version = dataset_version_for(plan, run_id)
        if loader.find_dataset_by_version(connection, dataset_version) is not None:
            raise IntegratedPublicationError("integrated dataset version collision")
        loader.start_run(
            connection,
            run_id=run_id,
            dataset_version=dataset_version,
            trigger_type=options.trigger_type,
            git_commit=options.git_commit,
        )
        activation_type = None
        previous_dataset_version = str(active["dataset_version"]) if active else None
        if plan.activation_authorized:
            activation_type = "replace" if active else "publish"
        loader.persist_materialization(
            connection,
            run_id=run_id,
            dataset_version=dataset_version,
            plan=plan,
            activation_type=activation_type,
            previous_dataset_version=previous_dataset_version,
        )
        run_status = "succeeded" if plan.activation_authorized else "partial"
        loader.finish_run(
            connection,
            run_id=run_id,
            status=run_status,
            received=plan.catalog_universe_count,
            inserted=plan.published_scenario_count,
            deduplicated=0,
            rejected=plan.excluded_vehicle_count,
            error=(
                "integrated coverage regression requires manual review"
                if not plan.activation_authorized
                else None
            ),
        )
        return IntegratedPipelineResult(
            status=("succeeded" if plan.activation_authorized else "manual_review_required"),
            dataset_version=dataset_version,
            pipeline_run_id=str(run_id),
            previous_dataset_version=previous_dataset_version,
            activation_type=activation_type,
            published_vehicle_count=plan.published_vehicle_count,
            excluded_vehicle_count=plan.excluded_vehicle_count,
            published_scenario_count=plan.published_scenario_count,
            catalog_coverage_pct=plan.catalog_coverage_pct,
            pbev_coverage_pct=plan.pbev_coverage_pct,
        )


def rollback_integrated_vehicle_cost(
    loader: Any,
    dataset_version: str,
    *,
    trigger_type: str = "manual",
    git_commit: str | None = None,
) -> IntegratedPipelineResult:
    if not dataset_version or len(dataset_version) > 96:
        raise ValueError("rollback dataset_version must contain 1 to 96 characters")
    if trigger_type not in {"manual", "scheduled", "retry", "backfill"}:
        raise ValueError("unsupported integrated trigger_type")
    if not loader.is_postgresql:
        return IntegratedPipelineResult(
            status="skipped",
            dataset_version=dataset_version,
            pipeline_run_id=None,
            previous_dataset_version=None,
            activation_type=None,
            published_vehicle_count=0,
            excluded_vehicle_count=0,
            published_scenario_count=0,
            catalog_coverage_pct=Decimal("0.00"),
            pbev_coverage_pct=Decimal("0.00"),
        )
    with loader.publication_transaction() as connection:
        target = loader.get_dataset(connection, dataset_version)
        if target is None:
            raise IntegratedPublicationError("integrated rollback target does not exist")
        active = loader.find_active_dataset(connection)
        if active is not None and str(active["dataset_version"]) == dataset_version:
            run_id = uuid4()
            loader.start_run(
                connection,
                run_id=run_id,
                dataset_version=dataset_version,
                trigger_type=trigger_type,
                git_commit=git_commit,
                pipeline_name="integrated_vehicle_cost_rollback",
            )
            loader.finish_run(
                connection,
                run_id=run_id,
                status="succeeded",
                received=0,
                inserted=0,
                deduplicated=1,
                rejected=0,
            )
            counts = _counts_from_dataset(target)
            return IntegratedPipelineResult(
                status="deduplicated",
                dataset_version=dataset_version,
                pipeline_run_id=str(run_id),
                previous_dataset_version=dataset_version,
                activation_type=None,
                published_vehicle_count=counts[0],
                excluded_vehicle_count=counts[1],
                published_scenario_count=counts[2],
                catalog_coverage_pct=counts[3],
                pbev_coverage_pct=counts[4],
            )
        if active is None:
            raise IntegratedPublicationError("integrated rollback requires an active dataset")
        if (
            str(target["status"]) != "retired"
            or str(target["quality_status"]) != "passed"
            or str(target["hard_gate_status"]) != "passed"
            or str(target["coverage_regression_status"]) == "manual_review_required"
            or bool(target.get("is_invalidated", False))
        ):
            raise IntegratedPublicationError("integrated rollback target is not eligible")
        run_id = uuid4()
        loader.start_run(
            connection,
            run_id=run_id,
            dataset_version=dataset_version,
            trigger_type=trigger_type,
            git_commit=git_commit,
            pipeline_name="integrated_vehicle_cost_rollback",
        )
        previous_dataset_version = str(active["dataset_version"])
        loader.activate_rollback(
            connection,
            run_id=run_id,
            dataset_version=dataset_version,
            previous_dataset_version=previous_dataset_version,
        )
        loader.finish_run(
            connection,
            run_id=run_id,
            status="succeeded",
            received=0,
            inserted=0,
            deduplicated=0,
            rejected=0,
        )
        counts = _counts_from_dataset(target)
        return IntegratedPipelineResult(
            status="succeeded",
            dataset_version=dataset_version,
            pipeline_run_id=str(run_id),
            previous_dataset_version=previous_dataset_version,
            activation_type="rollback",
            published_vehicle_count=counts[0],
            excluded_vehicle_count=counts[1],
            published_scenario_count=counts[2],
            catalog_coverage_pct=counts[3],
            pbev_coverage_pct=counts[4],
        )
