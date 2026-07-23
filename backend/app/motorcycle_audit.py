from __future__ import annotations

import math
import re
from datetime import date, datetime
from decimal import Decimal
from numbers import Number
from typing import Any, Mapping
from urllib.parse import urlparse

from app.motorcycle_domain import (
    MotorcycleFinalDriveType,
    MotorcycleFuelType,
    MotorcycleMarketCondition,
    MotorcycleTransmissionType,
)
from app.vehicle_domain import DataSource, MotorcycleCategory, VehicleType


EMAIL_PATTERN = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")


def _read(record: Any, field: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(field, default)
    return getattr(record, field, default)


def _issue(issues: list[dict[str, str]], field: str, code: str, message: str) -> None:
    issues.append({"field": field, "code": code, "message": message})


def _required_text(
    record: Any,
    field: str,
    label: str,
    issues: list[dict[str, str]],
    *,
    minimum_length: int,
    maximum_length: int,
) -> None:
    value = _read(record, field)
    if not isinstance(value, str) or not minimum_length <= len(value.strip()) <= maximum_length:
        _issue(
            issues,
            field,
            "missing_or_invalid",
            f"{label} deve ser um texto entre {minimum_length} e {maximum_length} caracteres.",
        )


def _numeric(
    record: Any,
    field: str,
    label: str,
    issues: list[dict[str, str]],
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    minimum_exclusive: bool = False,
    optional: bool = False,
) -> None:
    value = _read(record, field)
    if optional and value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (Number, Decimal)):
        _issue(issues, field, "invalid_type", f"{label} deve ser numérico.")
        return
    numeric_value = float(value)
    if not math.isfinite(numeric_value):
        _issue(issues, field, "not_finite", f"{label} deve ser um valor finito.")
        return
    if minimum is not None:
        invalid_minimum = numeric_value <= minimum if minimum_exclusive else numeric_value < minimum
        if invalid_minimum:
            comparison = "maior que" if minimum_exclusive else "maior ou igual a"
            _issue(issues, field, "out_of_range", f"{label} deve ser {comparison} {minimum}.")
    if maximum is not None and numeric_value > maximum:
        _issue(issues, field, "out_of_range", f"{label} deve ser menor ou igual a {maximum}.")


def _enum_value(
    record: Any,
    field: str,
    label: str,
    allowed: set[str],
    issues: list[dict[str, str]],
) -> None:
    value = _read(record, field)
    if hasattr(value, "value"):
        value = value.value
    if value not in allowed:
        _issue(issues, field, "invalid_value", f"{label} possui um valor não reconhecido.")


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if "T" not in normalized and " " not in normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _validate_optional_datetime(record: Any, field: str, label: str, issues: list[dict[str, str]]) -> datetime | None:
    value = _read(record, field)
    if value is None:
        return None
    parsed = _parse_datetime(value)
    if parsed is None:
        _issue(issues, field, "invalid_date", f"{label} deve usar uma data e hora válida.")
    return parsed


def _validate_optional_date(record: Any, field: str, label: str, issues: list[dict[str, str]]) -> date | None:
    value = _read(record, field)
    if value is None:
        return None
    parsed = _parse_date(value)
    if parsed is None:
        _issue(issues, field, "invalid_date", f"{label} deve usar uma data válida.")
    return parsed


