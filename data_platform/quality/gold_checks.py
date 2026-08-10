from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping

from data_platform.common.logging import sanitize


ZERO_COVERAGE = Decimal("0.00")
HUNDRED = Decimal("100")
TWO_PLACES = Decimal("0.01")


def calculate_coverage(expected_count: int, published_count: int) -> Decimal:
    if expected_count <= 0:
        return ZERO_COVERAGE
    if published_count < 0 or published_count > expected_count:
        raise ValueError("Gold publication counts are inconsistent")
    return (
        Decimal(published_count) * HUNDRED / Decimal(expected_count)
    ).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def classify_freshness(reference_month: date, *, as_of: date | None = None) -> str:
    comparison_date = as_of or date.today()
    age_days = (comparison_date - reference_month).days
    if age_days < 0:
        raise ValueError("Gold reference month cannot be in the future")
    if age_days <= 45:
        return "current"
    if age_days <= 90:
        return "stale"
    return "expired"


def effective_quality_status(base_quality_status: str, freshness_status: str) -> str:
    if base_quality_status not in {"passed", "warning"}:
        raise ValueError("Invalid Gold base quality status")
    if freshness_status not in {"current", "stale", "expired"}:
        raise ValueError("Invalid Gold freshness status")
    return (
        "passed"
        if base_quality_status == "passed" and freshness_status == "current"
        else "warning"
    )


def valid_reference_month(reference_month: date, *, as_of: date) -> bool:
    return reference_month.day == 1 and reference_month <= as_of


def issue_resolution_is_coherent(
    resolution_status: str,
    resolved_at: datetime | None,
) -> bool:
    if resolution_status == "open":
        return resolved_at is None
    if resolution_status in {"accepted", "resolved", "ignored"}:
        return resolved_at is not None
    return False


def safe_issue_details(details: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(key)[:80]: sanitize(value, limit=160)
        for key, value in details.items()
        if str(key).lower() not in {"payload", "endpoint", "url", "password", "token"}
    }
