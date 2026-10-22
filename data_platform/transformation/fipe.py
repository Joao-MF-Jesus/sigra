from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import unicodedata
from typing import Any

from data_platform.contracts.silver_fipe import (
    BronzeFipeInput,
    PriceHistoryDecision,
    SilverQualityIssue,
    SilverTransformCandidate,
    VehicleIdentityCandidate,
    VehiclePriceCandidate,
)
from data_platform.quality.silver_checks import quality_issue


FUEL_VOCABULARY = frozenset(
    {"gasoline", "ethanol", "flex", "diesel", "electric", "hybrid", "cng"}
)

_FUEL_ALIASES = {
    "gasoline": "gasoline",
    "gasolina": "gasoline",
    "ethanol": "ethanol",
    "etanol": "ethanol",
    "alcool": "ethanol",
    "flex": "flex",
    "flex fuel": "flex",
    "flexfuel": "flex",
    "gasolina/alcool": "flex",
    "gasolina/etanol": "flex",
    "diesel": "diesel",
    "electric": "electric",
    "eletrico": "electric",
    "hybrid": "hybrid",
    "hibrido": "hybrid",
    "cng": "cng",
    "gnv": "cng",
    "gas natural veicular": "cng",
}

_FUEL_ACRONYMS = {
    "G": "gasoline",
    "A": "ethanol",
    "F": "flex",
    "D": "diesel",
    "E": "electric",
    "H": "hybrid",
    "C": "cng",
    "GNV": "cng",
    "CNG": "cng",
}

_MONTHS = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}

_FIPE_CODE = re.compile(r"^[0-9]{6}-[0-9]$")
_YEAR_CODE = re.compile(r"^(?P<year>[0-9]{4,5})-(?P<suffix>[A-Za-z0-9]+)$")
_BRL_PRICE = re.compile(r"^R\$\s*(?P<amount>(?:[0-9]{1,3}(?:\.[0-9]{3})*|[0-9]+),[0-9]{2})$")
_REFERENCE_MONTH = re.compile(r"^(?P<month>[a-z]+)\s+de\s+(?P<year>[0-9]{4})$")

_STATUS_PRIORITY = {"matched": 0, "pending": 1, "ambiguous": 2, "rejected": 3}


def normalize_display(value: str) -> str:
    """Normaliza representacao sem remover acentos, caixa ou pontuacao."""
    return " ".join(unicodedata.normalize("NFKC", value).split())


def normalize_key_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(without_accents.casefold().split())


