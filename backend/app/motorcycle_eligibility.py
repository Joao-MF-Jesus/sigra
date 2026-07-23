from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping

from app.motorcycle_domain import (
    COMPLEMENTARY_SOURCE_GROUPS,
    PILOT_REQUIRED_SOURCE_GROUPS,
    MotorcycleDataGroup,
    MotorcycleEligibilityStatus,
    MotorcycleFutureReadiness,
)
from app.vehicle_domain import DataSource


SUPPORTED_CATEGORIES = {"scooter", "underbone", "street", "naked", "trail"}
MINIMUM_DISPLACEMENT_CC = 100
MAXIMUM_DISPLACEMENT_CC = 500
MINIMUM_MODEL_YEAR = 2018
MINIMUM_SOURCE_CONFIDENCE = 60
PILOT_REQUIRED_GROUPS = set(PILOT_REQUIRED_SOURCE_GROUPS)
COMPLEMENTARY_GROUPS = set(COMPLEMENTARY_SOURCE_GROUPS)

OBJECTIVE_COVERAGE_FIELDS = (
    ("brand", None),
    ("model", None),
    ("version", None),
    ("year", None),
    ("market_condition", None),
    ("price", None),
    ("price_reference_date", None),
    ("city_consumption", None),
    ("road_consumption", None),
    ("annual_maintenance_cost", None),
    ("engine_displacement_cc", "specifications"),
    ("motorcycle_category", "specifications"),
    ("power_cv", "specifications"),
    ("torque_nm", "specifications"),
    ("wet_weight_kg", "specifications"),
    ("seat_height_mm", "specifications"),
    ("tank_capacity_l", "specifications"),
    ("transmission_type", "specifications"),
    ("gear_count", "specifications"),
    ("final_drive_type", "specifications"),
    ("has_abs", "specifications"),
    ("has_cbs", "specifications"),
    ("has_traction_control", "specifications"),
)


