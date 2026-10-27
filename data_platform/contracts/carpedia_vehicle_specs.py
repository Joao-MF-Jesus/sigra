from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
import json
from pathlib import Path
from typing import Mapping, Sequence
from uuid import UUID


CARPEDIA_SOURCE_NAME = "carpedia_api_v1"
CARPEDIA_CONTRACT_VERSION = "carpedia-api-v1"
CARPEDIA_PARSER_VERSION = "carpedia-ficha-v1"
CARPEDIA_NORMALIZER_VERSION = "carpedia-spec-normalizer-v2"
CARPEDIA_MATCHER_VERSION = "carpedia-exact-identity-v1"
CARPEDIA_PUBLICATION_VERSION = "carpedia-spec-shadow-v1"
CARPEDIA_LICENSE_STATUS = "approved_with_restrictions"
CARPEDIA_ATTRIBUTION = "Dados de especificações: Carpedia"
CARPEDIA_OFFICIAL_BASE_URL = "https://www.carpedia.com.br"


class CarpediaMappingStatus(StrEnum):
    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    REJECTED = "rejected"
    NOT_FOUND = "not_found"
    PENDING = "pending"


@dataclass(frozen=True)
class CarpediaTarget:
    external_vehicle_id: int
    model_year: int

    def __post_init__(self) -> None:
        if isinstance(self.external_vehicle_id, bool) or self.external_vehicle_id <= 0:
            raise ValueError("Carpedia target requires a positive official vehicle id")
        if isinstance(self.model_year, bool) or not 1900 <= self.model_year <= 2100:
            raise ValueError("Carpedia target model year is outside the supported range")

    @property
    def source_reference(self) -> str:
        return f"{self.external_vehicle_id}:{self.model_year}"


@dataclass(frozen=True)
class CarpediaRequest:
    logical_endpoint: str
    path: str
    parameters: Mapping[str, str | int] = field(default_factory=dict)
    external_vehicle_id: int | None = None
    source_reference: str | None = None


@dataclass(frozen=True)
class DownloadedCarpediaAsset:
    request: CarpediaRequest
    path: Path
    collected_at: datetime
    http_status: int
    content_type: str
    byte_length: int
    sha256: str


@dataclass(frozen=True)
class CarpediaRawRecord:
    external_vehicle_id: int
    model_year: int
    source_reference: str
    source_record_key: str
    payload: Mapping[str, object]
    row_hash: str
    parsed_at: datetime
    asset_id: int | None = None
    raw_record_id: int | None = None
    pipeline_run_id: UUID | None = None


@dataclass(frozen=True)
class CarpediaAttribute:
    attribute_code: str
    source_section: str
    source_label: str
    source_value: str
    source_unit: str | None
    normalized_value: Decimal | str | None
    normalized_unit: str | None
    precision: int | None
    unit_status: str
    provenance: Mapping[str, object]


@dataclass(frozen=True)
class ParsedCarpediaSpecification:
    asset: DownloadedCarpediaAsset
    raw: CarpediaRawRecord
    schema_fingerprint: str
    source_reference: str
    brand_name: str
    model_name: str
    version_name: str
    model_year: int
    source_name: str | None
    source_at: str | None
    attributes: tuple[CarpediaAttribute, ...]
    contract_recognized: bool = True


@dataclass(frozen=True)
class VehicleIdentityCandidate:
    vehicle_sk: int
    brand_name: str
    model_name: str
    version_name: str | None
    model_year: int | None
    is_zero_km: bool
    fuel_type: str


@dataclass(frozen=True)
class CarpediaMappingDecision:
    status: CarpediaMappingStatus
    match_method: str
    vehicle_sk: int | None
    confidence: Decimal | None
    review_required: bool
    identity_evidence: Mapping[str, object]
    candidate_evidence: tuple[Mapping[str, object], ...]
    decision_reason: str
    mapping_decision_id: int | None = None
    supersedes_mapping_id: int | None = None


@dataclass(frozen=True)
class CarpediaSpecification:
    parsed: ParsedCarpediaSpecification
    mapping: CarpediaMappingDecision
    attributes: Mapping[str, object]
    attribute_provenance: Mapping[str, object]
    source_fingerprint: str
    normalized_fingerprint: str
    quality_status: str
    specification_id: int | None = None
    supersedes_specification_id: int | None = None


@dataclass(frozen=True)
class CarpediaQualityIssue:
    layer_name: str
    rule_code: str
    severity: str
    record_reference: str | None
    message: str
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CarpediaQualityResult:
    rule_code: str
    severity: str
    status: str
    observed_value: Mapping[str, object]
    expected_condition: str
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CarpediaSnapshot:
    specification_id: int
    vehicle_sk: int
    external_vehicle_id: int
    source_reference: str
    model_year: int
    attributes: Mapping[str, object]
    attribute_provenance: Mapping[str, object]
    snapshot_fingerprint: str


@dataclass(frozen=True)
class CarpediaPipelineResult:
    status: str
    dataset_version: str | None
    pipeline_run_id: str | None
    targets: int
    records_received: int
    matched: int
    ambiguous: int
    rejected: int
    not_found: int
    pending: int
    snapshots_published: int
    plan: Mapping[str, object] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "status": self.status,
                "dataset_version": self.dataset_version,
                "pipeline_run_id": self.pipeline_run_id,
                "targets": self.targets,
                "records_received": self.records_received,
                "matched": self.matched,
                "ambiguous": self.ambiguous,
                "rejected": self.rejected,
                "not_found": self.not_found,
                "pending": self.pending,
                "snapshots_published": self.snapshots_published,
                "plan": self.plan,
            },
            ensure_ascii=False,
            sort_keys=True,
        )


def mapping_distribution(
    decisions: Sequence[CarpediaMappingDecision],
) -> Mapping[str, int]:
    return {
        status.value: sum(item.status == status for item in decisions)
        for status in CarpediaMappingStatus
    }
