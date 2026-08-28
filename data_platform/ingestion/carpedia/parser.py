from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit

from data_platform.contracts.carpedia_vehicle_specs import (
    CARPEDIA_PARSER_VERSION,
    CarpediaAttribute,
    CarpediaRawRecord,
    DownloadedCarpediaAsset,
    ParsedCarpediaSpecification,
)


_SENSITIVE_KEYS = frozenset({"authorization", "token", "api_key", "apikey", "key", "secret", "password"})


def _append_scalar_attributes(
    attributes: list[CarpediaAttribute],
    *,
    section: str,
    prefix: str,
    value: object,
) -> None:
    """Preserve nested official fields without assigning invented semantics."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            label = " ".join(part for part in (prefix, str(key)) if part)
            _append_scalar_attributes(attributes, section=section, prefix=label, value=item)
        return
    if isinstance(value, list):
        for index, item in enumerate(value, start=1):
            _append_scalar_attributes(
                attributes,
                section=section,
                prefix=f"{prefix} {index}",
                value=item,
            )
        return
    if value is None or isinstance(value, bool):
        return
    source_value = " ".join(str(value).split())
    if not source_value:
        return
    attributes.append(
        CarpediaAttribute(
            attribute_code="pending_normalization",
            source_section=section,
            source_label=prefix,
            source_value=source_value,
            source_unit=None,
            normalized_value=None,
            normalized_unit=None,
            precision=None,
            unit_status="pending",
            provenance={"contract_version": "carpedia-api-v1", "shape": "nested"},
        )
    )


def _sanitize_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): "[redacted]" if str(key).casefold() in _SENSITIVE_KEYS else _sanitize_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str) and "://" in value:
        try:
            parsed = urlsplit(value)
            if parsed.scheme and parsed.hostname:
                host = parsed.hostname + (f":{parsed.port}" if parsed.port else "")
                return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
        except ValueError:
            return "[redacted-url]"
    return value


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Carpedia response has an invalid {field_name}")
    return " ".join(value.split())


def _schema_fingerprint(payload: Mapping[str, object]) -> str:
    version = payload.get("versao")
    sections = payload.get("secoes")
    shape = {
        "top": sorted(payload),
        "version": sorted(version) if isinstance(version, Mapping) else [],
        "section": sorted(sections[0]) if isinstance(sections, list) and sections and isinstance(sections[0], Mapping) else [],
        "item": sorted(sections[0]["itens"][0])
        if isinstance(sections, list) and sections and isinstance(sections[0], Mapping)
        and isinstance(sections[0].get("itens"), list) and sections[0]["itens"]
        and isinstance(sections[0]["itens"][0], Mapping)
        else [],
    }
    encoded = json.dumps(shape, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class CarpediaJsonParser:
    def parse(self, asset: DownloadedCarpediaAsset) -> ParsedCarpediaSpecification:
        try:
            payload = json.loads(asset.path.read_text(encoding="utf-8"), parse_float=Decimal)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Carpedia response is not valid UTF-8 JSON") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("Carpedia response root must be an object")
        sanitized = _sanitize_value(payload)
        assert isinstance(sanitized, Mapping)
        source_reference = _required_text(sanitized.get("ref"), "reference")
        version = sanitized.get("versao")
        if not isinstance(version, Mapping):
            raise ValueError("Carpedia response has no vehicle version object")
        external_id = version.get("id")
        if isinstance(external_id, bool) or not isinstance(external_id, int) or external_id <= 0:
            raise ValueError("Carpedia response uses a non-official or invalid vehicle id")
        if asset.request.external_vehicle_id is not None and external_id != asset.request.external_vehicle_id:
            raise ValueError("Carpedia response vehicle id differs from the requested identity")
        year_value = sanitized.get("ano")
        if isinstance(year_value, str) and year_value.isdigit():
            year_value = int(year_value)
        if isinstance(year_value, bool) or not isinstance(year_value, int) or not 1900 <= year_value <= 2100:
            raise ValueError("Carpedia response has an invalid model year")
        sections = sanitized.get("secoes")
        if not isinstance(sections, list) or not sections:
            raise ValueError("Carpedia response has no specification sections")
        attributes: list[CarpediaAttribute] = []
        for section in sections:
            if not isinstance(section, Mapping):
                raise ValueError("Carpedia response contains an invalid section")
            title = _required_text(section.get("titulo"), "section title")
            items = section.get("itens")
            if not isinstance(items, list):
                raise ValueError("Carpedia response contains an invalid item list")
            for item in items:
                if not isinstance(item, Mapping):
                    raise ValueError("Carpedia response contains an invalid specification item")
                label = _required_text(item.get("label"), "specification label")
                value = item.get("valor")
                if value is None or isinstance(value, (dict, list, bool)):
                    raise ValueError("Carpedia response contains an invalid specification value")
                source_value = " ".join(str(value).split())
                if not source_value:
                    raise ValueError("Carpedia response contains an empty specification value")
                attributes.append(
                    CarpediaAttribute(
                        attribute_code="pending_normalization",
                        source_section=title,
                        source_label=label,
                        source_value=source_value,
                        source_unit=None,
                        normalized_value=None,
                        normalized_unit=None,
                        precision=None,
                        unit_status="pending",
                        provenance={"contract_version": "carpedia-api-v1"},
                    )
                )
        for field, section_title in (("consumo", "Consumo"), ("autonomia", "Autonomia")):
            nested = sanitized.get(field)
            if nested is not None:
                _append_scalar_attributes(
                    attributes,
                    section=section_title,
                    prefix="",
                    value=nested,
                )
        source = sanitized.get("fonte")
        source_name = source_at = None
        if source is not None:
            if not isinstance(source, Mapping):
                raise ValueError("Carpedia source provenance has an invalid shape")
            source_name = str(source.get("fonte") or "").strip() or None
            source_at = str(source.get("em") or "").strip() or None
        raw_payload = dict(sanitized)
        encoded = json.dumps(raw_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        raw = CarpediaRawRecord(
            external_vehicle_id=external_id,
            model_year=year_value,
            source_reference=source_reference,
            source_record_key=f"{external_id}:{year_value}",
            payload=raw_payload,
            row_hash=hashlib.sha256(encoded).hexdigest(),
            parsed_at=asset.collected_at or datetime.now(UTC),
        )
        return ParsedCarpediaSpecification(
            asset=asset,
            raw=raw,
            schema_fingerprint=_schema_fingerprint(raw_payload),
            source_reference=source_reference,
            brand_name=_required_text(version.get("marca"), "brand"),
            model_name=_required_text(version.get("modelo"), "model"),
            version_name=_required_text(version.get("nome"), "version"),
            model_year=year_value,
            source_name=source_name,
            source_at=source_at,
            attributes=tuple(attributes),
        )


__all__ = ["CARPEDIA_PARSER_VERSION", "CarpediaJsonParser"]
