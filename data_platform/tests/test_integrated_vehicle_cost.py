from __future__ import annotations

from dataclasses import fields
from datetime import date
from decimal import Decimal

import pytest

from data_platform.contracts.integrated_vehicle_cost import (
    CoverageRegressionStatus,
    ExclusionScope,
    FuelScenarioCode,
    INTEGRATED_QUALITY_POLICY_VERSION,
    IntegratedActivation,
    IntegratedActivationType,
    IntegratedDatasetIdentity,
    IntegratedExclusion,
    IntegratedProjectionGrain,
    IntegratedSnapshotGrain,
    MIXED_1000_V1,
    QualityExpectedStatus,
    calculate_projection,
    coverage_pct,
    coverage_regression_status,
)
from data_platform.quality.integrated_checks import (
    ANP_UNCALIBRATED_CONTROLS,
    INTEGRATED_HARD_GATE_RULES,
    QualityEvidence,
    build_integrated_quality_catalog,
    evaluate_policy_scoped_quality,
    reconcile_integrated_grains,
)


def _snapshot_grain() -> IntegratedSnapshotGrain:
    return IntegratedSnapshotGrain(
        dataset_version="integrated-v1",
        vehicle_sk=1,
        fuel_scenario_code=FuelScenarioCode.GASOLINE_C_COMMON,
        requested_geography_level="municipality",
        requested_geography_key="sao-paulo-sp",
        anp_week_start=date(2026, 8, 3),
    )


def test_integrated_identity_widths_and_grains_are_structurally_distinct():
    identity = IntegratedDatasetIdentity(
        dataset_version="x" * 96,
        fipe_source_dataset_version="f" * 80,
        pbev_source_dataset_version="p" * 80,
        anp_source_dataset_version="a" * 80,
    )
    assert len(identity.dataset_version) == 96
    assert "scenario_code" not in {field.name for field in fields(IntegratedSnapshotGrain)}
    projection = IntegratedProjectionGrain(snapshot=_snapshot_grain())
    assert projection.scenario_code == MIXED_1000_V1
    with pytest.raises(ValueError):
        IntegratedDatasetIdentity(
            dataset_version="x" * 97,
            fipe_source_dataset_version="fipe",
            pbev_source_dataset_version="pbev",
            anp_source_dataset_version="anp",
        )


def test_integrated_activation_accepts_only_canonical_types_and_predecessors():
    assert IntegratedActivation(
        dataset_version="integrated-v1",
        activation_type=IntegratedActivationType.PUBLISH,
        previous_dataset_version=None,
    ).activation_type is IntegratedActivationType.PUBLISH
    for activation_type in (
        IntegratedActivationType.REPLACE,
        IntegratedActivationType.ROLLBACK,
    ):
        assert IntegratedActivation(
            dataset_version="integrated-v2",
            activation_type=activation_type,
            previous_dataset_version="integrated-v1",
        ).previous_dataset_version == "integrated-v1"
        with pytest.raises(ValueError, match="require"):
            IntegratedActivation(
                dataset_version="integrated-v2",
                activation_type=activation_type,
                previous_dataset_version=None,
            )
    with pytest.raises(ValueError, match="no previous"):
        IntegratedActivation(
            dataset_version="integrated-v2",
            activation_type=IntegratedActivationType.PUBLISH,
            previous_dataset_version="integrated-v1",
        )
    with pytest.raises(ValueError):
        IntegratedActivationType("initial")
    with pytest.raises(ValueError):
        IntegratedActivationType("replacement")


def test_projection_uses_decimal_and_preserves_the_mixed_1000_policy():
    result = calculate_projection(
        fuel_price_per_liter_brl=Decimal("6.0000"),
        city_consumption_km_l=Decimal("10.0000"),
        highway_consumption_km_l=Decimal("15.0000"),
    )
    assert result.city_cost_per_km_brl == Decimal("0.60000000")
    assert result.highway_cost_per_km_brl == Decimal("0.40000000")
    assert result.mixed_cost_per_km_brl == Decimal("0.50000000")
    assert result.projected_monthly_cost_brl == Decimal("500.0000")
    assert result.projected_annual_cost_brl == Decimal("6000.0000")
    with pytest.raises(ValueError, match="Decimal"):
        calculate_projection(
            fuel_price_per_liter_brl=6.0,  # type: ignore[arg-type]
            city_consumption_km_l=Decimal("10"),
            highway_consumption_km_l=Decimal("15"),
        )


