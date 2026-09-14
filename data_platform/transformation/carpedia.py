from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import hashlib
import json
import re
import unicodedata
from typing import Iterable, Mapping

from data_platform.contracts.carpedia_vehicle_specs import (
    CARPEDIA_CONTRACT_VERSION,
    CARPEDIA_MATCHER_VERSION,
    CARPEDIA_NORMALIZER_VERSION,
    CarpediaAttribute,
    CarpediaMappingDecision,
    CarpediaMappingStatus,
    CarpediaSpecification,
    ParsedCarpediaSpecification,
    VehicleIdentityCandidate,
)


_ATTRIBUTE_CODES = {
    "POTENCIA": "power",
    "POTENCIA MAXIMA MOTOR A COMBUSTAO": "power",
    "TORQUE": "torque",
    "TORQUE MAXIMO MOTOR A COMBUSTAO": "torque",
    "CILINDRADA": "engine_displacement",
    "MOTOR": "engine",
    "MOTORIZACAO": "engine",
    "COMBUSTIVEL": "fuel_type",
    "TRANSMISSAO": "transmission",
    "CAMBIO": "transmission",
    "CAMBIO TIPO": "transmission",
    "TRACAO": "drivetrain",
    "CARROCERIA": "body_style",
    "CARROCERIA CONFIGURACAO": "body_style",
    "PORTAS": "doors",
    "NUMERO DE PORTAS": "doors",
    "LUGARES": "seats",
    "NUMERO DE LUGARES": "seats",
    "ASSENTOS": "seats",
    "COMPRIMENTO": "length",
    "LARGURA": "width",
    "ALTURA": "height",
    "ENTRE EIXOS": "wheelbase",
    "DISTANCIA ENTRE EIXOS": "wheelbase",
    "PESO": "curb_weight",
    "CARGA UTIL": "payload_capacity",
    "PORTA MALAS": "cargo_capacity",
    "CAPACIDADE DO PORTA MALAS": "cargo_capacity",
    "VOLUME DO PORTA MALAS": "cargo_capacity",
    "CAPACIDADE DO TANQUE": "fuel_tank_capacity",
    "TANQUE": "fuel_tank_capacity",
    "TANQUE DE COMBUSTIVEL": "fuel_tank_capacity",
    "PNEUS": "tires",
}
_NUMERIC_ATTRIBUTES = frozenset({
    "power", "torque", "engine_displacement", "doors", "seats", "length",
    "width", "height", "wheelbase", "curb_weight", "payload_capacity", "cargo_capacity",
    "fuel_tank_capacity", "city_consumption", "highway_consumption", "range_km",
})
_UNIT_RULES = {
    "cv": ("kW", Decimal("0.73549875")),
    "hp": ("kW", Decimal("0.745699872")),
    "kw": ("kW", Decimal("1")),
    "kgfm": ("N_m", Decimal("9.80665")),
    "nm": ("N_m", Decimal("1")),
    "cm3": ("cm3", Decimal("1")),
    "cc": ("cm3", Decimal("1")),
    "mm": ("mm", Decimal("1")),
    "cm": ("mm", Decimal("10")),
    "m": ("mm", Decimal("1000")),
    "kg": ("kg", Decimal("1")),
    "l": ("L", Decimal("1")),
    "litros": ("L", Decimal("1")),
    "km/l": ("km_per_liter", Decimal("1")),
    "km": ("km", Decimal("1")),
}
_FUEL_CODES = {
    "GASOLINA": "gasoline",
    "ETANOL": "ethanol",
    "FLEX": "flex",
    "DIESEL": "diesel",
    "ELETRICO": "electric",
    "HIBRIDO": "hybrid",
    "GNV": "cng",
}


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    plain = "".join(character for character in decomposed if not unicodedata.combining(character))
    return " ".join(re.sub(r"[^a-zA-Z0-9]+", " ", plain).casefold().split())


def _code_text(value: str) -> str:
    return normalize_text(value).upper()


def _attribute_identity(section: str, label: str) -> tuple[str, str | None]:
    section_code = _code_text(section)
    label_code = _code_text(label)
    if section_code == "CONSUMO":
        if "CIDADE" in label_code or "URBANO" in label_code:
            return "city_consumption", None
        if "ESTRADA" in label_code or "RODOVIARIO" in label_code:
            return "highway_consumption", None
    if section_code == "AUTONOMIA":
        return "range_km", None
    known = _ATTRIBUTE_CODES.get(label_code)
    if known:
        return known, None
    suffix = re.search(r"\(([^()]*)\)\s*$", label)
    if suffix:
        base_code = _code_text(label[:suffix.start()])
        known = _ATTRIBUTE_CODES.get(base_code)
        if known:
            return known, suffix.group(1).strip() or None
    slug = "_".join(part for part in (normalize_text(section), normalize_text(label)) if part)
    return slug[:100] or "unclassified_attribute", None


def _attribute_code(section: str, label: str) -> str:
    return _attribute_identity(section, label)[0]