def _audit_specifications(specifications: Any, issues: list[dict[str, str]]) -> bool:
    if specifications is None:
        _issue(
            issues,
            "specifications",
            "missing_relationship",
            "As especificações técnicas da motocicleta estão ausentes.",
        )
        return False

    initial_issue_count = len(issues)
    prefix = "specifications."
    _numeric(specifications, "engine_displacement_cc", "A cilindrada", issues, minimum=0, maximum=3000, minimum_exclusive=True)
    _enum_value(
        specifications,
        "motorcycle_category",
        "A categoria",
        {item.value for item in MotorcycleCategory},
        issues,
    )
    _numeric(specifications, "wet_weight_kg", "O peso em ordem de marcha", issues, minimum=20, maximum=600)
    _numeric(specifications, "seat_height_mm", "A altura do assento", issues, minimum=400, maximum=1200)
    _numeric(specifications, "tank_capacity_l", "A capacidade do tanque", issues, minimum=1, maximum=50)

    has_abs = _read(specifications, "has_abs")
    if not isinstance(has_abs, bool) and has_abs not in (0, 1):
        _issue(issues, f"{prefix}has_abs", "invalid_type", "A presença de ABS deve ser booleana.")

    for field, label, maximum in (
        ("power_cv", "A potência", None),
        ("torque_nm", "O torque", None),
        ("payload_capacity_kg", "A capacidade de carga", None),
        ("oil_change_interval_km", "O intervalo de troca de óleo", None),
        ("gear_count", "A quantidade de marchas", 12),
        ("abs_channels", "A quantidade de canais do ABS", 2),
    ):
        _numeric(
            specifications,
            field,
            label,
            issues,
            minimum=0,
            maximum=maximum,
            minimum_exclusive=field != "abs_channels",
            optional=True,
        )
    for field, label, allowed in (
        ("transmission_type", "O tipo de transmissão", {item.value for item in MotorcycleTransmissionType}),
        ("final_drive_type", "A transmissão final", {item.value for item in MotorcycleFinalDriveType}),
    ):
        if _read(specifications, field) is not None:
            _enum_value(specifications, field, label, allowed, issues)
    for field, label in (
        ("has_cbs", "A presença de CBS"),
        ("has_traction_control", "A presença de controle de tração"),
    ):
        value = _read(specifications, field)
        if value is not None and not isinstance(value, bool) and value not in (0, 1):
            _issue(issues, field, "invalid_type", f"{label} deve ser booleana quando informada.")
    for issue in issues[initial_issue_count:]:
        if not issue["field"].startswith(prefix):
            issue["field"] = f"{prefix}{issue['field']}"
    return True


