"""Offline, hash-bound CarPedia enrichment for the experimental profile cohort."""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

from data_platform.catalog.profile_contracts_v3 import (
    Citation,
    Observation,
    ProfileVehicle,
    observed,
)
from data_platform.contracts.carpedia_vehicle_specs import (
    CARPEDIA_CONTRACT_VERSION,
    CARPEDIA_NORMALIZER_VERSION,
    CarpediaMappingStatus,
    CarpediaRequest,
    DownloadedCarpediaAsset,
    VehicleIdentityCandidate,
)
from data_platform.ingestion.carpedia.parser import CarpediaJsonParser
from data_platform.transformation.carpedia import build_specification, normalize_text


MANIFEST_PATH = Path(__file__).with_name("carpedia_profile_evidence_v1.json")
MANIFEST_VERSION = "carpedia-profile-evidence-v1"
EXPECTED_IDS = frozenset({36, 37, 38, 39, 42, 43, 46, 47, 49})
PROFILE_FIELDS = {
    "body_style": "body_type",
    "seats": "seats",
    "cargo_capacity": "cargo_l",
    "payload_capacity": "payload_kg",
    "length": "length_mm",
    "width": "width_mm",
    "wheelbase": "wheelbase_mm",
}
PROFILE_ONLY_FIELDS = {"ground_clearance": "ground_clearance_mm"}
PROFILE_FIELD_BY_CODE = {**PROFILE_FIELDS, **PROFILE_ONLY_FIELDS}
CONTRACT_ONLY_FIELDS = frozenset(
    {"power", "engine_displacement", "transmission", "fuel_type", "fuel_tank_capacity"}
)
_FULL_PROFILE_CODES = frozenset(PROFILE_FIELDS)
_PROFILE_CODES_WITHOUT_PAYLOAD = _FULL_PROFILE_CODES - {"payload_capacity"}
EXPECTED_CODES = {
    36: _FULL_PROFILE_CODES | CONTRACT_ONLY_FIELDS,
    37: _FULL_PROFILE_CODES | CONTRACT_ONLY_FIELDS,
    38: _PROFILE_CODES_WITHOUT_PAYLOAD | CONTRACT_ONLY_FIELDS,
    39: _FULL_PROFILE_CODES | CONTRACT_ONLY_FIELDS,
    42: _FULL_PROFILE_CODES | CONTRACT_ONLY_FIELDS | frozenset(PROFILE_ONLY_FIELDS),
    43: _FULL_PROFILE_CODES | CONTRACT_ONLY_FIELDS | frozenset(PROFILE_ONLY_FIELDS),
    46: _PROFILE_CODES_WITHOUT_PAYLOAD | CONTRACT_ONLY_FIELDS,
    47: _FULL_PROFILE_CODES | CONTRACT_ONLY_FIELDS,
    49: _PROFILE_CODES_WITHOUT_PAYLOAD | CONTRACT_ONLY_FIELDS,
}


def _load_manifest(path: Path = MANIFEST_PATH) -> dict[str, object]:
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    if manifest.get("schema_version") != MANIFEST_VERSION:
        raise ValueError("Carpedia profile evidence version mismatch")
    if manifest.get("carpedia_contract_version") != CARPEDIA_CONTRACT_VERSION:
        raise ValueError("Carpedia contract version mismatch")
    if manifest.get("normalizer_version") != CARPEDIA_NORMALIZER_VERSION:
        raise ValueError("Carpedia normalizer version mismatch")
    scope = manifest.get("scope")
    if not isinstance(scope, dict) or scope.get("publication_authorized") is not False or scope.get("database_write_authorized") is not False:
        raise ValueError("Carpedia offline evidence scope is invalid")
    records = manifest.get("records")
    if not isinstance(records, list):
        raise ValueError("Carpedia profile evidence records are invalid")
    identifiers = [row.get("candidate_id") for row in records if isinstance(row, dict)]
    if len(records) != len(EXPECTED_IDS) or len(set(identifiers)) != len(records) or set(identifiers) != EXPECTED_IDS:
        raise ValueError("Carpedia profile evidence candidate scope differs")
    for record in records:
        _validate_manifest_record(record)
    return manifest


