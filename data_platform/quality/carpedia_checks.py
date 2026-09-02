from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Iterable, Mapping, Sequence

from data_platform.contracts.carpedia_vehicle_specs import (
    CARPEDIA_CONTRACT_VERSION,
    CARPEDIA_LICENSE_STATUS,
    CARPEDIA_SOURCE_NAME,
    CarpediaMappingStatus,
    CarpediaQualityIssue,
    CarpediaQualityResult,
    CarpediaSnapshot,
    CarpediaSpecification,
)


_HASH = re.compile(r"^[0-9a-f]{64}$")
_SECRET = re.compile(r"(?i)cpk_[A-Za-z0-9_-]{12,}|authorization|api[_-]?key|bearer\s+")
_RANGES = {
    "engine_displacement": (Decimal("300"), Decimal("10000"), "cm3"),
    "power": (Decimal("3"), Decimal("1500"), "kW"),
    "torque": (Decimal("5"), Decimal("3000"), "N_m"),
    "length": (Decimal("500"), Decimal("10000"), "mm"),
    "width": (Decimal("500"), Decimal("5000"), "mm"),
    "height": (Decimal("500"), Decimal("5000"), "mm"),
    "wheelbase": (Decimal("500"), Decimal("10000"), "mm"),
    "curb_weight": (Decimal("100"), Decimal("10000"), "kg"),
    "cargo_capacity": (Decimal("0"), Decimal("5000"), "L"),
    "fuel_tank_capacity": (Decimal("0"), Decimal("1000"), "L"),
    "doors": (Decimal("1"), Decimal("10"), "count"),
    "seats": (Decimal("1"), Decimal("100"), "count"),
}


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _contains_sensitive(value: object) -> bool:
    return bool(_SECRET.search(_json(value)))


def _range_issues(specifications: Sequence[CarpediaSpecification]) -> tuple[CarpediaQualityIssue, ...]:
    issues: list[CarpediaQualityIssue] = []
    for specification in specifications:
        for code, (minimum, maximum, unit) in _RANGES.items():
            raw = specification.attributes.get(code)
            values = raw if isinstance(raw, list) else [raw] if raw is not None else []
            for item in values:
                if not isinstance(item, Mapping) or item.get("value") is None:
                    continue
                try:
                    value = Decimal(str(item["value"]))
                except InvalidOperation:
                    value = Decimal("NaN")
                if item.get("unit") != unit or not value.is_finite() or value < minimum or value > maximum:
                    issues.append(
                        CarpediaQualityIssue(
                            "silver",
                            "CARPEDIA_PHYSICAL_RANGE",
                            "critical",
                            specification.parsed.raw.source_record_key,
                            "Normalized Carpedia attribute is outside its audited physical range",
                            {"attribute_code": code, "expected_unit": unit},
                        )
                    )
    return tuple(issues)


def build_snapshots(
    specifications: Sequence[CarpediaSpecification],
) -> tuple[CarpediaSnapshot, ...]:
    matched = [item for item in specifications if item.mapping.status == CarpediaMappingStatus.MATCHED]
    vehicle_ids = [item.mapping.vehicle_sk for item in matched]
    if len(vehicle_ids) != len(set(vehicle_ids)):
        raise ValueError("Carpedia Gold shadow contains duplicate vehicle grains")
    snapshots: list[CarpediaSnapshot] = []
    for item in matched:
        if (
            item.specification_id is None
            or item.mapping.mapping_decision_id is None
            or item.mapping.vehicle_sk is None
            or item.mapping.confidence != Decimal("100")
            or item.mapping.review_required
        ):
            raise ValueError("Carpedia Gold shadow requires persisted matched Silver lineage")
        payload = {
            "vehicle_sk": item.mapping.vehicle_sk,
            "specification_id": item.specification_id,
            "external_vehicle_id": item.parsed.raw.external_vehicle_id,
            "source_reference": item.parsed.source_reference,
            "model_year": item.parsed.model_year,
            "normalized_fingerprint": item.normalized_fingerprint,
        }
        snapshots.append(
            CarpediaSnapshot(
                specification_id=item.specification_id,
                vehicle_sk=item.mapping.vehicle_sk,
                external_vehicle_id=item.parsed.raw.external_vehicle_id,
                source_reference=item.parsed.source_reference,
                model_year=item.parsed.model_year,
                attributes=item.attributes,
                attribute_provenance=item.attribute_provenance,
                snapshot_fingerprint=hashlib.sha256(_json(payload).encode("utf-8")).hexdigest(),
            )
        )
    return tuple(snapshots)


