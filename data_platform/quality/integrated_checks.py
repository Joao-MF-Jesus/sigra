"""Catalogo e validacoes puras da Gold analitica integrada."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from data_platform.contracts.integrated_vehicle_cost import (
    INTEGRATED_QUALITY_POLICY_VERSION,
    QualityExpectedStatus,
    QualityRuleContract,
    QualityRuleKind,
    QualitySeverity,
    SetReconciliation,
)


INTEGRATED_HARD_GATE_RULES = (
    "INTEGRATED_FIPE_SOURCE_AVAILABLE",
    "INTEGRATED_PBEV_SOURCE_AVAILABLE",
    "INTEGRATED_ANP_SOURCE_AVAILABLE",
    "INTEGRATED_SOURCE_FINGERPRINTS_MATCH",
    "INTEGRATED_SOURCE_DATASETS_IMMUTABLE",
    "INTEGRATED_POINT_IN_TIME_VALID",
    "INTEGRATED_NO_FUTURE_DATA",
    "INTEGRATED_EXACT_GEOGRAPHY_ONLY",
    "INTEGRATED_NATIONAL_GEOGRAPHY_BLOCKED",
    "INTEGRATED_ANP_COMMON_WEEK",
    "INTEGRATED_REQUIRED_PRODUCTS_PRESENT",
    "INTEGRATED_PBEV_MATCHED_ONLY",
    "INTEGRATED_CONSUMPTION_POSITIVE",
    "INTEGRATED_FUEL_PRICE_POSITIVE",
    "INTEGRATED_CURRENCY_BRL",
    "INTEGRATED_UNIT_LITER",
    "INTEGRATED_SCENARIO_POLICY",
    "INTEGRATED_DISTANCE_RECONCILED",
    "INTEGRATED_DECIMAL_ARITHMETIC",
    "INTEGRATED_GOLD_LINEAGE_COMPLETE",
    "INTEGRATED_SNAPSHOT_GRAIN_UNIQUE",
    "INTEGRATED_PROJECTION_GRAIN_UNIQUE",
    "INTEGRATED_FLEX_COMPARISON_RECONCILED",
    "INTEGRATED_COUNTS_RECONCILED",
    "INTEGRATED_VEHICLE_COVERAGE_RECONCILED",
    "INTEGRATED_SCENARIO_COVERAGE_RECONCILED",
    "INTEGRATED_COVERAGE_NON_REGRESSION",
    "INTEGRATED_SHADOW_ONLY",
    "INTEGRATED_NO_PARTIAL_PUBLICATION",
)

ANP_UNCALIBRATED_CONTROLS = (
    "ANP_MINIMUM_SAMPLE",
    "ANP_MINIMUM_ESTABLISHMENTS",
    "ANP_MUNICIPAL_COVERAGE",
    "ANP_MAXIMUM_FRESHNESS",
    "ANP_EXTREME_PRICE",
    "ANP_PRICE_DISPERSION",
    "ANP_WEEKLY_VOLUME_VARIATION",
)


@dataclass(frozen=True)
class QualityEvidence:
    quality_policy_version: str
    rule_code: str
    rule_kind: QualityRuleKind
    severity: QualitySeverity
    status: QualityExpectedStatus | str


@dataclass(frozen=True)
class IntegratedQualityDecision:
    passed: bool
    missing_or_invalid_rules: tuple[str, ...]


def build_integrated_quality_catalog(
    quality_policy_version: str = INTEGRATED_QUALITY_POLICY_VERSION,
) -> tuple[QualityRuleContract, ...]:
    hard_gates = tuple(
        QualityRuleContract(
            quality_policy_version=quality_policy_version,
            rule_code=rule_code,
            rule_kind=QualityRuleKind.HARD_GATE,
            severity=QualitySeverity.CRITICAL,
            required_for_activation=True,
            expected_status=QualityExpectedStatus.PASSED,
        )
        for rule_code in INTEGRATED_HARD_GATE_RULES
    )
    statistical_controls = tuple(
        QualityRuleContract(
            quality_policy_version=quality_policy_version,
            rule_code=rule_code,
            rule_kind=QualityRuleKind.STATISTICAL_CONTROL,
            severity=QualitySeverity.INFO,
            required_for_activation=True,
            expected_status=QualityExpectedStatus.NOT_CALIBRATED,
        )
        for rule_code in ANP_UNCALIBRATED_CONTROLS
    )
    return hard_gates + statistical_controls


def evaluate_policy_scoped_quality(
    *,
    quality_policy_version: str,
    evidence: Iterable[QualityEvidence],
    catalog: Iterable[QualityRuleContract] | None = None,
) -> IntegratedQualityDecision:
    rules = tuple(catalog or build_integrated_quality_catalog(quality_policy_version))
    evidence_by_identity: Mapping[tuple[str, str], QualityEvidence] = {
        (item.quality_policy_version, item.rule_code): item for item in evidence
    }
    failures: list[str] = []
    for rule in rules:
        if rule.quality_policy_version != quality_policy_version or not rule.required_for_activation:
            continue
        observed = evidence_by_identity.get((quality_policy_version, rule.rule_code))
        if (
            observed is None
            or observed.rule_kind is not rule.rule_kind
            or observed.severity is not rule.severity
            or str(observed.status) != str(rule.expected_status)
        ):
            failures.append(rule.rule_code)
    return IntegratedQualityDecision(
        passed=not failures,
        missing_or_invalid_rules=tuple(sorted(failures)),
    )


def reconcile_integrated_grains(
    *,
    expected_vehicles: Iterable[int],
    published_vehicles: Iterable[int],
    excluded_vehicles: Iterable[int],
    expected_scenarios: Iterable[tuple[object, ...]],
    published_scenarios: Iterable[tuple[object, ...]],
    excluded_scenarios: Iterable[tuple[object, ...]],
) -> tuple[SetReconciliation, SetReconciliation]:
    """Reconcilia chaves completas; contagens iguais nao mascaram chaves erradas."""
    return (
        SetReconciliation.build(
            expected=expected_vehicles,
            published=published_vehicles,
            excluded=excluded_vehicles,
        ),
        SetReconciliation.build(
            expected=expected_scenarios,
            published=published_scenarios,
            excluded=excluded_scenarios,
        ),
    )
