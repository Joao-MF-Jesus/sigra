"""Motor stateless e deterministico da simulacao de custo veicular."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from data_platform.contracts.integrated_vehicle_cost import FuelScenarioCode
from data_platform.integrated_vehicle_cost.simulation_contracts import (
    CONSUMPTION_QUANTUM,
    COST_PER_KM_QUANTUM,
    DIFFERENCE_PERCENT_QUANTUM,
    LITERS_QUANTUM,
    MONEY_QUANTUM,
    SIMULATION_POLICY_VERSION,
    FuelStrategy,
    PublishedVehicleExclusion,
    SimulationEvidenceOrigin,
    VehicleCostEvidence,
    VehicleCostSimulationBatch,
    VehicleCostSimulationExclusion,
    VehicleCostSimulationResult,
    VehicleCostSimulationScenario,
    canonical_fingerprint,
    result_fingerprint_payload,
)


_FUEL_TIE_ORDER = {
    FuelScenarioCode.GASOLINE_C_COMMON: 0,
    FuelScenarioCode.GASOLINE_C_ADDITIZED: 1,
    FuelScenarioCode.ETHANOL_HYDRATED: 2,
}
_SUPPORTED_FUELS = frozenset(_FUEL_TIE_ORDER)


class VehicleCostSimulationError(ValueError):
    """Entrada ou evidencia inconsistente para uma simulacao pura."""


class VehicleCostSimulationSelectionConflictError(VehicleCostSimulationError):
    """A selecao explicita corresponde a mais de uma evidencia elegivel."""


def _calculate(
    scenario: VehicleCostSimulationScenario,
    evidence: VehicleCostEvidence,
    *,
    single_fuel_for_lowest: bool,
) -> VehicleCostSimulationResult:
    city_consumption = (
        scenario.city_consumption_km_l
        if scenario.city_consumption_km_l is not None
        else evidence.city_consumption_km_l
    )
    highway_consumption = (
        scenario.highway_consumption_km_l
        if scenario.highway_consumption_km_l is not None
        else evidence.highway_consumption_km_l
    )
    fuel_price = (
        scenario.manual_fuel_price_brl
        if scenario.manual_fuel_price_brl is not None
        else evidence.fuel_price_per_liter_brl
    )
    city_distance = scenario.monthly_distance_km * scenario.city_share
    highway_distance = scenario.monthly_distance_km * scenario.highway_share
    raw_monthly_liters = (
        city_distance / city_consumption
        + highway_distance / highway_consumption
    )
    monthly_liters = raw_monthly_liters.quantize(
        LITERS_QUANTUM,
        rounding=ROUND_HALF_UP,
    )
    weighted_consumption = (
        scenario.monthly_distance_km / monthly_liters
    ).quantize(
        CONSUMPTION_QUANTUM,
        rounding=ROUND_HALF_UP,
    )
    annual_liters = (monthly_liters * Decimal("12")).quantize(
        LITERS_QUANTUM,
        rounding=ROUND_HALF_UP,
    )
    monthly_cost = (raw_monthly_liters * fuel_price).quantize(
        MONEY_QUANTUM,
        rounding=ROUND_HALF_UP,
    )
    cost_per_km = (monthly_cost / scenario.monthly_distance_km).quantize(
        COST_PER_KM_QUANTUM,
        rounding=ROUND_HALF_UP,
    )
    annual_cost = (monthly_cost * Decimal("12")).quantize(
        MONEY_QUANTUM,
        rounding=ROUND_HALF_UP,
    )
    horizon_cost = (monthly_cost * Decimal(scenario.horizon_months)).quantize(
        MONEY_QUANTUM,
        rounding=ROUND_HALF_UP,
    )
    monthly_difference = (
        monthly_cost - evidence.analytical_projected_monthly_cost_brl
    ).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    difference_percentage = (
        monthly_difference
        / evidence.analytical_projected_monthly_cost_brl
        * Decimal("100")
    ).quantize(DIFFERENCE_PERCENT_QUANTUM, rounding=ROUND_HALF_UP)
    warnings: list[str] = []
    if not scenario.uses_manual_price and scenario.municipality is None:
        warnings.append("ANP_STATE_LEVEL_PRICE")
    if scenario.uses_manual_price:
        warnings.append("MANUAL_FUEL_PRICE_SIMULATION_ONLY")
    if scenario.city_consumption_km_l is not None:
        warnings.append("CUSTOM_CITY_EFFICIENCY_SIMULATION_ONLY")
    if scenario.highway_consumption_km_l is not None:
        warnings.append("CUSTOM_HIGHWAY_EFFICIENCY_SIMULATION_ONLY")
    if single_fuel_for_lowest:
        warnings.append("LOWEST_COST_HAS_SINGLE_COMPATIBLE_FUEL")
    return VehicleCostSimulationResult(
        rank=0,
        vehicle_sk=evidence.vehicle_sk,
        brand_name=evidence.brand_name,
        model_name=evidence.model_name,
        version_name=evidence.version_name,
        model_year=evidence.model_year,
        fuel_code=evidence.fuel_code,
        city_consumption_km_l=city_consumption,
        highway_consumption_km_l=highway_consumption,
        weighted_consumption_km_l=weighted_consumption,
        estimated_monthly_liters=monthly_liters,
        estimated_annual_liters=annual_liters,
        monthly_fuel_cost_brl=monthly_cost,
        annual_fuel_cost_brl=annual_cost,
        fuel_cost_per_km_brl=cost_per_km,
        fuel_price_per_liter_brl=fuel_price,
        fuel_price_origin=(
            SimulationEvidenceOrigin.USER_INPUT
            if scenario.uses_manual_price
            else SimulationEvidenceOrigin.ANP_GOLD
        ),
        city_consumption_origin=(
            SimulationEvidenceOrigin.USER_INPUT
            if scenario.city_consumption_km_l is not None
            else SimulationEvidenceOrigin.PBEV_GOLD
        ),
        highway_consumption_origin=(
            SimulationEvidenceOrigin.USER_INPUT
            if scenario.highway_consumption_km_l is not None
            else SimulationEvidenceOrigin.PBEV_GOLD
        ),
        canonical_comparison_origin=SimulationEvidenceOrigin.CANONICAL_POLICY,
        horizon_months=scenario.horizon_months,
        projected_horizon_cost_brl=horizon_cost,
        canonical_scenario_code=evidence.analytical_scenario_code,
        canonical_monthly_distance_km=evidence.analytical_monthly_distance_km,
        canonical_monthly_fuel_cost_brl=(
            evidence.analytical_projected_monthly_cost_brl
        ),
        canonical_annual_fuel_cost_brl=(
            evidence.analytical_projected_annual_cost_brl
        ),
        monthly_cost_difference_brl=monthly_difference,
        monthly_cost_difference_percentage=difference_percentage,
        state_code=scenario.state_code,
        municipality=scenario.municipality,
        anp_week_start=(None if scenario.uses_manual_price else evidence.anp_week_start),
        anp_week_end=(None if scenario.uses_manual_price else evidence.anp_week_end),
        sources=evidence.sources,
        simulation_policy_version=SIMULATION_POLICY_VERSION,
        warnings=tuple(warnings),
        limitations=(
            "ACTIVE_PUBLISHED_GOLD_EVIDENCE_ONLY",
            "FUEL_COST_ONLY",
            "NO_FINANCING_MAINTENANCE_INSURANCE_TAX_OR_DEPRECIATION",
        ),
    )


def _matches_exact_grain(
    scenario: VehicleCostSimulationScenario,
    evidence: VehicleCostEvidence,
) -> bool:
    return (
        evidence.requested_geography_level == scenario.geography_level
        and evidence.requested_geography_key == scenario.geography_key
        and evidence.anp_week_start == scenario.reference_week_start
    )


def _rank_key(item: VehicleCostSimulationResult) -> tuple[object, ...]:
    return (
        item.monthly_fuel_cost_brl,
        item.fuel_cost_per_km_brl,
        item.brand_name.casefold(),
        item.model_name.casefold(),
        (item.version_name or "").casefold(),
        item.model_year if item.model_year is not None else 0,
        item.vehicle_sk,
        _FUEL_TIE_ORDER[item.fuel_code],
    )


def simulate_vehicle_costs(
    scenario: VehicleCostSimulationScenario,
    evidence_rows: Iterable[VehicleCostEvidence],
    published_exclusions: Iterable[PublishedVehicleExclusion] = (),
) -> VehicleCostSimulationBatch:
    """Calcula sem persistencia, clock, UUID, rede ou valores implicitos."""
    rows_by_vehicle: dict[int, list[VehicleCostEvidence]] = defaultdict(list)
    seen_grains: set[tuple[int, str, str, str, object]] = set()
    for row in evidence_rows:
        grain = (
            row.vehicle_sk,
            row.fuel_code.value,
            row.requested_geography_level,
            row.requested_geography_key,
            row.anp_week_start,
        )
        if grain in seen_grains:
            raise VehicleCostSimulationError("Gold evidence grain is duplicated")
        seen_grains.add(grain)
        rows_by_vehicle[row.vehicle_sk].append(row)

    exclusions_by_vehicle: dict[int, PublishedVehicleExclusion] = {}
    for exclusion in published_exclusions:
        if exclusion.vehicle_sk in exclusions_by_vehicle:
            raise VehicleCostSimulationError("Gold exclusion grain is duplicated")
        exclusions_by_vehicle[exclusion.vehicle_sk] = exclusion

    if scenario.vehicle_sks is not None:
        vehicle_ids = set(scenario.vehicle_sks)
    else:
        vehicle_ids = set(rows_by_vehicle) | set(exclusions_by_vehicle)

    calculated: list[VehicleCostSimulationResult] = []
    audited_exclusions: list[VehicleCostSimulationExclusion] = []
    for vehicle_sk in sorted(vehicle_ids):
        published_exclusion = exclusions_by_vehicle.get(vehicle_sk)
        if published_exclusion is not None:
            audited_exclusions.append(
                VehicleCostSimulationExclusion(
                    vehicle_sk=vehicle_sk,
                    reason_code=published_exclusion.reason_code,
                    detail="vehicle is excluded by the active integrated Gold dataset",
                )
            )
            continue

        all_vehicle_rows = rows_by_vehicle.get(vehicle_sk, [])
        if not all_vehicle_rows:
            audited_exclusions.append(
                VehicleCostSimulationExclusion(
                    vehicle_sk=vehicle_sk,
                    reason_code="VEHICLE_NOT_IN_ACTIVE_INTEGRATED_GOLD",
                    detail="no published active Gold evidence exists for the vehicle",
                )
            )
            continue
        exact_rows = [row for row in all_vehicle_rows if _matches_exact_grain(scenario, row)]
        if not scenario.uses_manual_price and not exact_rows:
            audited_exclusions.append(
                VehicleCostSimulationExclusion(
                    vehicle_sk=vehicle_sk,
                    reason_code="ANP_EXACT_EVIDENCE_NOT_AVAILABLE",
                    detail="no price exists for the requested geography and week",
                )
            )
            continue
        candidate_rows = all_vehicle_rows if scenario.uses_manual_price else exact_rows
        supported_rows = [row for row in candidate_rows if row.fuel_code in _SUPPORTED_FUELS]
        if scenario.fuel_strategy is FuelStrategy.GASOLINE_C_COMMON:
            compatible = [
                row
                for row in supported_rows
                if row.fuel_code is FuelScenarioCode.GASOLINE_C_COMMON
            ]
        elif scenario.fuel_strategy is FuelStrategy.GASOLINE_C_ADDITIZED:
            compatible = [
                row
                for row in supported_rows
                if row.fuel_code is FuelScenarioCode.GASOLINE_C_ADDITIZED
            ]
        elif scenario.fuel_strategy is FuelStrategy.ETHANOL_HYDRATED:
            compatible = [
                row
                for row in supported_rows
                if row.fuel_code is FuelScenarioCode.ETHANOL_HYDRATED
            ]
        else:
            compatible = supported_rows
        if not compatible:
            audited_exclusions.append(
                VehicleCostSimulationExclusion(
                    vehicle_sk=vehicle_sk,
                    reason_code="FUEL_INCOMPATIBLE",
                    detail="the requested fuel has no compatible published PBEV evidence",
                )
            )
            continue
        if scenario.uses_manual_price and len(compatible) != 1:
            raise VehicleCostSimulationSelectionConflictError(
                "manual-price Gold efficiency evidence is ambiguous"
            )
        candidates = [
            _calculate(
                scenario,
                row,
                single_fuel_for_lowest=(
                    scenario.fuel_strategy is FuelStrategy.LOWEST_PROJECTED_COST
                    and len(compatible) == 1
                ),
            )
            for row in compatible
        ]
        chosen = min(
            candidates,
            key=lambda item: (
                item.monthly_fuel_cost_brl,
                item.fuel_cost_per_km_brl,
                _FUEL_TIE_ORDER[item.fuel_code],
            ),
        )
        calculated.append(chosen)

    ranked_all = tuple(
        replace(item, rank=index)
        for index, item in enumerate(sorted(calculated, key=_rank_key), start=1)
    )
    returned = (
        ranked_all[: scenario.max_results]
        if scenario.max_results is not None
        else ranked_all
    )
    exclusions = tuple(
        sorted(audited_exclusions, key=lambda item: (item.vehicle_sk, item.reason_code))
    )
    payload = result_fingerprint_payload(
        scenario,
        returned,
        exclusions,
        evaluated_vehicle_count=len(vehicle_ids),
        eligible_vehicle_count=len(ranked_all),
    )
    return VehicleCostSimulationBatch(
        scenario=scenario,
        results=returned,
        exclusions=exclusions,
        evaluated_vehicle_count=len(vehicle_ids),
        eligible_vehicle_count=len(ranked_all),
        excluded_vehicle_count=len(exclusions),
        returned_vehicle_count=len(returned),
        fingerprint=canonical_fingerprint(payload),
    )