def test_exclusion_contract_separates_vehicle_and_scenario_grains():
    vehicle = IntegratedExclusion(
        dataset_version="integrated-v1",
        vehicle_sk=1,
        scope=ExclusionScope.VEHICLE,
    )
    assert vehicle.scenario_code is None
    scenario = IntegratedExclusion(
        dataset_version="integrated-v1",
        vehicle_sk=1,
        scope=ExclusionScope.SCENARIO,
        scenario_code=MIXED_1000_V1,
        fuel_scenario_code=FuelScenarioCode.ETHANOL_HYDRATED,
        requested_geography_level="municipality",
        requested_geography_key="sao-paulo-sp",
        anp_week_start=date(2026, 8, 3),
    )
    assert scenario.scenario_code == MIXED_1000_V1
    with pytest.raises(ValueError):
        IntegratedExclusion(
            dataset_version="integrated-v1",
            vehicle_sk=1,
            scope=ExclusionScope.VEHICLE,
            scenario_code=MIXED_1000_V1,
        )


def test_set_reconciliation_rejects_equal_counts_with_different_keys():
    vehicles, scenarios = reconcile_integrated_grains(
        expected_vehicles={1, 2},
        published_vehicles={1, 3},
        excluded_vehicles=set(),
        expected_scenarios={(1, MIXED_1000_V1), (2, MIXED_1000_V1)},
        published_scenarios={(1, MIXED_1000_V1), (3, MIXED_1000_V1)},
        excluded_scenarios=set(),
    )
    assert len(vehicles.expected) == len(vehicles.published) == 2
    assert vehicles.missing == frozenset({2})
    assert vehicles.unexpected == frozenset({3})
    assert scenarios.passed is False
    with pytest.raises(ValueError, match="disjoint"):
        reconcile_integrated_grains(
            expected_vehicles={1},
            published_vehicles={1},
            excluded_vehicles={1},
            expected_scenarios=set(),
            published_scenarios=set(),
            excluded_scenarios=set(),
        )


def test_snapshot_without_projection_is_not_published():
    vehicles, scenarios = reconcile_integrated_grains(
        expected_vehicles={1},
        published_vehicles=set(),
        excluded_vehicles=set(),
        expected_scenarios={(1, MIXED_1000_V1)},
        published_scenarios=set(),
        excluded_scenarios=set(),
    )
    assert vehicles.missing == frozenset({1})
    assert scenarios.missing == frozenset({(1, MIXED_1000_V1)})
    assert not vehicles.passed and not scenarios.passed


def test_quality_catalog_has_29_hard_gates_and_seven_uncalibrated_controls():
    catalog = build_integrated_quality_catalog()
    assert len(INTEGRATED_HARD_GATE_RULES) == 29
    assert len(ANP_UNCALIBRATED_CONTROLS) == 7
    assert len(catalog) == 36
    statistical = [rule for rule in catalog if rule.rule_code in ANP_UNCALIBRATED_CONTROLS]
    assert all(rule.expected_status is QualityExpectedStatus.NOT_CALIBRATED for rule in statistical)
    assert all(rule.required_for_activation for rule in catalog)


def test_quality_evidence_is_scoped_by_policy_and_requires_expected_status():
    catalog = build_integrated_quality_catalog()
    valid = [
        QualityEvidence(
            quality_policy_version=rule.quality_policy_version,
            rule_code=rule.rule_code,
            rule_kind=rule.rule_kind,
            severity=rule.severity,
            status=rule.expected_status,
        )
        for rule in catalog
    ]
    assert evaluate_policy_scoped_quality(
        quality_policy_version=INTEGRATED_QUALITY_POLICY_VERSION,
        evidence=valid,
        catalog=catalog,
    ).passed
    wrong_policy = [
        QualityEvidence(
            quality_policy_version="other-policy",
            rule_code=item.rule_code,
            rule_kind=item.rule_kind,
            severity=item.severity,
            status=item.status,
        )
        for item in valid
    ]
    decision = evaluate_policy_scoped_quality(
        quality_policy_version=INTEGRATED_QUALITY_POLICY_VERSION,
        evidence=wrong_policy,
        catalog=catalog,
    )
    assert not decision.passed
    assert len(decision.missing_or_invalid_rules) == 36
    missing_gate = evaluate_policy_scoped_quality(
        quality_policy_version=INTEGRATED_QUALITY_POLICY_VERSION,
        evidence=valid[1:],
        catalog=catalog,
    )
    assert not missing_gate.passed
    assert valid[0].rule_code in missing_gate.missing_or_invalid_rules


def test_coverage_is_decimal_and_regression_requires_manual_review():
    assert coverage_pct(18, 34) == Decimal("52.94")
    assert coverage_regression_status(
        catalog_coverage_pct=Decimal("52.94"),
        pbev_coverage_pct=Decimal("100.00"),
        baseline_catalog_coverage_pct=None,
        baseline_pbev_coverage_pct=None,
    ) is CoverageRegressionStatus.NOT_APPLICABLE
    assert coverage_regression_status(
        catalog_coverage_pct=Decimal("52.94"),
        pbev_coverage_pct=Decimal("99.99"),
        baseline_catalog_coverage_pct=Decimal("52.94"),
        baseline_pbev_coverage_pct=Decimal("100.00"),
    ) is CoverageRegressionStatus.MANUAL_REVIEW_REQUIRED
    assert "failed" not in {status.value for status in CoverageRegressionStatus}