def build_canonical_key(
    *,
    vehicle_type: str,
    brand_name: str,
    model_name: str,
    version_name: str | None,
    model_year: int | None,
    is_zero_km: bool,
    fuel_type: str,
) -> str:
    if is_zero_km:
        year_identity: dict[str, Any] = {"kind": "zero_km"}
    elif model_year is None:
        year_identity = {"kind": "missing"}
    else:
        year_identity = {"kind": "model_year", "value": model_year}
    identity = {
        "brand": normalize_key_text(brand_name),
        "fuel": normalize_key_text(fuel_type),
        "model": normalize_key_text(model_name),
        "vehicle_type": normalize_key_text(vehicle_type),
        "version": normalize_key_text(version_name) if version_name is not None else None,
        "year": year_identity,
    }
    canonical = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def normalize_fuel(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = normalize_key_text(value)
    return _FUEL_ALIASES.get(normalized)


def normalize_fuel_acronym(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return _FUEL_ACRONYMS.get(normalize_display(value).upper())


def parse_brl_price(value: object) -> Decimal:
    if not isinstance(value, str):
        raise ValueError("FIPE price must be a BRL string")
    match = _BRL_PRICE.fullmatch(normalize_display(value))
    if match is None:
        raise ValueError("FIPE price is not in the expected BRL format")
    normalized = match.group("amount").replace(".", "").replace(",", ".")
    try:
        amount = Decimal(normalized).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError("FIPE price is not a valid decimal") from exc
    if amount <= 0:
        raise ValueError("FIPE price must be greater than zero")
    if amount >= Decimal("1000000000000"):
        raise ValueError("FIPE price exceeds NUMERIC(14,2)")
    return amount


def parse_reference_month(value: object) -> date:
    if not isinstance(value, str):
        raise ValueError("referenceMonth must be a string")
    normalized = normalize_key_text(value)
    match = _REFERENCE_MONTH.fullmatch(normalized)
    if match is None or match.group("month") not in _MONTHS:
        raise ValueError("referenceMonth is not a supported FIPE month")
    return date(int(match.group("year")), _MONTHS[match.group("month")], 1)


def decide_price_history(
    candidate: VehiclePriceCandidate,
    *,
    existing_price: Decimal | None = None,
    existing_currency: str | None = None,
    predecessor_exists: bool = False,
    successor_valid_from: datetime | None = None,
) -> PriceHistoryDecision:
    if existing_price is not None:
        if existing_price == candidate.price_amount and existing_currency == candidate.currency:
            return PriceHistoryDecision(action="idempotent")
        return PriceHistoryDecision(action="conflict")
    valid_from = datetime.combine(candidate.reference_month, time.min, tzinfo=UTC)
    return PriceHistoryDecision(
        action="insert",
        valid_from=valid_from,
        valid_to=successor_valid_from,
        is_current=successor_valid_from is None,
        close_predecessor=predecessor_exists,
    )


def parse_year_code(value: object) -> tuple[int | None, bool]:
    if not isinstance(value, str):
        raise ValueError("year_code must be a string")
    match = _YEAR_CODE.fullmatch(value)
    if match is None:
        raise ValueError("year_code must preserve year and fuel suffix")
    year = int(match.group("year"))
    if year == 32000:
        return None, True
    if not 1900 <= year <= 2100:
        raise ValueError("year_code model year is outside the supported range")
    return year, False


def _parse_model_year(value: object) -> tuple[int | None, bool]:
    if isinstance(value, bool):
        raise ValueError("modelYear cannot be boolean")
    if isinstance(value, int):
        year = value
    elif isinstance(value, str) and value.isdigit():
        year = int(value)
    else:
        raise ValueError("modelYear must be an integer")
    if year == 32000:
        return None, True
    if not 1900 <= year <= 2100:
        raise ValueError("modelYear is outside the supported range")
    return year, False


def _required_display(payload: dict[str, Any], field: str, maximum: int) -> tuple[str | None, str | None]:
    value = payload.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, "missing"
    if not isinstance(value, str):
        return None, "invalid"
    normalized = normalize_display(value)
    if not normalized or len(normalized) > maximum:
        return None, "invalid"
    return normalized, None


def _escalate(current: str, requested: str) -> str:
    return requested if _STATUS_PRIORITY[requested] > _STATUS_PRIORITY[current] else current


def transform_bronze_record(bronze: BronzeFipeInput) -> SilverTransformCandidate:
    issues: list[SilverQualityIssue] = []
    mapping_status = "matched"

    def add_issue(
        code: str,
        message: str,
        *,
        status: str | None = None,
        severity: str = "error",
        details: dict[str, Any] | None = None,
    ) -> None:
        nonlocal mapping_status
        issues.append(
            quality_issue(
                code,
                message,
                severity=severity,
                details=details,
            )
        )
        if status is not None:
            mapping_status = _escalate(mapping_status, status)

    if (
        bronze.ingestion_status != "received"
        or not 200 <= bronze.http_status < 300
        or bronze.payload is None
    ):
        add_issue(
            "INELIGIBLE_BRONZE_RECORD",
            "Only received 2xx Bronze JSON records can enter Silver",
            status="rejected",
        )

    payload = bronze.payload
    if not isinstance(payload, dict):
        add_issue(
            "UNEXPECTED_PAYLOAD",
            "FIPE payload must be a JSON object",
            status="rejected",
        )
        payload = {}

    if bronze.vehicle_type not in {"car", "motorcycle", "truck"}:
        add_issue(
            "INVALID_VEHICLE_TYPE",
            "Bronze vehicle type is outside the controlled vocabulary",
            status="rejected",
        )

    fipe_code_valid = bool(bronze.fipe_code and _FIPE_CODE.fullmatch(bronze.fipe_code))
    if not fipe_code_valid:
        add_issue(
            "INVALID_FIPE_CODE",
            "Bronze FIPE code is missing or invalid",
            status="rejected",
        )
    payload_fipe_code = payload.get("codeFipe")
    if payload_fipe_code is not None:
        if not isinstance(payload_fipe_code, str) or not _FIPE_CODE.fullmatch(payload_fipe_code):
            add_issue(
                "INVALID_PAYLOAD_FIPE_CODE",
                "Payload codeFipe is invalid",
                status="rejected",
            )
        elif bronze.fipe_code and payload_fipe_code != bronze.fipe_code:
            add_issue(
                "FIPE_CODE_CONFLICT",
                "Bronze and payload FIPE codes conflict",
                status="ambiguous",
                details={"bronze_code": bronze.fipe_code, "payload_code": payload_fipe_code},
            )

    source_vehicle_key: str | None = None
    if fipe_code_valid and bronze.year_code:
        source_vehicle_key = f"{bronze.fipe_code}:{bronze.year_code}"
        if bronze.source_record_key != source_vehicle_key:
            add_issue(
                "SOURCE_RECORD_KEY_CONFLICT",
                "Bronze source key conflicts with FIPE code and full year_code",
                status="ambiguous",
            )

    year_value: int | None = None
    is_zero_km = False
    try:
        year_value, is_zero_km = parse_year_code(bronze.year_code)
    except ValueError:
        add_issue(
            "INVALID_YEAR_CODE",
            "Bronze year_code is missing, invalid, or outside the supported range",
            status="rejected",
        )

    payload_year_value: int | None = None
    payload_zero_km = False
    if payload.get("modelYear") is None:
        add_issue(
            "MODEL_YEAR_MISSING",
            "Payload modelYear is required for cross-validation",
            status="pending",
        )
    else:
        try:
            payload_year_value, payload_zero_km = _parse_model_year(payload.get("modelYear"))
        except ValueError:
            add_issue(
                "INVALID_MODEL_YEAR",
                "Payload modelYear is invalid",
                status="rejected",
            )
        else:
            if (year_value, is_zero_km) != (payload_year_value, payload_zero_km):
                add_issue(
                    "MODEL_YEAR_CONFLICT",
                    "Payload modelYear conflicts with the preserved Bronze year_code",
                    status="ambiguous",
                )

    brand_name, brand_problem = _required_display(payload, "brand", 80)
    model_name, model_problem = _required_display(payload, "model", 120)
    for field, problem in (("brand", brand_problem), ("model", model_problem)):
        if problem == "missing":
            add_issue(
                "MISSING_IDENTITY_FIELD",
                f"Required identity field {field} is missing",
                status="pending",
                details={"field": field},
            )
        elif problem == "invalid":
            add_issue(
                "INVALID_IDENTITY_FIELD",
                f"Required identity field {field} has an invalid type or length",
                status="rejected",
                details={"field": field},
            )

    fuel_value = payload.get("fuel")
    fuel_type = normalize_fuel(fuel_value)
    if fuel_type is None:
        add_issue(
            "UNMAPPED_FUEL",
            "Payload fuel is missing or outside the controlled vocabulary",
            status="pending",
        )
    acronym_value = payload.get("fuelAcronym")
    acronym_fuel = normalize_fuel_acronym(acronym_value)
    if acronym_value is not None and acronym_fuel is None:
        add_issue(
            "UNMAPPED_FUEL_ACRONYM",
            "fuelAcronym could not be used for validation",
            severity="warning",
        )
    if fuel_type is not None and acronym_fuel is not None and fuel_type != acronym_fuel:
        add_issue(
            "FUEL_CONFLICT",
            "Payload fuel conflicts with its recognized fuelAcronym",
            status="ambiguous",
        )

    price_amount: Decimal | None = None
    try:
        price_amount = parse_brl_price(payload.get("price"))
    except ValueError:
        add_issue(
            "INVALID_PRICE",
            "Payload price must be positive BRL with two decimal places",
        )

    reference_month: date | None = None
    try:
        reference_month = parse_reference_month(payload.get("referenceMonth"))
    except ValueError:
        add_issue(
            "INVALID_REFERENCE_MONTH",
            "Payload referenceMonth cannot be converted safely",
        )
    if bronze.reference_month_raw is not None:
        try:
            bronze_reference = parse_reference_month(bronze.reference_month_raw)
        except ValueError:
            add_issue(
                "INVALID_BRONZE_REFERENCE_MONTH",
                "Bronze reference_month_raw cannot be converted safely",
            )
            reference_month = None
        else:
            if reference_month is not None and bronze_reference != reference_month:
                add_issue(
                    "REFERENCE_MONTH_CONFLICT",
                    "Bronze and payload reference months conflict",
                )
                reference_month = None

    identity: VehicleIdentityCandidate | None = None
    if (
        mapping_status == "matched"
        and brand_name is not None
        and model_name is not None
        and fuel_type is not None
        and (year_value is not None or is_zero_km)
    ):
        identity = VehicleIdentityCandidate(
            vehicle_type=bronze.vehicle_type,
            brand_name=brand_name,
            model_name=model_name,
            model_year=year_value,
            is_zero_km=is_zero_km,
            fuel_type=fuel_type,
            canonical_key=build_canonical_key(
                vehicle_type=bronze.vehicle_type,
                brand_name=brand_name,
                model_name=model_name,
                version_name=None,
                model_year=year_value,
                is_zero_km=is_zero_km,
                fuel_type=fuel_type,
            ),
        )

    price: VehiclePriceCandidate | None = None
    price_has_blocking_issue = any(
        item.rule_code
        in {
            "INVALID_PRICE",
            "INVALID_REFERENCE_MONTH",
            "INVALID_BRONZE_REFERENCE_MONTH",
            "REFERENCE_MONTH_CONFLICT",
        }
        for item in issues
    )
    if (
        mapping_status == "matched"
        and identity is not None
        and price_amount is not None
        and reference_month is not None
        and not price_has_blocking_issue
    ):
        price = VehiclePriceCandidate(
            price_amount=price_amount,
            currency="BRL",
            reference_month=reference_month,
        )

    review_notes = (
        "Automated evidence conflict; human review is required."
        if mapping_status == "ambiguous"
        else None
    )
    return SilverTransformCandidate(
        bronze=bronze,
        mapping_status=mapping_status,
        match_method="exact" if mapping_status == "matched" else None,
        confidence=Decimal("100.00") if mapping_status == "matched" else None,
        review_notes=review_notes,
        identity=identity,
        price=price,
        issues=tuple(issues),
        source_vehicle_key=source_vehicle_key,
    )