def _source_decimal(value: str) -> tuple[Decimal, int, str | None] | None:
    match = re.fullmatch(r"\s*(-?\d[\d.,]*)\s*([^\d\s].*)?\s*", value)
    if not match:
        return None
    number_text = match.group(1)
    unit = (match.group(2) or "").strip() or None
    if "," in number_text:
        normalized = number_text.replace(".", "").replace(",", ".")
        precision = len(number_text.rsplit(",", 1)[1])
    elif number_text.count(".") == 1 and len(number_text.rsplit(".", 1)[1]) == 3:
        normalized = number_text.replace(".", "")
        precision = 0
    else:
        normalized = number_text
        precision = len(number_text.rsplit(".", 1)[1]) if "." in number_text else 0
    try:
        parsed = Decimal(normalized)
    except InvalidOperation:
        return None
    if not parsed.is_finite():
        return None
    return parsed, precision, unit


def _unit_code(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = normalize_text(value).replace(" ", "")
    normalized = normalized.replace("m3", "m3")
    aliases = {
        "cv": "cv", "hp": "hp", "kw": "kw", "kgfm": "kgfm",
        "nm": "nm", "cm3": "cm3", "cm³": "cm3", "cc": "cc",
        "mm": "mm", "cm": "cm", "m": "m", "kg": "kg", "l": "l",
        "litro": "litros", "litros": "litros", "km/l": "km/l", "kml": "km/l",
        "km": "km",
    }
    return aliases.get(normalized)


def normalize_attribute(attribute: CarpediaAttribute) -> CarpediaAttribute:
    code, label_unit = _attribute_identity(attribute.source_section, attribute.source_label)
    if code not in _NUMERIC_ATTRIBUTES:
        return replace(
            attribute,
            attribute_code=code,
            normalized_value=" ".join(attribute.source_value.split()),
            unit_status="not_applicable",
            provenance={
                **attribute.provenance,
                "normalizer_version": CARPEDIA_NORMALIZER_VERSION,
                "source_value_preserved": True,
            },
        )
    parsed = _source_decimal(attribute.source_value)
    if parsed is None:
        return replace(
            attribute,
            attribute_code=code,
            unit_status="unrecognized",
            provenance={**attribute.provenance, "normalizer_version": CARPEDIA_NORMALIZER_VERSION},
        )
    value, precision, value_unit = parsed
    declared_unit = attribute.source_unit or label_unit
    value_unit_code = _unit_code(value_unit)
    declared_unit_code = _unit_code(declared_unit)
    if value_unit and declared_unit and value_unit_code != declared_unit_code:
        return replace(
            attribute,
            attribute_code=code,
            source_unit=value_unit,
            normalized_value=None,
            normalized_unit=None,
            precision=precision,
            unit_status="unrecognized",
            provenance={
                **attribute.provenance,
                "normalizer_version": CARPEDIA_NORMALIZER_VERSION,
                "unit_conflict": {"source_value": value_unit, "source_label": declared_unit},
            },
        )
    source_unit = value_unit or declared_unit
    if code in {"doors", "seats"} and source_unit is None:
        return replace(
            attribute,
            attribute_code=code,
            source_unit=None,
            normalized_value=value,
            normalized_unit="count",
            precision=precision,
            unit_status="recognized",
            provenance={**attribute.provenance, "normalizer_version": CARPEDIA_NORMALIZER_VERSION},
        )
    unit_code = _unit_code(source_unit)
    rule = _UNIT_RULES.get(unit_code or "")
    if rule is None:
        return replace(
            attribute,
            attribute_code=code,
            source_unit=source_unit,
            normalized_value=None,
            precision=precision,
            unit_status="unrecognized",
            provenance={**attribute.provenance, "normalizer_version": CARPEDIA_NORMALIZER_VERSION},
        )
    normalized_unit, multiplier = rule
    normalized_value = (value * multiplier).quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN)
    return replace(
        attribute,
        attribute_code=code,
        source_unit=source_unit,
        normalized_value=normalized_value,
        normalized_unit=normalized_unit,
        precision=precision,
        unit_status="recognized",
        provenance={
            **attribute.provenance,
            "normalizer_version": CARPEDIA_NORMALIZER_VERSION,
            "conversion_multiplier": str(multiplier),
            "unit_locator": "source_value" if value_unit else "source_label",
        },
    )


def normalize_attributes(
    parsed: ParsedCarpediaSpecification,
) -> tuple[CarpediaAttribute, ...]:
    return tuple(normalize_attribute(item) for item in parsed.attributes)


def _fuel_from_attributes(attributes: Iterable[CarpediaAttribute]) -> str | None:
    for item in attributes:
        if item.attribute_code == "fuel_type" and isinstance(item.normalized_value, str):
            normalized = _code_text(item.normalized_value)
            for source, target in _FUEL_CODES.items():
                if normalized == source:
                    return target
    return None


def _candidate_payload(candidate: VehicleIdentityCandidate) -> Mapping[str, object]:
    return {
        "vehicle_sk": candidate.vehicle_sk,
        "brand": candidate.brand_name,
        "model": candidate.model_name,
        "version": candidate.version_name,
        "model_year": candidate.model_year,
        "fuel_type": candidate.fuel_type,
    }


