from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Mapping, Sequence

from data_platform.contracts.pbev import (
    PBEV_MATCHER_VERSION,
    PBEV_PARSER_VERSION,
    PBEV_SOURCE_SYSTEM,
    CoverageSlice,
    ExternalVehicleIdentity,
    ExternalVehicleMapping,
    MappingStatus,
    SourceCoverageReport,
)


TWO_PLACES = Decimal("0.01")
AUDITED_PILOT_COUNTS = {
    MappingStatus.MATCHED: 18,
    MappingStatus.AMBIGUOUS: 6,
    MappingStatus.REJECTED: 3,
    MappingStatus.NOT_FOUND: 3,
    MappingStatus.PENDING: 4,
}


def coverage_percentage(eligible: int, published: int) -> Decimal:
    if eligible <= 0:
        return Decimal("0.00")
    if published < 0 or published > eligible:
        raise ValueError("PBEV coverage counts are inconsistent")
    return (Decimal(published) * Decimal("100") / Decimal(eligible)).quantize(
        TWO_PLACES,
        rounding=ROUND_HALF_UP,
    )


def _slices(
    targets: Sequence[ExternalVehicleIdentity],
    mappings: Sequence[ExternalVehicleMapping],
    key,
) -> tuple[CoverageSlice, ...]:
    values: dict[str, list[int]] = {}
    for target, mapping in zip(targets, mappings, strict=True):
        bucket = str(key(target))
        counts = values.setdefault(bucket, [0, 0])
        counts[0] += 1
        counts[1] += mapping.mapping_status == MappingStatus.MATCHED
    return tuple(
        CoverageSlice(name, counts[0], counts[1], coverage_percentage(*counts))
        for name, counts in sorted(values.items())
    )


def build_coverage_report(
    *,
    dataset_version: str,
    asset_manifest: Sequence[Mapping[str, object]],
    targets: Sequence[ExternalVehicleIdentity],
    mappings: Sequence[ExternalVehicleMapping],
    field_coverage: Mapping[str, Mapping[str, object]],
    generated_at: datetime,
) -> SourceCoverageReport:
    if len(targets) != len(mappings):
        raise ValueError("every PBEV target must have exactly one current decision")
    counts = Counter(item.mapping_status for item in mappings)
    universe = len(targets)
    matched = counts[MappingStatus.MATCHED]
    if sum(counts.values()) != universe:
        raise ValueError("PBEV mapping states do not reconcile")
    reasons = Counter(item.decision_reason for item in mappings if item.mapping_status != MappingStatus.MATCHED)
    return SourceCoverageReport(
        source_system=PBEV_SOURCE_SYSTEM,
        dataset_version=dataset_version,
        asset_manifest=tuple(asset_manifest),
        universe_count=universe,
        eligible_count=universe,
        matched_count=matched,
        pending_count=counts[MappingStatus.PENDING],
        ambiguous_count=counts[MappingStatus.AMBIGUOUS],
        rejected_count=counts[MappingStatus.REJECTED],
        not_found_count=counts[MappingStatus.NOT_FOUND],
        published_count=matched,
        coverage_percentage=coverage_percentage(universe, matched),
        by_brand=_slices(targets, mappings, lambda item: item.brand_name),
        by_year=_slices(targets, mappings, lambda item: item.model_year),
        by_fuel=_slices(targets, mappings, lambda item: item.fuel_type),
        field_coverage=field_coverage,
        reason_counts=dict(sorted(reasons.items())),
        generated_at=generated_at,
        parser_version=PBEV_PARSER_VERSION,
        matcher_version=PBEV_MATCHER_VERSION,
    )


def enforce_audited_pilot_baseline(
    mappings: Iterable[ExternalVehicleMapping],
    *,
    baseline_applicable: bool,
) -> None:
    if not baseline_applicable:
        return
    decisions = tuple(mappings)
    counts = Counter(item.mapping_status for item in decisions)
    if sum(counts.values()) != 34:
        raise ValueError("audited PBEV pilot must classify exactly 34 targets")
    if counts[MappingStatus.MATCHED] < 18:
        raise ValueError("PBEV matched count regressed below the audited baseline")
    if counts[MappingStatus.MATCHED] == 18 and any(
        counts[status] != expected
        for status, expected in AUDITED_PILOT_COUNTS.items()
    ):
        raise ValueError("audited PBEV pilot classification differs from the approved baseline")
    additional_matches = counts[MappingStatus.MATCHED] - 18
    reviewed_manual_matches = sum(
        bool(item.reviewed_by and item.reviewed_at)
        for item in decisions
        if item.mapping_status == MappingStatus.MATCHED
        and item.match_method.value == "manual_review"
    )
    if additional_matches > reviewed_manual_matches:
        raise ValueError("PBEV increase above baseline requires recorded review evidence")


def validate_shadow_rows(
    mappings: Sequence[ExternalVehicleMapping],
    observation_vehicle_ids: Sequence[int],
) -> None:
    matched_ids = [item.vehicle_sk for item in mappings if item.mapping_status == MappingStatus.MATCHED]
    if not matched_ids:
        raise ValueError("empty PBEV Gold shadow is forbidden")
    if any(item is None for item in matched_ids):
        raise ValueError("matched PBEV mapping has incomplete lineage")
    if len(set(matched_ids)) != len(matched_ids):
        raise ValueError("duplicate vehicle_sk in PBEV Gold shadow")
    if sorted(matched_ids) != sorted(observation_vehicle_ids):
        raise ValueError("PBEV observations do not reconcile with matched mappings")