def _validate_manifest_record(record: dict[str, object]) -> None:
    identifier = record["candidate_id"]
    cache_file = record.get("cache_file")
    if not isinstance(cache_file, str) or Path(cache_file).name != cache_file:
        raise ValueError("Invalid Carpedia cache filename")
    response_sha256 = record.get("response_sha256")
    if not isinstance(response_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", response_sha256):
        raise ValueError("Invalid Carpedia response hash")
    collected_at = datetime.fromisoformat(str(record.get("collected_at")))
    if collected_at.tzinfo is None:
        raise ValueError("Carpedia collection timestamp requires a timezone")
    external_id = record.get("external_vehicle_id")
    identity = record.get("catalog_identity")
    if not isinstance(identity, dict) or not isinstance(external_id, int):
        raise ValueError("Carpedia canonical identity is incomplete")
    fipe_digits = "".join(character for character in str(identity.get("fipe_code", "")) if character.isdigit())
    if not fipe_digits or int(fipe_digits) != external_id:
        raise ValueError("Carpedia external id differs from the canonical FIPE code")
    fields = record.get("fields")
    if not isinstance(fields, list):
        raise ValueError("Carpedia field admission list is invalid")
    codes = [field.get("attribute_code") for field in fields if isinstance(field, dict)]
    locators = [field.get("locator") for field in fields if isinstance(field, dict)]
    profile_fields = [field.get("profile_field") for field in fields if isinstance(field, dict) and field.get("profile_field")]
    if len(fields) != len(codes) or Counter(codes) != Counter(EXPECTED_CODES[identifier]):
        raise ValueError("Carpedia field admission scope differs")
    if len(set(codes)) != len(codes) or len(set(locators)) != len(locators) or len(set(profile_fields)) != len(profile_fields):
        raise ValueError("Duplicate Carpedia evidence field")
    for field in fields:
        code = field["attribute_code"]
        expected_profile = PROFILE_FIELD_BY_CODE.get(code)
        if field.get("profile_field") != expected_profile:
            if not (code in CONTRACT_ONLY_FIELDS and field.get("profile_field") is None):
                raise ValueError("Carpedia profile field mapping is invalid")


def _profile_only_normalization(item, expected):
    """Admit narrowly versioned profile fields without changing the API normalizer contract."""
    if expected["attribute_code"] not in PROFILE_ONLY_FIELDS:
        return item
    if expected["attribute_code"] != "ground_clearance":
        raise ValueError("Unsupported profile-only Carpedia field")
    if normalize_text(item.source_label) != "vao livre do solo mm":
        raise ValueError("Carpedia ground-clearance label or unit is not exact")
    match = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*", item.source_value)
    if match is None:
        raise ValueError("Carpedia ground clearance is not an exact millimetre value")
    value_text = match.group(1).replace(",", ".")
    value = Decimal(value_text)
    if not value.is_finite() or value <= 0:
        raise ValueError("Carpedia ground clearance must be positive")
    precision = len(value_text.rsplit(".", 1)[1]) if "." in value_text else 0
    return replace(
        item,
        attribute_code="ground_clearance",
        source_unit="mm",
        normalized_value=value.quantize(Decimal("0.000001")),
        normalized_unit="mm",
        precision=precision,
        unit_status="recognized",
        provenance={
            **item.provenance,
            "profile_evidence_normalizer_version": MANIFEST_VERSION,
            "unit_locator": "source_label",
            "source_value_preserved": True,
        },
    )


def _source_transmission(value: str) -> str | None:
    normalized = normalize_text(value)
    if "cvt" in normalized:
        return "cvt"
    if normalized == "automatico":
        return "automatic"
    if normalized == "manual":
        return "manual"
    return None


def _source_fuel(value: str) -> str | None:
    return {
        "flex": "flex",
        "gasolina": "gasoline",
        "etanol": "ethanol",
        "diesel": "diesel",
        "eletrico": "electric",
        "hibrido": "hybrid",
    }.get(normalize_text(value))


def reprocess_carpedia_caches(
    cache_directory: Path,
    *,
    manifest_path: Path = MANIFEST_PATH,
) -> dict[int, dict[str, object]]:
    """Reprocess only the hash-bound authorized fichas; no network, database or fallback."""
    directory = Path(cache_directory).resolve(strict=True)
    manifest = _load_manifest(manifest_path)
    output: dict[int, dict[str, object]] = {}
    for record in manifest["records"]:
        identifier = record["candidate_id"]
        cache_path = (directory / record["cache_file"]).resolve(strict=True)
        if cache_path.parent != directory or not cache_path.is_file():
            raise ValueError("Carpedia cache must be a direct regular file in the authorized directory")
        payload = cache_path.read_bytes()
        actual_sha256 = hashlib.sha256(payload).hexdigest()
        if actual_sha256 != record["response_sha256"]:
            raise ValueError("Carpedia cache changed")
        collected_at = datetime.fromisoformat(record["collected_at"])
        asset = DownloadedCarpediaAsset(
            request=CarpediaRequest(
                "vehicle_specification",
                f"/api/v1/ficha/{record['external_vehicle_id']}/{record['model_year']}",
                external_vehicle_id=record["external_vehicle_id"],
                source_reference=f"{record['external_vehicle_id']}:{record['model_year']}",
            ),
            path=cache_path,
            collected_at=collected_at,
            http_status=200,
            content_type="application/json",
            byte_length=len(payload),
            sha256=actual_sha256,
        )
        parsed = CarpediaJsonParser().parse(asset)
        source_identity = record["source_identity"]
        observed_identity = {
            "external_vehicle_id": parsed.raw.external_vehicle_id,
            "model_year": parsed.model_year,
            "source_reference": parsed.source_reference,
            "source_name": parsed.source_name,
            "source_at": parsed.source_at,
            "brand": parsed.brand_name,
            "model": parsed.model_name,
            "version": parsed.version_name,
        }
        expected_identity = {
            "external_vehicle_id": record["external_vehicle_id"],
            "model_year": record["model_year"],
            "source_reference": record["source_reference"],
            "source_name": record["source_name"],
            "source_at": record["source_at"],
            "brand": source_identity["brand"],
            "model": source_identity["model"],
            "version": source_identity["version"],
        }
        if observed_identity != expected_identity:
            raise ValueError("Carpedia cached identity differs from the versioned crosswalk")
        specification = build_specification(
            parsed,
            (
                VehicleIdentityCandidate(
                    vehicle_sk=identifier,
                    brand_name=source_identity["brand"],
                    model_name=source_identity["model"],
                    version_name=source_identity["version"],
                    model_year=record["model_year"],
                    is_zero_km=False,
                    fuel_type=source_identity["fuel"],
                ),
            ),
        )
        if specification.mapping.status != CarpediaMappingStatus.MATCHED or specification.mapping.match_method != "exact_identity":
            raise ValueError("Carpedia cache did not produce one exact identity")
        parsed_by_locator = {
            item.provenance.get("field_locator"): item
            for item in specification.parsed.attributes
        }
        if len(parsed_by_locator) != len(specification.parsed.attributes):
            raise ValueError("Carpedia field locator is missing or duplicated")
        fields: dict[str, object] = {}
        for expected in record["fields"]:
            raw_item = parsed_by_locator.get(expected["locator"])
            item = _profile_only_normalization(raw_item, expected) if raw_item is not None else None
            normalized_value = str(item.normalized_value) if item and isinstance(item.normalized_value, Decimal) else (item.normalized_value if item else None)
            if item is None or {
                "attribute_code": item.attribute_code,
                "source_section": item.source_section,
                "source_label": item.source_label,
                "source_value": item.source_value,
                "source_unit": item.source_unit,
                "normalized_value": normalized_value,
                "normalized_unit": item.normalized_unit,
            } != {key: expected[key] for key in (
                "attribute_code", "source_section", "source_label", "source_value",
                "source_unit", "normalized_value", "normalized_unit",
            )}:
                raise ValueError("Carpedia admitted field differs from its versioned evidence")
            if item.unit_status not in {"recognized", "not_applicable"}:
                raise ValueError("Carpedia admitted field has an invalid or unavailable unit")
            fields[item.attribute_code] = item
        if Counter(fields.keys()) != Counter(EXPECTED_CODES[identifier]):
            raise ValueError("Carpedia cache contains a missing or duplicate admitted attribute")
        output[identifier] = {
            "record": record,
            "specification": specification,
            "fields": fields,
            "response_sha256": actual_sha256,
        }
    return output


def augment_carpedia_profile_evidence(
    vehicles: tuple[ProfileVehicle, ...],
    cache_directory: Path,
    *,
    manifest_path: Path = MANIFEST_PATH,
) -> tuple[ProfileVehicle, ...]:
    processed = reprocess_carpedia_caches(cache_directory, manifest_path=manifest_path)
    output = []
    for vehicle in vehicles:
        evidence = processed.get(vehicle.id)
        if evidence is None:
            output.append(vehicle)
            continue
        record = evidence["record"]
        expected_identity = record["catalog_identity"]
        observed_identity = {
            "fipe_code": vehicle.fields["fipe_code"].value,
            "year_code": vehicle.fields["year_code"].value,
            "commercial_identity": vehicle.fields["commercial_identity"].value,
        }
        if observed_identity != expected_identity or vehicle.identity_status != "identity_approved":
            raise ValueError("Carpedia profile identity differs from the approved catalog identity")
        citation_base = {
            "provider": "carpedia",
            "url": record["source_url"],
            "sha256": record["response_sha256"],
            "document": f"CarPedia ficha técnica {record['external_vehicle_id']}/{record['model_year']}",
            "collected_at": record["collected_at"],
        }
        fields = dict(vehicle.fields)
        body_type = None
        admitted_profile_fields = []
        preserved_existing_profile_fields = []
        normalized_contract_fields = {}
        for expected in record["fields"]:
            item = evidence["fields"][expected["attribute_code"]]
            normalized_contract_fields[item.attribute_code] = {
                "value": str(item.normalized_value) if isinstance(item.normalized_value, Decimal) else item.normalized_value,
                "unit": item.normalized_unit,
                "source_value": item.source_value,
                "source_unit": item.source_unit,
                "origin": item.provenance["origin"],
                "external_vehicle_id": item.provenance["external_vehicle_id"],
                "model_year": item.provenance["model_year"],
                "response_sha256": item.provenance["response_sha256"],
                "source_reference": item.provenance["source_reference"],
                "collected_at": item.provenance["collected_at"],
                "source_name": item.provenance["source_name"],
                "source_at": item.provenance["source_at"],
                "locator": item.provenance["field_locator"],
            }
            profile_field = expected["profile_field"]
            if profile_field is None:
                continue
            citation = Citation(**citation_base, locator=expected["locator"])
            if profile_field == "body_type":
                body_type = Observation(
                    value=item.normalized_value,
                    unit="text",
                    kind="observed",
                    sources=(citation,),
                    applicability="exact_variant",
                )
            else:
                candidate_observation = observed(profile_field, item.normalized_value, (citation,))
                if fields[profile_field].kind == "unavailable":
                    fields[profile_field] = candidate_observation
                elif fields[profile_field] == candidate_observation:
                    pass
                elif (
                    fields[profile_field].value == candidate_observation.value
                    and fields[profile_field].unit == candidate_observation.unit
                ):
                    preserved_existing_profile_fields.append(profile_field)
                else:
                    raise ValueError("Carpedia enrichment cannot overwrite existing profile evidence")
            admitted_profile_fields.append(profile_field)
        carpedia_fuel = _source_fuel(evidence["fields"]["fuel_type"].source_value)
        carpedia_transmission = _source_transmission(evidence["fields"]["transmission"].source_value)
        if carpedia_fuel != vehicle.fields["fuel"].value or carpedia_transmission != vehicle.fields["transmission"].value:
            raise ValueError("Carpedia technical identity conflicts with official PBEV fuel or transmission")
        provenance = {
            **vehicle.provenance,
            "carpedia_profile_evidence": {
                "version": MANIFEST_VERSION,
                "external_vehicle_id": record["external_vehicle_id"],
                "model_year": record["model_year"],
                "source_reference": record["source_reference"],
                "response_sha256": record["response_sha256"],
                "collected_at": record["collected_at"],
                "match_method": "exact_fipe_code_year_and_versioned_identity",
                "official_precedence_preserved": {"fuel": "pbev", "transmission": "pbev"},
                "source_concordance": {"fuel": carpedia_fuel, "transmission": carpedia_transmission},
                "normalized_contract_fields": normalized_contract_fields,
                "admitted_profile_fields": admitted_profile_fields,
                "preserved_existing_profile_fields": preserved_existing_profile_fields,
                "unavailable_profile_fields": record["unavailable_profile_fields"],
            },
        }
        if body_type is not None:
            provenance["carpedia_body_type"] = body_type.model_dump(mode="json")
        output.append(ProfileVehicle.model_validate({**vehicle.model_dump(), "fields": fields, "provenance": provenance}))
    return tuple(output)


def carpedia_body_types(vehicles: tuple[ProfileVehicle, ...]) -> dict[int, Observation]:
    return {
        vehicle.id: Observation.model_validate(vehicle.provenance["carpedia_body_type"])
        for vehicle in vehicles
        if "carpedia_body_type" in vehicle.provenance
    }


__all__ = [
    "MANIFEST_PATH",
    "augment_carpedia_profile_evidence",
    "carpedia_body_types",
    "reprocess_carpedia_caches",
]