def match_vehicle_identity(
    parsed: ParsedCarpediaSpecification,
    attributes: Iterable[CarpediaAttribute],
    candidates: Iterable[VehicleIdentityCandidate],
) -> CarpediaMappingDecision:
    candidates = tuple(candidates)
    brand = normalize_text(parsed.brand_name)
    model = normalize_text(parsed.model_name)
    year = parsed.model_year
    source_version = normalize_text(parsed.version_name)
    fuel = _fuel_from_attributes(attributes)
    base = tuple(
        item for item in candidates
        if normalize_text(item.brand_name) == brand
        and normalize_text(item.model_name) == model
        and item.model_year == year
        and not item.is_zero_km
    )
    exact = []
    for item in base:
        candidate_version = normalize_text(
            f"{item.model_name} {item.version_name or ''}"
        )
        version_only = normalize_text(item.version_name)
        version_match = source_version in {candidate_version, version_only}
        fuel_match = fuel is None or fuel == item.fuel_type
        if version_match and fuel_match:
            exact.append(item)
    evidence = {
        "source": {
            "brand": parsed.brand_name,
            "model": parsed.model_name,
            "version": parsed.version_name,
            "model_year": year,
            "fuel_type": fuel,
        },
        "policy": "exact normalized identity only; no substring or fuzzy association",
        "matcher_version": CARPEDIA_MATCHER_VERSION,
    }
    candidate_evidence = tuple(_candidate_payload(item) for item in base)
    if len(exact) == 1:
        return CarpediaMappingDecision(
            CarpediaMappingStatus.MATCHED,
            "exact_identity",
            exact[0].vehicle_sk,
            Decimal("100.00"),
            False,
            evidence,
            candidate_evidence,
            "one Silver identity exactly matches brand, model, version, year and available fuel evidence",
        )
    if len(exact) > 1:
        return CarpediaMappingDecision(
            CarpediaMappingStatus.AMBIGUOUS,
            "multiple_exact",
            None,
            Decimal("100.00"),
            True,
            evidence,
            candidate_evidence,
            "multiple Silver identities satisfy the exact evidence",
        )
    if not base:
        return CarpediaMappingDecision(
            CarpediaMappingStatus.NOT_FOUND,
            "no_candidate",
            None,
            None,
            True,
            evidence,
            (),
            "no Silver identity has the same brand, model and model year",
        )
    if not source_version:
        return CarpediaMappingDecision(
            CarpediaMappingStatus.PENDING,
            "insufficient_evidence",
            None,
            None,
            True,
            evidence,
            candidate_evidence,
            "source version evidence is insufficient for exact association",
        )
    return CarpediaMappingDecision(
        CarpediaMappingStatus.REJECTED,
        "identity_conflict",
        None,
        None,
        True,
        evidence,
        candidate_evidence,
        "Silver candidates exist but version or fuel evidence conflicts",
    )


def build_specification(
    parsed: ParsedCarpediaSpecification,
    candidates: Iterable[VehicleIdentityCandidate],
) -> CarpediaSpecification:
    normalized = normalize_attributes(parsed)
    mapping = match_vehicle_identity(parsed, normalized, candidates)
    attributes: dict[str, object] = {}
    provenance: dict[str, object] = {}
    for item in normalized:
        payload = {
            "value": str(item.normalized_value) if isinstance(item.normalized_value, Decimal) else item.normalized_value,
            "unit": item.normalized_unit,
            "source_value": item.source_value,
            "source_unit": item.source_unit,
            "unit_status": item.unit_status,
            "precision": item.precision,
        }
        if item.attribute_code in attributes:
            current = attributes[item.attribute_code]
            attributes[item.attribute_code] = current + [payload] if isinstance(current, list) else [current, payload]
        else:
            attributes[item.attribute_code] = payload
        provenance[item.attribute_code] = {
            "source": parsed.source_name,
            "source_at": parsed.source_at,
            "section": item.source_section,
            "label": item.source_label,
            "policy": item.provenance,
        }
    normalized_payload = {
        "identity": mapping.identity_evidence,
        "mapping": {
            "status": mapping.status.value,
            "method": mapping.match_method,
            "vehicle_sk": mapping.vehicle_sk,
        },
        "attributes": attributes,
        "provenance": provenance,
        "contract_version": CARPEDIA_CONTRACT_VERSION,
        "normalizer_version": CARPEDIA_NORMALIZER_VERSION,
    }
    encoded = json.dumps(normalized_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    unrecognized = sum(item.unit_status == "unrecognized" for item in normalized)
    return CarpediaSpecification(
        parsed=replace(parsed, attributes=normalized),
        mapping=mapping,
        attributes=attributes,
        attribute_provenance=provenance,
        source_fingerprint=parsed.raw.row_hash,
        normalized_fingerprint=hashlib.sha256(encoded).hexdigest(),
        quality_status="warning" if unrecognized or mapping.status != CarpediaMappingStatus.MATCHED else "passed",
    )