def audit_motorcycle_record(motorcycle: Any) -> dict[str, Any]:
    """Audita um registro persistido sem alterar, completar ou normalizar seus dados."""
    issues: list[dict[str, str]] = []
    grouped_sources = list(_read(motorcycle, "data_sources", []) or [])

    identifier = _read(motorcycle, "id")
    if isinstance(identifier, bool) or not isinstance(identifier, int) or identifier <= 0:
        _issue(issues, "id", "invalid_value", "O identificador deve ser um inteiro positivo.")

    _required_text(motorcycle, "brand", "A marca", issues, minimum_length=2, maximum_length=80)
    _required_text(motorcycle, "model", "O modelo", issues, minimum_length=1, maximum_length=120)
    image_url = _read(motorcycle, "image_url")
    if not isinstance(image_url, str) or len(image_url) > 240:
        _issue(issues, "image_url", "invalid_type", "A imagem deve ser informada como texto, ainda que vazio.")

    year = _read(motorcycle, "year")
    if isinstance(year, bool) or not isinstance(year, int) or not 1990 <= year <= 2035:
        _issue(issues, "year", "out_of_range", "O ano deve estar entre 1990 e 2035.")

    for field, label, minimum, maximum, exclusive in (
        ("price", "O preço", 0, None, True),
        ("city_consumption", "O consumo urbano", 0, None, True),
        ("road_consumption", "O consumo rodoviário", 0, None, True),
        ("annual_maintenance_cost", "A manutenção anual", 0, None, False),
    ):
        _numeric(
            motorcycle,
            field,
            label,
            issues,
            minimum=minimum,
            maximum=maximum,
            minimum_exclusive=exclusive,
            optional=field == "annual_maintenance_cost",
        )
    _numeric(
        motorcycle,
        "data_confidence",
        "A confiança legada dos dados",
        issues,
        minimum=0,
        maximum=100,
        optional=True,
    )

    for field, label, minimum, maximum in (
        ("reliability_score", "A confiabilidade legada", 0, 100),
        ("parts_availability_score", "A disponibilidade de peças legada", 0, 100),
        ("depreciation_rate", "A depreciação", 0, None),
    ):
        _numeric(motorcycle, field, label, issues, minimum=minimum, maximum=maximum, optional=True)

    for field, label, allowed in (
        ("market_condition", "A situação de mercado", {item.value for item in MotorcycleMarketCondition}),
        ("fuel_type", "O combustível", {item.value for item in MotorcycleFuelType}),
    ):
        if _read(motorcycle, field) is not None:
            _enum_value(motorcycle, field, label, allowed, issues)
    _validate_optional_date(motorcycle, "price_reference_date", "A data de referência do preço", issues)

    _enum_value(
        motorcycle,
        "vehicle_type",
        "O tipo de veículo",
        {VehicleType.MOTORCYCLE.value},
        issues,
    )
    if _read(motorcycle, "data_source") is not None:
        _enum_value(
            motorcycle,
            "data_source",
            "A origem legada dos dados",
            {item.value for item in DataSource},
            issues,
        )
    elif not grouped_sources:
        _issue(
            issues,
            "data_sources",
            "missing_traceability",
            "O registro não possui fonte agrupada nem metadado legado de origem.",
        )

    # SQLite persists booleans as integers; external payloads remain protected by
    # StrictBool in the Pydantic schema before they reach this persistence audit.
    demonstration_value = _read(motorcycle, "is_demonstration", False)
    if not (
        isinstance(demonstration_value, bool)
        or type(demonstration_value) is int
        and demonstration_value in {0, 1}
    ):
        _issue(issues, "is_demonstration", "invalid_type", "A marcação demonstrativa deve ser booleana.")

    source_url = _read(motorcycle, "source_url")
    for field, maximum in (("source_name", 160), ("source_reference", 240)):
        value = _read(motorcycle, field)
        if value is not None and (not isinstance(value, str) or not 2 <= len(value.strip()) <= maximum):
            _issue(issues, field, "invalid_type", f"{field} deve ser texto válido quando informado.")
    if source_url is not None:
        if not isinstance(source_url, str) or len(source_url) > 500:
            _issue(issues, "source_url", "invalid_type", "A URL da fonte deve ser textual.")
        else:
            parsed_url = urlparse(source_url)
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                _issue(issues, "source_url", "invalid_url", "A URL da fonte deve ser HTTP ou HTTPS válida.")

    collected_at = _validate_optional_datetime(
        motorcycle,
        "source_collected_at",
        "A data de coleta",
        issues,
    )
    _validate_optional_date(motorcycle, "source_reference_date", "A data de referência", issues)
    verified_at = _validate_optional_datetime(
        motorcycle,
        "last_verified_at",
        "A data da última verificação",
        issues,
    )
    if collected_at is not None and verified_at is not None:
        collected_comparable = collected_at.replace(tzinfo=None)
        verified_comparable = verified_at.replace(tzinfo=None)
        if verified_comparable < collected_comparable:
            _issue(
                issues,
                "last_verified_at",
                "inconsistent_date",
                "A última verificação não pode ser anterior à coleta.",
            )

    data_source = _read(motorcycle, "data_source")
    if hasattr(data_source, "value"):
        data_source = data_source.value
    source_name = _read(motorcycle, "source_name")
    source_reference = _read(motorcycle, "source_reference")
    if data_source == DataSource.OFFICIAL.value:
        if not isinstance(source_name, str) or not source_name.strip():
            _issue(issues, "source_name", "missing_source_identification", "Dados oficiais exigem a identificação da fonte.")
        if not ((isinstance(source_reference, str) and source_reference.strip()) or source_url):
            _issue(issues, "source_reference", "missing_source_reference", "Dados oficiais exigem referência ou URL da fonte.")
        if collected_at is None:
            _issue(issues, "source_collected_at", "missing_source_date", "Dados oficiais exigem data de coleta.")
    elif data_source == DataSource.ESTIMATED.value:
        if not isinstance(source_reference, str) or not source_reference.strip():
            _issue(issues, "source_reference", "missing_estimation_method", "Dados estimados exigem método ou referência.")
    elif data_source == DataSource.USER_REPORTED.value:
        if collected_at is None:
            _issue(issues, "source_collected_at", "missing_source_date", "Dados relatados exigem data de coleta.")
        for field, value in (("source_name", source_name), ("source_reference", source_reference)):
            if isinstance(value, str) and EMAIL_PATTERN.search(value):
                _issue(issues, field, "personal_data_exposed", "Metadados de relatos não devem expor endereço de e-mail.")

    specifications_present = _audit_specifications(_read(motorcycle, "specifications"), issues)
    missing_codes = {"missing_or_invalid", "missing_relationship", "missing_traceability", "missing_source_identification", "missing_source_reference", "missing_source_date", "missing_estimation_method"}
    is_complete = specifications_present and not any(issue["code"] in missing_codes for issue in issues)
    return {"is_valid": not issues, "is_complete": is_complete, "issues": issues}
