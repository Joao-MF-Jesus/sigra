from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_EVEN
import hashlib
import json
from typing import Iterable, Sequence

from data_platform.contracts.anp_fuel_prices import (
    ANP_REQUIRED_PRODUCTS,
    AnpFuelPriceObservation,
    AnpFuelPriceSnapshot,
    AnpQualityIssue,
    AnpQualityResult,
)


_FOUR_PLACES = Decimal("0.0001")
_NON_CALIBRATED_RULES = (
    "ANP_MINIMUM_SAMPLE",
    "ANP_MINIMUM_ESTABLISHMENTS",
    "ANP_MUNICIPAL_COVERAGE",
    "ANP_MAXIMUM_FRESHNESS",
    "ANP_EXTREME_PRICE",
    "ANP_PRICE_DISPERSION",
    "ANP_WEEKLY_VOLUME_VARIATION",
)


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_FOUR_PLACES, rounding=ROUND_HALF_EVEN)


def percentile(values: Sequence[Decimal], fraction: Decimal) -> Decimal:
    if not values:
        raise ValueError("percentile requires at least one Decimal value")
    if not Decimal("0") <= fraction <= Decimal("1"):
        raise ValueError("percentile fraction is outside [0, 1]")
    ordered = sorted(values)
    if len(ordered) == 1:
        return _quantize(ordered[0])
    position = Decimal(len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - Decimal(lower)
    return _quantize(ordered[lower] + (ordered[upper] - ordered[lower]) * weight)


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def build_snapshots(
    observations: Sequence[AnpFuelPriceObservation],
    *,
    reference_period_end,
) -> tuple[AnpFuelPriceSnapshot, ...]:
    if not observations:
        raise ValueError("empty ANP Gold shadow is forbidden")
    groups: dict[tuple[str, object, str, str], list[AnpFuelPriceObservation]] = defaultdict(list)
    for item in observations:
        groups[(item.product_code.value, item.week_start, "municipality", f"{item.state_code}:{item.municipality_normalized}")].append(item)
        groups[(item.product_code.value, item.week_start, "state", item.state_code)].append(item)
    snapshots = []
    for (product, week_start, level, key), rows in sorted(groups.items(), key=lambda item: tuple(str(value) for value in item[0])):
        values = [item.sale_price for item in rows]
        p25 = percentile(values, Decimal("0.25"))
        median = percentile(values, Decimal("0.50"))
        p75 = percentile(values, Decimal("0.75"))
        last_collection = max(item.collection_date for item in rows)
        freshness = (reference_period_end - last_collection).days
        if freshness < 0:
            raise ValueError("ANP collection date exceeds the reference period")
        payload = {
            "product": product,
            "week_start": week_start.isoformat(),
            "level": level,
            "key": key,
            "prices": [str(value) for value in sorted(values)],
            "establishments": sorted({item.establishment_key for item in rows}),
            "last_collection": last_collection.isoformat(),
        }
        snapshots.append(
            AnpFuelPriceSnapshot(
                product_code=rows[0].product_code,
                week_start=week_start,
                week_end=rows[0].week_end,
                geography_level=level,
                geography_key=key,
                municipality_name=min(item.municipality_name for item in rows) if level == "municipality" else None,
                state_code=rows[0].state_code,
                mean_price=_quantize(sum(values, Decimal("0")) / Decimal(len(values))),
                median_price=median,
                minimum_price=_quantize(min(values)),
                maximum_price=_quantize(max(values)),
                percentile_25=p25,
                percentile_75=p75,
                interquartile_range=_quantize(p75 - p25),
                observation_count=len(rows),
                establishment_count=len({item.establishment_key for item in rows}),
                last_collection_date=last_collection,
                freshness_days=freshness,
                sampling_status="not_calibrated",
                dispersion_status="not_calibrated",
                quality_status="passed",
                snapshot_fingerprint=_fingerprint(payload),
            )
        )
    return tuple(snapshots)


def evaluate_quality(
    observations: Sequence[AnpFuelPriceObservation],
    snapshots: Sequence[AnpFuelPriceSnapshot],
    issues: Iterable[AnpQualityIssue],
) -> tuple[AnpQualityResult, ...]:
    issue_list = tuple(issues)
    critical = sum(item.severity == "critical" for item in issue_list)
    hard_passed = bool(observations and snapshots and not critical)
    observed_products = frozenset(item.product_code for item in observations)
    required_products_present = ANP_REQUIRED_PRODUCTS.issubset(observed_products)
    results = [
        AnpQualityResult(
            rule_code="ANP_SHADOW_HARD_GATES",
            severity="critical",
            status="passed" if hard_passed else "failed",
            observed_value={
                "observation_count": len(observations),
                "snapshot_count": len(snapshots),
                "critical_issue_count": critical,
                "publication_mode": "shadow",
                "storage_mode": "metadata_only",
            },
            expected_condition="non-empty lineage, deterministic snapshots, no critical issue, shadow and metadata_only",
        ),
        AnpQualityResult(
            rule_code="ANP_REQUIRED_PRODUCTS_PRESENT",
            severity="critical",
            status="passed" if required_products_present else "failed",
            observed_value={
                "product_codes": sorted(item.value for item in observed_products),
            },
            expected_condition=(
                "products include gasoline_c_common and ethanol_hydrated"
            ),
        ),
    ]
    results.extend(
        AnpQualityResult(
            rule_code=rule,
            severity="info",
            status="not_calibrated",
            observed_value={},
            expected_condition="threshold requires evidence from the PostgreSQL pilot",
        )
        for rule in _NON_CALIBRATED_RULES
    )
    return tuple(results)


def require_hard_gates(results: Sequence[AnpQualityResult]) -> None:
    if any(item.severity == "critical" and item.status != "passed" for item in results):
        raise ValueError("ANP Gold shadow hard gates failed")
