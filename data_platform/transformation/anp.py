from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import unicodedata

from data_platform.contracts.anp_fuel_prices import (
    ANP_NORMALIZER_VERSION,
    PILOT_PRODUCTS,
    AnpFuelPriceObservation,
    AnpQualityIssue,
    AnpSilverBatch,
    ParsedAnpAsset,
    ProductCode,
)


_PRODUCTS = {
    "GASOLINA": ProductCode.GASOLINE_C_COMMON,
    "GASOLINA COMUM": ProductCode.GASOLINE_C_COMMON,
    "GASOLINA ADITIVADA": ProductCode.GASOLINE_C_ADDITIZED,
    "ETANOL": ProductCode.ETHANOL_HYDRATED,
    "ETANOL HIDRATADO": ProductCode.ETHANOL_HYDRATED,
    "DIESEL": ProductCode.DIESEL_B_S500,
    "DIESEL S500": ProductCode.DIESEL_B_S500,
    "DIESEL S10": ProductCode.DIESEL_B_S10,
    "GNV": ProductCode.CNG,
    "GLP P13": ProductCode.LPG_P13,
}
_STATE_REGION = {
    "AC": "N", "AL": "NE", "AP": "N", "AM": "N", "BA": "NE",
    "CE": "NE", "DF": "CO", "ES": "SE", "GO": "CO", "MA": "NE",
    "MT": "CO", "MS": "CO", "MG": "SE", "PA": "N", "PB": "NE",
    "PR": "S", "PE": "NE", "PI": "NE", "RJ": "SE", "RN": "NE",
    "RS": "S", "RO": "N", "RR": "N", "SC": "S", "SP": "SE",
    "SE": "NE", "TO": "N",
}


def _text(value: str) -> str:
    return " ".join(value.strip().split())