def _read(record: Any, field: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(field, default)
    return getattr(record, field, default)


def _reason(code: str, field: str, message: str) -> dict[str, str]:
    return {"code": code, "field": field, "message": message}


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _coverage(record: Any, primary_by_group: dict[str, Any]) -> dict[str, Any]:
    specifications = _read(record, "specifications") or {}
    missing_objective_fields = []
    for field, container_name in OBJECTIVE_COVERAGE_FIELDS:
        container = specifications if container_name == "specifications" else record
        if _read(container, field) is None:
            prefix = "specifications." if container_name else ""
            missing_objective_fields.append(f"{prefix}{field}")
    missing_pilot_groups = sorted(PILOT_REQUIRED_GROUPS - set(primary_by_group))
    missing_complementary_groups = sorted(COMPLEMENTARY_GROUPS - set(primary_by_group))
    objective_total = len(OBJECTIVE_COVERAGE_FIELDS)
    pilot_total = len(PILOT_REQUIRED_GROUPS)
    complementary_total = len(COMPLEMENTARY_GROUPS)
    return {
        "motorcycle_id": _read(record, "id"),
        "objective_field_coverage_percent": round(
            100 * (objective_total - len(missing_objective_fields)) / objective_total,
            2,
        ),
        "pilot_required_source_coverage_percent": round(
            100 * (pilot_total - len(missing_pilot_groups)) / pilot_total,
            2,
        ),
        "pilot_required_source_groups": sorted(PILOT_REQUIRED_GROUPS),
        "missing_pilot_source_groups": missing_pilot_groups,
        "complementary_source_coverage_percent": round(
            100 * (complementary_total - len(missing_complementary_groups)) / complementary_total,
            2,
        ),
        "complementary_source_groups": sorted(COMPLEMENTARY_GROUPS),
        "missing_complementary_source_groups": missing_complementary_groups,
        "missing_objective_fields": missing_objective_fields,
        "future_recommendation_readiness": MotorcycleFutureReadiness.NOT_READY.value,
        "blocking_issues": [],
        "informational_issues": [],
    }


def _future_readiness(
    record: Any,
    *,
    status: MotorcycleEligibilityStatus,
    primary_by_group: dict[str, Any],
) -> MotorcycleFutureReadiness:
    if status == MotorcycleEligibilityStatus.DEMONSTRATION_ONLY:
        return MotorcycleFutureReadiness.DEMONSTRATION_ONLY
    if status == MotorcycleEligibilityStatus.INSUFFICIENT_CONFIDENCE:
        return MotorcycleFutureReadiness.INSUFFICIENT_SOURCE_CONFIDENCE
    if status != MotorcycleEligibilityStatus.ELIGIBLE:
        return MotorcycleFutureReadiness.NOT_READY

    economic_estimates = list(_read(record, "economic_estimates", []) or [])
    if (
        _read(record, "annual_maintenance_cost") is None
        or MotorcycleDataGroup.MAINTENANCE.value not in primary_by_group
        or not economic_estimates
    ):
        return MotorcycleFutureReadiness.MISSING_ECONOMIC_DATA

    derived_metrics = list(_read(record, "derived_metrics", []) or [])
    if not derived_metrics:
        return MotorcycleFutureReadiness.MISSING_METHODOLOGICAL_DATA
    return MotorcycleFutureReadiness.STRUCTURALLY_READY


def evaluate_motorcycle_eligibility(record: Any, *, today: date | None = None) -> dict[str, Any]:
    """Avalia somente prontidão estrutural; não calcula adequação, nota ou ranking."""
    today = today or datetime.now(timezone.utc).date()
    specifications = _read(record, "specifications") or {}
    sources = list(_read(record, "data_sources", []) or [])
    primary_by_group = {
        _read(source, "data_group"): source
        for source in sources
        if _read(source, "is_primary") is True
    }
    coverage = _coverage(record, primary_by_group)
    informational_issues = [
        _reason(
            "secondary_demonstration_source",
            f"data_sources.{_read(source, 'data_group')}",
            "Uma fonte complementar deste grupo é demonstrativa e não foi usada como referência principal.",
        )
        for source in sources
        if _read(source, "source_type") == DataSource.DEMONSTRATION.value
        and _read(source, "is_primary") is not True
    ]

    def result(status: MotorcycleEligibilityStatus, reasons: list[dict[str, str]]) -> dict[str, Any]:
        coverage["future_recommendation_readiness"] = _future_readiness(
            record,
            status=status,
            primary_by_group=primary_by_group,
        ).value
        coverage["blocking_issues"] = reasons
        coverage["informational_issues"] = informational_issues
        return {
            "eligibility_status": status.value,
            "eligibility_reasons": reasons,
            "blocking_issues": reasons,
            "informational_issues": informational_issues,
            "coverage": coverage,
        }

    demonstration_reasons = []
    if _read(record, "is_demonstration") is True:
        demonstration_reasons.append(
            _reason("demonstration_record", "is_demonstration", "O próprio registro está marcado como demonstrativo.")
        )
    if not sources and _read(record, "data_source") == DataSource.DEMONSTRATION.value:
        demonstration_reasons.append(
            _reason("legacy_demonstration_record", "data_source", "O registro legado está marcado como demonstrativo.")
        )
    for group in (
        MotorcycleDataGroup.IDENTITY.value,
        MotorcycleDataGroup.TECHNICAL_SPECS.value,
        MotorcycleDataGroup.MARKET_PRICE.value,
    ):
        source = primary_by_group.get(group)
        if source and _read(source, "source_type") == DataSource.DEMONSTRATION.value:
            demonstration_reasons.append(
                _reason(
                    "blocking_demonstration_source",
                    f"data_sources.{group}",
                    f"A fonte principal de {group} é demonstrativa.",
                )
            )
    if demonstration_reasons:
        return result(MotorcycleEligibilityStatus.DEMONSTRATION_ONLY, demonstration_reasons)

    category = _read(specifications, "motorcycle_category")
    if category not in SUPPORTED_CATEGORIES:
        return result(
            MotorcycleEligibilityStatus.UNSUPPORTED_CATEGORY,
            [
                _reason(
                    "unsupported_category",
                    "specifications.motorcycle_category",
                    "A categoria está fora do escopo inicial do MVP de motocicletas.",
                )
            ],
        )

    domain_reasons = []
    displacement = _read(specifications, "engine_displacement_cc")
    if not isinstance(displacement, (int, float)) or not MINIMUM_DISPLACEMENT_CC <= displacement <= MAXIMUM_DISPLACEMENT_CC:
        domain_reasons.append(
            _reason(
                "unsupported_displacement",
                "specifications.engine_displacement_cc",
                "A cilindrada está fora da faixa estrutural de 100 a 500 cm³ do MVP.",
            )
        )
    year = _read(record, "year")
    if not isinstance(year, int) or not MINIMUM_MODEL_YEAR <= year <= today.year + 1:
        domain_reasons.append(
            _reason("unsupported_year", "year", f"O MVP estrutural considera modelos de {MINIMUM_MODEL_YEAR} em diante.")
        )
    if domain_reasons:
        return result(MotorcycleEligibilityStatus.EXCLUDED_BY_DOMAIN_RULE, domain_reasons)

    missing_reasons = []
    required_fields = (
        (record, "market_condition", "missing_market_condition", "A situação nova ou usada ainda não foi informada."),
        (record, "price_reference_date", "missing_price_reference_date", "A data de referência do preço ainda não foi informada."),
        (specifications, "power_cv", "missing_power", "A potência é necessária para os futuros guardrails de experiência."),
        (specifications, "transmission_type", "missing_transmission", "O tipo de transmissão ainda não foi informado."),
        (specifications, "final_drive_type", "missing_final_drive", "A transmissão final ainda não foi informada."),
    )
    for container, field, code, message in required_fields:
        if _read(container, field) is None:
            prefix = "specifications." if container is specifications else ""
            missing_reasons.append(_reason(code, f"{prefix}{field}", message))

    for group in sorted(PILOT_REQUIRED_GROUPS):
        if group not in primary_by_group:
            missing_reasons.append(
                _reason(
                    "missing_primary_source",
                    f"data_sources.{group}",
                    f"O grupo {group} ainda não possui uma fonte principal auditável.",
                )
            )
    if missing_reasons:
        return result(MotorcycleEligibilityStatus.INCOMPLETE, missing_reasons)

    outdated_reasons = []
    freshness_days = {
        MotorcycleDataGroup.MARKET_PRICE.value: 548,
        MotorcycleDataGroup.TECHNICAL_SPECS.value: 1825,
    }
    for group, maximum_age_days in freshness_days.items():
        source = primary_by_group[group]
        reference_date = _parse_date(_read(source, "reference_date")) or _parse_date(_read(source, "last_verified_at"))
        if reference_date is None or (today - reference_date).days > maximum_age_days:
            outdated_reasons.append(
                _reason(
                    "outdated_or_undated_source",
                    f"data_sources.{group}.reference_date",
                    f"A fonte principal de {group} está sem referência temporal atual.",
                )
            )
    if outdated_reasons:
        return result(MotorcycleEligibilityStatus.OUTDATED_DATA, outdated_reasons)

    confidence_reasons = []
    for group in sorted(PILOT_REQUIRED_GROUPS):
        confidence = _read(primary_by_group[group], "confidence")
        if not isinstance(confidence, (int, float)) or confidence < MINIMUM_SOURCE_CONFIDENCE:
            confidence_reasons.append(
                _reason(
                    "insufficient_source_confidence",
                    f"data_sources.{group}.confidence",
                    f"A confiança da fonte principal de {group} é insuficiente para avaliação futura.",
                )
            )
    if confidence_reasons:
        return result(MotorcycleEligibilityStatus.INSUFFICIENT_CONFIDENCE, confidence_reasons)

    return result(MotorcycleEligibilityStatus.ELIGIBLE, [])
