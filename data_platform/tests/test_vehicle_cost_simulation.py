from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import inspect

import pytest

from data_platform.contracts.integrated_vehicle_cost import (
    DEFAULT_DISTANCE_SCENARIO,
    MIXED_1000_V1,
    FuelScenarioCode,
)
from data_platform.integrated_vehicle_cost import simulation as simulation_module
from data_platform.integrated_vehicle_cost import (
    simulation_contracts as contracts_module,
)
from data_platform.integrated_vehicle_cost.simulation import simulate_vehicle_costs
from data_platform.integrated_vehicle_cost.simulation_contracts import (
    SIMULATION_POLICY_VERSION,
    FuelStrategy,
    PublishedVehicleExclusion,
    SimulationSourceVersions,
    VehicleCostEvidence,
    VehicleCostSimulationScenario,
)


WEEK_START = date(2026, 8, 3)
WEEK_END = date(2026, 8, 9)
SOURCES = SimulationSourceVersions(
    integrated_dataset_version="integrated-v1",
    fipe_dataset_version="fipe-v1",
    pbev_dataset_version="pbev-v1",
    anp_dataset_version="anp-v1",
)


def scenario(**changes):
    values = {
        "monthly_distance_km": Decimal("1000.00"),
        "city_percentage": Decimal("50.00"),
        "highway_percentage": Decimal("50.00"),
        "state_code": "SP",
        "municipality": None,
        "reference_week_start": WEEK_START,
        "fuel_strategy": FuelStrategy.GASOLINE_C_COMMON,
        "horizon_months": 12,
    }
    values.update(changes)
    return VehicleCostSimulationScenario(**values)


def evidence(
    vehicle_sk=1,
    fuel=FuelScenarioCode.GASOLINE_C_COMMON,
    *,
    price="6.0000",
    city="12.0000",
    highway="15.0000",
    brand="Volkswagen",
    model="Polo",
    geography_level="state",
    geography_key="SP",
    week_start=WEEK_START,
):
    return VehicleCostEvidence(
        sources=SOURCES,
        vehicle_sk=vehicle_sk,
        brand_name=brand,
        model_name=model,
        version_name="Comfortline",
        model_year=2024,
        fuel_code=fuel,
        requested_geography_level=geography_level,
        requested_geography_key=geography_key,
        anp_week_start=week_start,
        anp_week_end=date.fromordinal(week_start.toordinal() + 6),
        city_consumption_km_l=Decimal(city),
        highway_consumption_km_l=Decimal(highway),
        fuel_price_per_liter_brl=Decimal(price),
        analytical_scenario_code=MIXED_1000_V1,
        analytical_monthly_distance_km=Decimal("1000.00"),
        analytical_annual_distance_km=Decimal("12000.00"),
        analytical_projected_monthly_cost_brl=Decimal("450.0000"),
        analytical_projected_annual_cost_brl=Decimal("5400.0000"),
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("monthly_distance_km", Decimal("0")),
        ("monthly_distance_km", Decimal("-1")),
        ("monthly_distance_km", True),
        ("monthly_distance_km", 1.5),
        ("monthly_distance_km", Decimal("NaN")),
        ("monthly_distance_km", Decimal("Infinity")),
        ("monthly_distance_km", Decimal("100000.01")),
        ("city_percentage", Decimal("-0.01")),
        ("city_percentage", Decimal("100.01")),
        ("highway_percentage", Decimal("-0.01")),
        ("highway_percentage", Decimal("100.01")),
    ],
)
def test_scenario_rejects_invalid_decimal_inputs(field, value):
    with pytest.raises(ValueError):
        scenario(**{field: value})


def test_scenario_requires_percentages_to_sum_exactly_one_hundred():
    with pytest.raises(ValueError, match="sum exactly to 100"):
        scenario(
            city_percentage=Decimal("49.99"),
            highway_percentage=Decimal("50.00"),
        )
    normalized = scenario(
        state_code="sp",
        vehicle_sks=(3, 1, 3),
        max_results=2,
    )
    assert normalized.state_code == "SP"
    assert normalized.vehicle_sks == (1, 3)


@pytest.mark.parametrize("horizon", [0, -1, 121, True])
def test_scenario_rejects_invalid_horizon(horizon):
    with pytest.raises(ValueError, match="horizon_months"):
        scenario(horizon_months=horizon)


@pytest.mark.parametrize(
    "field,value",
    [
        ("manual_fuel_price_brl", Decimal("0")),
        ("manual_fuel_price_brl", Decimal("-1")),
        ("manual_fuel_price_brl", Decimal("1.00001")),
        ("city_consumption_km_l", Decimal("0")),
        ("highway_consumption_km_l", Decimal("-1")),
        ("city_consumption_km_l", Decimal("NaN")),
    ],
)
def test_scenario_rejects_invalid_manual_price_and_efficiency(field, value):
    with pytest.raises(ValueError):
        scenario(**{field: value})