def _code(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", _text(value))
    return "".join(character for character in decomposed if not unicodedata.combining(character)).upper()


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _decimal(value: str, *, nullable: bool) -> Decimal | None:
    cleaned = _text(value)
    if not cleaned and nullable:
        return None
    if not cleaned:
        raise ValueError("missing monetary value")
    if not re.fullmatch(r"-?\d{1,9}(?:,\d{1,4})?", cleaned):
        raise ValueError("invalid monetary value")
    try:
        result = Decimal(cleaned.replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError("invalid monetary value") from exc
    if not result.is_finite():
        raise ValueError("non-finite monetary value")
    return result


def _valid_cnpj(digits: str) -> bool:
    if len(digits) != 14 or len(set(digits)) == 1:
        return False
    for length, weights in (
        (12, (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)),
        (13, (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)),
    ):
        total = sum(int(digits[index]) * weight for index, weight in enumerate(weights))
        remainder = total % 11
        expected = 0 if remainder < 2 else 11 - remainder
        if int(digits[length]) != expected:
            return False
    return True


def _identity(payload: dict[str, str]) -> tuple[str, str | None, str, AnpQualityIssue | None]:
    digits = "".join(character for character in payload["CNPJ da Revenda"] if character.isdigit())
    if _valid_cnpj(digits):
        cnpj_hash = hashlib.sha256(f"anp-cnpj:{digits}".encode("ascii")).hexdigest()
        return cnpj_hash, cnpj_hash, "cnpj_hash", None
    fallback = _hash(
        {
            "legal_name": _code(payload["Revenda"]),
            "street": _code(payload["Nome da Rua"]),
            "number": _code(payload["Numero Rua"]),
            "municipality": _code(payload["Municipio"]),
            "state": _code(payload["Estado - Sigla"]),
        }
    )
    issue = AnpQualityIssue(
        layer_name="silver",
        rule_code="ANP_ESTABLISHMENT_FALLBACK_IDENTITY",
        severity="warning",
        record_reference=None,
        message="Establishment identity used a controlled fallback",
        details={"normalizer_version": ANP_NORMALIZER_VERSION},
    )
    return fallback, None, "fallback_identity", issue


def _reject(line_number: int, rule: str, message: str) -> AnpQualityIssue:
    return AnpQualityIssue(
        layer_name="silver",
        rule_code=rule,
        severity="error",
        record_reference=f"line:{line_number}",
        message=message,
        details={},
    )


def transform_asset(parsed: ParsedAnpAsset) -> AnpSilverBatch:
    candidates: list[AnpFuelPriceObservation] = []
    issues: list[AnpQualityIssue] = []
    rejected = 0
    for raw in parsed.rows:
        payload = dict(raw.payload)
        try:
            product = _PRODUCTS.get(_code(payload["Produto"]))
            if product is None:
                raise _RowRejected("ANP_UNKNOWN_PRODUCT", "Unknown ANP product blocks the observation")
            if product not in PILOT_PRODUCTS:
                raise _RowRejected("ANP_PRODUCT_OUTSIDE_RESOURCE", "Recognized product is outside this ANP resource")
            if _code(payload["Unidade de Medida"]) not in {"R$ / LITRO", "R$/LITRO"}:
                raise _RowRejected("ANP_INCOMPATIBLE_UNIT", "Incompatible ANP unit blocks the observation")
            sale_price = _decimal(payload["Valor de Venda"], nullable=False)
            purchase_price = _decimal(payload["Valor de Compra"], nullable=True)
            assert sale_price is not None
            if sale_price <= 0 or (purchase_price is not None and purchase_price < 0):
                raise _RowRejected("ANP_INVALID_PRICE", "Invalid ANP price blocks the observation")
            state = _code(payload["Estado - Sigla"])
            region = _code(payload["Regiao - Sigla"])
            if state not in _STATE_REGION or region != _STATE_REGION[state]:
                raise _RowRejected("ANP_INVALID_GEOGRAPHY", "Invalid ANP state or region blocks the observation")
            try:
                collection_date = datetime.strptime(_text(payload["Data da Coleta"]), "%d/%m/%Y").date()
            except ValueError as exc:
                raise _RowRejected("ANP_INVALID_COLLECTION_DATE", "Invalid ANP collection date blocks the observation") from exc
            if not parsed.period_start <= collection_date <= parsed.period_end:
                raise _RowRejected("ANP_COLLECTION_DATE_OUTSIDE_PERIOD", "Collection date is outside the asset period")
            establishment_key, cnpj_hash, identity_method, identity_issue = _identity(payload)
            if identity_issue:
                issues.append(replace(identity_issue, record_reference=f"line:{raw.line_number}"))
            municipality_display = _text(payload["Municipio"])
            municipality_normalized = _code(municipality_display)
            if not municipality_display:
                raise _RowRejected("ANP_INVALID_GEOGRAPHY", "Missing municipality blocks the observation")
            week_start = collection_date - timedelta(days=collection_date.weekday())
            week_end = week_start + timedelta(days=6)
            observation_key = _hash(
                {
                    "establishment": establishment_key,
                    "product": product.value,
                    "collection_date": collection_date.isoformat(),
                }
            )
            normalized_content = {
                "observation_key": observation_key,
                "sale_price": str(sale_price),
                "purchase_price": str(purchase_price) if purchase_price is not None else None,
                "flag": _text(payload["Bandeira"]),
                "legal_name": _text(payload["Revenda"]),
                "street": _text(payload["Nome da Rua"]),
                "number": _text(payload["Numero Rua"]),
                "complement": _text(payload["Complemento"]),
                "neighborhood": _text(payload["Bairro"]),
                "postal_code": _text(payload["Cep"]),
                "municipality": municipality_normalized,
                "state": state,
                "region": region,
            }
            candidates.append(
                AnpFuelPriceObservation(
                    raw=raw,
                    observation_key=observation_key,
                    content_hash=_hash(normalized_content),
                    product_code=product,
                    sale_price=sale_price,
                    purchase_price=purchase_price,
                    flag_name=_text(payload["Bandeira"]) or None,
                    legal_name=_text(payload["Revenda"]),
                    establishment_key=establishment_key,
                    cnpj_hash=cnpj_hash,
                    street_name=_text(payload["Nome da Rua"]) or None,
                    street_number=_text(payload["Numero Rua"]) or None,
                    address_complement=_text(payload["Complemento"]) or None,
                    neighborhood=_text(payload["Bairro"]) or None,
                    postal_code=_text(payload["Cep"]) or None,
                    municipality_name=municipality_display,
                    municipality_normalized=municipality_normalized,
                    state_code=state,
                    region_code=region,
                    collection_date=collection_date,
                    week_start=week_start,
                    week_end=week_end,
                    identity_method=identity_method,
                    quality_status="warning" if identity_issue else "passed",
                    observed_at=parsed.asset.collected_at,
                )
            )
        except _RowRejected as exc:
            rejected += 1
            issues.append(_reject(raw.line_number, exc.rule_code, str(exc)))
        except (KeyError, ValueError) as exc:
            rejected += 1
            issues.append(_reject(raw.line_number, "ANP_INVALID_ROW", str(exc)))

    by_key: dict[str, list[AnpFuelPriceObservation]] = defaultdict(list)
    for candidate in candidates:
        by_key[candidate.observation_key].append(candidate)
    accepted: list[AnpFuelPriceObservation] = []
    deduplicated = 0
    for observation_key, group in by_key.items():
        hashes = {item.content_hash for item in group}
        if len(hashes) > 1:
            rejected += len(group)
            issues.append(
                AnpQualityIssue(
                    layer_name="silver",
                    rule_code="ANP_ASSET_IDENTITY_CONFLICT",
                    severity="critical",
                    record_reference=f"observation:{observation_key}",
                    message="One ANP asset contains divergent rows for the same observation identity",
                    details={"row_count": len(group)},
                )
            )
            continue
        accepted.append(group[0])
        deduplicated += len(group) - 1
    return AnpSilverBatch(
        observations=tuple(accepted),
        issues=tuple(issues),
        rejected_count=rejected,
        deduplicated_count=deduplicated,
    )


class _RowRejected(ValueError):
    def __init__(self, rule_code: str, message: str) -> None:
        self.rule_code = rule_code
        super().__init__(message)