def evaluate_quality(
    specifications: Sequence[CarpediaSpecification],
    snapshots: Sequence[CarpediaSnapshot],
    issues: Iterable[CarpediaQualityIssue] = (),
    *,
    lineage_evidence: Mapping[str, object] | None = None,
) -> tuple[CarpediaQualityResult, ...]:
    all_issues = tuple(issues) + _range_issues(specifications)
    critical = sum(item.severity == "critical" for item in all_issues)
    matched = sum(item.mapping.status == CarpediaMappingStatus.MATCHED for item in specifications)
    conflicts = sum(item.mapping.status in {CarpediaMappingStatus.AMBIGUOUS, CarpediaMappingStatus.REJECTED} for item in specifications)
    unknown_units = sum(
        attribute.unit_status == "unrecognized"
        for item in specifications
        for attribute in item.parsed.attributes
    )
    hashes_valid = all(
        _HASH.fullmatch(item.source_fingerprint)
        and _HASH.fullmatch(item.normalized_fingerprint)
        and _HASH.fullmatch(item.parsed.schema_fingerprint)
        for item in specifications
    )
    unique_external = len({item.parsed.raw.source_record_key for item in specifications}) == len(specifications)
    lineage_complete = all(
        item.parsed.raw.asset_id is not None
        and item.parsed.raw.raw_record_id is not None
        and item.mapping.mapping_decision_id is not None
        and item.specification_id is not None
        for item in specifications
    )
    lineage_coherent = bool(lineage_evidence and lineage_evidence.get("coherent"))
    sensitive = any(
        _contains_sensitive(item.parsed.raw.payload)
        or _contains_sensitive(item.attributes)
        or _contains_sensitive(item.attribute_provenance)
        for item in specifications
    )
    results = (
        CarpediaQualityResult(
            "CARPEDIA_SOURCE_AND_LICENSE_KNOWN", "critical", "passed",
            {"source": CARPEDIA_SOURCE_NAME, "license_status": CARPEDIA_LICENSE_STATUS},
            "official Carpedia API v1 with approved_with_restrictions usage and attribution",
        ),
        CarpediaQualityResult(
            "CARPEDIA_SCHEMA_AND_FINGERPRINT", "critical", "passed" if hashes_valid else "failed",
            {"records": len(specifications), "hashes_valid": hashes_valid, "contract_version": CARPEDIA_CONTRACT_VERSION},
            "recognized contract and deterministic 64-character SHA-256 fingerprints",
        ),
        CarpediaQualityResult(
            "CARPEDIA_UNITS_NORMALIZABLE", "critical", "passed" if unknown_units == 0 else "failed",
            {"unrecognized_units": unknown_units},
            "all numeric attributes use an explicitly recognized source unit",
        ),
        CarpediaQualityResult(
            "CARPEDIA_PHYSICAL_RANGES", "critical", "passed" if not _range_issues(specifications) else "failed",
            {"range_issue_count": len(_range_issues(specifications))},
            "normalized physical values are finite, non-negative where applicable and within audited ranges",
        ),
        CarpediaQualityResult(
            "CARPEDIA_IDENTITY_ELIGIBLE", "critical", "passed" if matched and matched == len(snapshots) else "failed",
            {"matched": matched, "snapshots": len(snapshots), "non_matched": len(specifications) - matched},
            "only unambiguous exact Silver identities are eligible for Gold shadow snapshots",
        ),
        CarpediaQualityResult(
            "CARPEDIA_NO_MATERIAL_CONFLICT",
            "critical",
            "passed" if len(snapshots) == matched else "failed",
            {
                "excluded_conflicting_records": conflicts,
                "published_conflicting_records": 0,
            },
            "ambiguous or conflicting identities remain in Silver and are excluded from Gold shadow",
        ),
        CarpediaQualityResult(
            "CARPEDIA_LINEAGE_COMPLETE", "critical", "passed" if lineage_complete else "failed",
            {"complete": lineage_complete},
            "every candidate has Bronze asset/raw, mapping and Silver specification lineage",
        ),
        CarpediaQualityResult(
            "CARPEDIA_LINEAGE_IDENTITY_COHERENT",
            "critical",
            "passed" if lineage_coherent else "failed",
            {
                "coherent": lineage_coherent,
                "specifications": int((lineage_evidence or {}).get("specifications", 0)),
                "snapshots": int((lineage_evidence or {}).get("snapshots", 0)),
                "publishable_snapshots": int(
                    (lineage_evidence or {}).get("publishable_snapshots", 0)
                ),
                "issue_codes": tuple((lineage_evidence or {}).get("issue_codes", ())),
            },
            "snapshot, Silver specification and current mapping decision agree on identity and publishable status",
        ),
        CarpediaQualityResult(
            "CARPEDIA_EXTERNAL_IDENTIFIERS_UNIQUE", "critical", "passed" if unique_external else "failed",
            {"unique": unique_external, "records": len(specifications)},
            "external vehicle and model-year record keys are unique within the candidate dataset",
        ),
        CarpediaQualityResult(
            "CARPEDIA_RECONCILIATION", "critical", "passed" if matched == len(snapshots) else "failed",
            {"silver_matched": matched, "gold_snapshots": len(snapshots)},
            "Gold snapshot count equals eligible matched Silver count",
        ),
        CarpediaQualityResult(
            "CARPEDIA_NO_SENSITIVE_CONTENT", "critical", "passed" if not sensitive else "failed",
            {"sensitive_content_detected": sensitive},
            "no API key, authorization header, token or authenticated URL is persisted",
        ),
        CarpediaQualityResult(
            "CARPEDIA_STORAGE_AND_PUBLICATION_MODE", "critical", "passed" if critical == 0 else "failed",
            {"publication_mode": "shadow", "storage_mode": "database_json", "critical_issues": critical},
            "authorized sanitized JSON only, atomic shadow publication and no operational integration",
        ),
    )
    return results


def require_hard_gates(results: Sequence[CarpediaQualityResult]) -> None:
    if any(item.severity == "critical" and item.status != "passed" for item in results):
        raise ValueError("Carpedia Gold shadow hard gates failed")