def test_manual_price_requires_an_explicit_single_fuel():
    with pytest.raises(ValueError, match="one explicitly selected fuel"):
        scenario(
            fuel_strategy=FuelStrategy.LOWEST_PROJECTED_COST,
            manual_fuel_price_brl=Decimal("5.0000"),
        )


@pytest.mark.parametrize(
    "city_pct,highway_pct,weighted,liters,monthly,difference,difference_pct",
    [
        ("100.00", "0.00", "12.0000", "83.3333", "500.0000", "50.0000", "11.11"),
        ("0.00", "100.00", "15.0000", "66.6667", "400.0000", "-50.0000", "-11.11"),
        ("50.00", "50.00", "13.3333", "75.0000", "450.0000", "0.0000", "0.00"),
    ],
)
def test_calculates_city_highway_and_mixed_profiles(
    city_pct,
    highway_pct,
    weighted,
    liters,
    monthly,
    difference,
    difference_pct,
):
    outcome = simulate_vehicle_costs(
        scenario(
            city_percentage=Decimal(city_pct),
            highway_percentage=Decimal(highway_pct),
        ),
        [evidence()],
    )
    result = outcome.results[0]
    assert result.weighted_consumption_km_l == Decimal(weighted)
    assert result.estimated_monthly_liters == Decimal(liters)
    assert result.estimated_annual_liters == (
        result.estimated_monthly_liters * Decimal("12")
    )
    assert result.monthly_fuel_cost_brl == Decimal(monthly)
    assert result.annual_fuel_cost_brl == result.monthly_fuel_cost_brl * Decimal("12")
    assert result.projected_horizon_cost_brl == result.monthly_fuel_cost_brl * Decimal(
        "12"
    )
    assert result.canonical_scenario_code == MIXED_1000_V1
    assert result.monthly_cost_difference_brl == Decimal(difference)
    assert result.monthly_cost_difference_percentage == Decimal(difference_pct)


