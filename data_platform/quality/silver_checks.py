from __future__ import annotations

from typing import Any, Mapping

from data_platform.common.logging import sanitize
from data_platform.contracts.silver_fipe import SilverQualityIssue


def quality_issue(
    rule_code: str,
    message: str,
    *,
    severity: str = "error",
    entity_name: str = "bronze.fipe_raw",
    details: Mapping[str, Any] | None = None,
) -> SilverQualityIssue:
    """Constroi evidencia Silver sem copiar payloads, URLs ou segredos."""
    safe_details = {
        str(key)[:80]: sanitize(value, limit=160)
        for key, value in (details or {}).items()
    }
    return SilverQualityIssue(
        rule_code=rule_code,
        severity=severity,
        message=sanitize(message),
        entity_name=entity_name,
        details=safe_details,
    )