def test_monthly_cost_uses_quantized_liters_times_price_without_float():
    result = simulate_vehicle_costs(
        scenario(
            monthly_distance_km=Decimal("1234.56"),
            city_percentage=Decimal("37.00"),
            highway_percentage=Decimal("63.00"),
        ),
        [evidence(price="6.1234", city="7.0000", highway="13.0000")],
    ).results[0]
    expected_liters = Decimal("1234.56") * (
        Decimal("0.37") / Decimal("7.0000")
        + Decimal("0.63") / Decimal("13.0000")
    )
    assert result.monthly_fuel_cost_brl == (
        expected_liters * Decimal("6.1234")
    ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def test_fixed_gasoline_and_ethanol_strategies_use_only_compatible_evidence():
    rows = [
        evidence(),
        evidence(
            fuel=FuelScenarioCode.ETHANOL_HYDRATED,
            price="3.6000",
            city="8.0000",
            highway="10.0000",
        ),
    ]
    gasoline = simulate_vehicle_costs(scenario(), rows).results[0]
    ethanol = simulate_vehicle_costs(
        scenario(fuel_strategy=FuelStrategy.ETHANOL_HYDRATED),
        rows,
    ).results[0]
    assert gasoline.fuel_code is FuelScenarioCode.GASOLINE_C_COMMON
    assert ethanol.fuel_code is FuelScenarioCode.ETHANOL_HYDRATED


def test_additized_gasoline_is_an_explicit_supported_fuel():
    result = simulate_vehicle_costs(
        scenario(fuel_strategy=FuelStrategy.GASOLINE_C_ADDITIZED),
        [
            evidence(
                fuel=FuelScenarioCode.GASOLINE_C_ADDITIZED,
                price="6.4000",
            )
        ],
    ).results[0]
    assert result.fuel_code is FuelScenarioCode.GASOLINE_C_ADDITIZED


def test_lowest_cost_evaluates_compatible_flex_fuels_and_selects_the_lower_cost():
    outcome = simulate_vehicle_costs(
        scenario(fuel_strategy=FuelStrategy.LOWEST_PROJECTED_COST),
        [
            evidence(),
            evidence(
                fuel=FuelScenarioCode.ETHANOL_HYDRATED,
                price="3.6000",
                city="8.0000",
                highway="10.0000",
            ),
        ],
    )
    assert outcome.results[0].fuel_code is FuelScenarioCode.ETHANOL_HYDRATED
    assert outcome.results[0].monthly_fuel_cost_brl == Decimal("405.0000")


def test_lowest_cost_fuel_tie_uses_the_documented_canonical_priority():
    outcome = simulate_vehicle_costs(
        scenario(fuel_strategy=FuelStrategy.LOWEST_PROJECTED_COST),
        [
            evidence(),
            evidence(
                fuel=FuelScenarioCode.ETHANOL_HYDRATED,
                price="4.0000",
                city="8.0000",
                highway="10.0000",
            ),
        ],
    )
    assert outcome.results[0].fuel_code is FuelScenarioCode.GASOLINE_C_COMMON


def test_incompatible_fuel_and_missing_exact_anp_evidence_are_auditable():
    incompatible = simulate_vehicle_costs(
        scenario(),
        [evidence(fuel=FuelScenarioCode.ETHANOL_HYDRATED)],
    )
    missing_price = simulate_vehicle_costs(
        scenario(state_code="RJ"),
        [evidence()],
    )
    assert incompatible.exclusions[0].reason_code == "FUEL_INCOMPATIBLE"
    assert missing_price.exclusions[0].reason_code == "ANP_EXACT_EVIDENCE_NOT_AVAILABLE"


def test_manual_price_and_efficiencies_are_request_scoped_and_do_not_require_anp_grain():
    outcome = simulate_vehicle_costs(
        scenario(
            monthly_distance_km=Decimal("2000.00"),
            city_percentage=Decimal("100.00"),
            highway_percentage=Decimal("0.00"),
            state_code="RJ",
            horizon_months=6,
            manual_fuel_price_brl=Decimal("5.0000"),
            city_consumption_km_l=Decimal("10.0000"),
            highway_consumption_km_l=Decimal("20.0000"),
        ),
        [evidence()],
    )
    result = outcome.results[0]
    assert result.estimated_monthly_liters == Decimal("200.0000")
    assert result.monthly_fuel_cost_brl == Decimal("1000.0000")
    assert result.projected_horizon_cost_brl == Decimal("6000.0000")
    assert result.fuel_price_origin.value == "user_input"
    assert result.city_consumption_origin.value == "user_input"
    assert result.highway_consumption_origin.value == "user_input"
    assert result.canonical_comparison_origin.value == "canonical_policy"
    assert result.anp_week_start is None
    assert result.monthly_cost_difference_brl == Decimal("550.0000")
    assert result.monthly_cost_difference_percentage == Decimal("122.22")


def test_missing_pbev_gold_and_unknown_selected_vehicle_are_auditable():
    outcome = simulate_vehicle_costs(
        scenario(vehicle_sks=(1, 2)),
        [],
        [PublishedVehicleExclusion(1, "PBEV_MATCHED_GOLD_NOT_AVAILABLE")],
    )
    assert [item.reason_code for item in outcome.exclusions] == [
        "PBEV_MATCHED_GOLD_NOT_AVAILABLE",
        "VEHICLE_NOT_IN_ACTIVE_INTEGRATED_GOLD",
    ]
    assert outcome.evaluated_vehicle_count == 2
    assert outcome.eligible_vehicle_count == 0


def test_ranking_tie_break_and_fingerprint_are_deterministic():
    rows = [
        evidence(vehicle_sk=2, brand="Volkswagen", model="Polo"),
        evidence(vehicle_sk=1, brand="Chevrolet", model="Onix"),
    ]
    requested = scenario(
        vehicle_sks=(2, 1),
        max_results=1,
        fuel_strategy=FuelStrategy.LOWEST_PROJECTED_COST,
    )
    first = simulate_vehicle_costs(requested, rows)
    second = simulate_vehicle_costs(requested, reversed(rows))
    assert first.results[0].vehicle_sk == 1
    assert first.results[0].rank == 1
    assert first.eligible_vehicle_count == 2
    assert first.returned_vehicle_count == 1
    assert first.fingerprint == second.fingerprint


def test_simulation_uses_decimal_and_preserves_the_historical_baseline_contract():
    source = inspect.getsource(simulation_module) + inspect.getsource(contracts_module)
    assert "float(" not in source
    outcome = simulate_vehicle_costs(scenario(), [evidence()])
    financial_values = (
        outcome.results[0].weighted_consumption_km_l,
        outcome.results[0].estimated_monthly_liters,
        outcome.results[0].estimated_annual_liters,
        outcome.results[0].monthly_fuel_cost_brl,
        outcome.results[0].annual_fuel_cost_brl,
        outcome.results[0].projected_horizon_cost_brl,
        outcome.results[0].monthly_cost_difference_brl,
        outcome.results[0].monthly_cost_difference_percentage,
        outcome.results[0].fuel_cost_per_km_brl,
    )
    assert all(isinstance(value, Decimal) for value in financial_values)
    assert MIXED_1000_V1 == "mixed_1000_v1"
    assert DEFAULT_DISTANCE_SCENARIO.scenario_code == MIXED_1000_V1
    assert SIMULATION_POLICY_VERSION != MIXED_1000_V1
    assert "mixed_1000_v1" not in source
    assert outcome.is_simulation is True
    assert outcome.simulation_only is True
    assert outcome.active_gold_unchanged is True
