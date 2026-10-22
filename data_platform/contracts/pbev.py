from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID


PBEV_SOURCE_SYSTEM = "inmetro_pbev"
PBEV_PARSER_VERSION = "pbev-pdf-v1"
PBEV_MATCHER_VERSION = "pbev-match-v1"
PBEV_LICENSE_CODE = "CC-BY-ND-3.0"
PBEV_LICENSE_URL = "https://creativecommons.org/licenses/by-nd/3.0/"
PBEV_ATTRIBUTION = "Instituto Nacional de Metrologia, Qualidade e Tecnologia (Inmetro) - PBE Veicular"


class MappingStatus(StrEnum):
    MATCHED = "matched"
    PENDING = "pending"
    AMBIGUOUS = "ambiguous"
    REJECTED = "rejected"
    NOT_FOUND = "not_found"


class MatchMethod(StrEnum):
    EXACT_RULE = "exact_rule"
    SCORED_RULE = "scored_rule"
    MANUAL_REVIEW = "manual_review"
    CATALOG_CONFLICT = "catalog_conflict"
    NO_CANDIDATE = "no_candidate"


@dataclass(frozen=True)
class AuditedAsset:
    cycle_year: int
    filename: str
    official_page_url: str
    download_url: str
    sha256: str
    byte_length: int
    page_count: int
    expected_row_count: int
    layout_family: str
    document_title: str


_BASE_PAGE = (
    "https://www.gov.br/inmetro/pt-br/assuntos/regulamentacao/"
    "avaliacao-da-conformidade/programa-brasileiro-de-etiquetagem/"
    "tabelas-de-eficiencia-energetica/veiculos-automotivos-pbe-veicular"
)


AUDITED_ASSETS: tuple[AuditedAsset, ...] = (
    AuditedAsset(2017, "veiculos_leves_2017.pdf", _BASE_PAGE, f"{_BASE_PAGE}/veiculos-leves-2017/@@download/file", "951c6b7fd4d6bb11c660816ae391f7129ed47e5aba558236d20398ece8b09f74", 3121446, 48, 735, "pbev-l1-2017-2019-v1", "Tabelas de Consumo/Eficiencia Energetica - Veiculos Automotores Leves - Ano 2017"),
    AuditedAsset(2018, "veiculos_leves_2018.pdf", _BASE_PAGE, f"{_BASE_PAGE}/veiculos-leves-2018/@@download/file", "73b4213fc9821eaf50eeb2142f0eff539a43fae9856e63ccfe2ee72d4fb5d5d4", 3364644, 52, 790, "pbev-l1-2017-2019-v1", "Tabelas de Consumo/Eficiencia Energetica - Veiculos Automotores Leves - Ano 2018"),
    AuditedAsset(2019, "veiculos_leves_2019.pdf", _BASE_PAGE, f"{_BASE_PAGE}/veiculos-leves-2019/@@download/file", "d2168ac4bdd266a483468390d501565186e36949eff0c37f61fbc419be5d8804", 3058197, 46, 684, "pbev-l1-2017-2019-v1", "Tabelas de Consumo/Eficiencia Energetica - Veiculos Automotores Leves - Ano 2019"),
    AuditedAsset(2020, "veiculos_leves_2020.pdf", _BASE_PAGE, f"{_BASE_PAGE}/veiculos-leves-2020/@@download/file", "b68ec4d79993badc6e89f9b19e99f19695b365e840b33321326beed7f7ed03a7", 1694592, 47, 1034, "pbev-l2-2020-v1", "Tabelas de Consumo/Eficiencia Energetica - Veiculos Automotores Leves - Ano 2020"),
    AuditedAsset(2021, "pbe-veicular-2021.pdf", _BASE_PAGE, f"{_BASE_PAGE}/veiculos-leves-2021/@@download/file", "3c2350a98cb5182f6d4c165be310f4edf4eb9b3162a92bf089be2a8005e2b6b7", 429588, 20, 1117, "pbev-l3-2021-v1", "PBE Veicular 2021"),
    AuditedAsset(2022, "pbe-veicular-2022.pdf", _BASE_PAGE, f"{_BASE_PAGE}/pbe-veicular-2022.pdf/@@download/file", "64cadc11a252641f2568c0f0e5d5749189505d7a1f10a30a375e9f38f83b87fd", 517938, 7, 785, "pbev-l4-2022-v1", "PBE Veicular 2022"),
)


AUDITED_ASSET_BY_YEAR = {item.cycle_year: item for item in AUDITED_ASSETS}


@dataclass(frozen=True)
class SourceAsset:
    pipeline_run_id: UUID | None
    cycle_year: int
    official_page_url: str
    download_url_sanitized: str
    document_title: str
    accessed_at: datetime
    content_type: str
    byte_length: int
    page_count: int
    sha256: str
    layout_family: str
    document_metadata: Mapping[str, Any] = field(default_factory=dict)
    storage_mode: str = "metadata_only"
    license_code: str = PBEV_LICENSE_CODE
    attribution_text: str = PBEV_ATTRIBUTION
    license_url: str = PBEV_LICENSE_URL
    asset_status: str = "accepted"
    validation_details: Mapping[str, Any] = field(default_factory=dict)
    published_at: datetime | None = None
    document_bytes: bytes | None = None
    asset_id: int | None = None

    def __post_init__(self) -> None:
        if self.storage_mode not in {"metadata_only", "internal_copy"}:
            raise ValueError("invalid PBEV storage mode")
        if self.storage_mode == "metadata_only" and self.document_bytes is not None:
            raise ValueError("metadata_only assets cannot retain document bytes")
        if self.asset_status not in {"accepted", "quarantined", "rejected"}:
            raise ValueError("invalid PBEV asset status")


@dataclass(frozen=True)
class PbevRawRow:
    cycle_year: int
    page_number: int
    row_number: int
    parser_version: str
    layout_family: str
    schema_fingerprint: str
    raw_cells: tuple[str | None, ...]
    raw_text: str
    row_hash: str
    extraction_status: str = "parsed"
    extraction_method: str = "vector_grid"
    source_record_key: str | None = None
    asset_id: int | None = None
    pipeline_run_id: UUID | None = None
    pbev_raw_row_id: int | None = None


@dataclass(frozen=True)
class ParsedPbevRow:
    raw: PbevRawRow
    category_name: str
    brand_name: str
    model_name: str
    version_name: str | None
    motor_description: str | None
    transmission_code: str | None
    propulsion_type: str | None
    fuel_type: str | None
    air_conditioning_code: str | None
    steering_assistance_code: str | None
    emission_schema_version: str
    emission_raw: tuple[str | None, ...]
    consumption_raw: tuple[str | None, ...]
    nmhc_mg_km: Decimal | None = None
    nox_mg_km: Decimal | None = None
    nmog_nox_mg_km: Decimal | None = None
    co_mg_km: Decimal | None = None
    cho_mg_km: Decimal | None = None
    co2_ethanol_g_km: Decimal | None = None
    co2_fossil_g_km: Decimal | None = None
    pollutant_reduction_class: str | None = None
    ethanol_city_km_l: Decimal | None = None
    ethanol_highway_km_l: Decimal | None = None
    fossil_city_km_l: Decimal | None = None
    fossil_highway_km_l: Decimal | None = None
    electric_city_km_l_equivalent: Decimal | None = None
    electric_highway_km_l_equivalent: Decimal | None = None
    energy_mj_km: Decimal | None = None
    pbe_relative_class: str | None = None
    pbe_absolute_class: str | None = None
    conpet_seal: bool | None = None

    @property
    def material_metrics_key(self) -> tuple[Any, ...]:
        return (
            self.emission_schema_version,
            self.emission_raw,
            self.consumption_raw,
            self.energy_mj_km,
            self.pbe_relative_class,
            self.pbe_absolute_class,
            self.conpet_seal,
        )


@dataclass(frozen=True)
class ExternalVehicleIdentity:
    vehicle_sk: int
    brand_name: str
    model_name: str
    model_year: int
    fuel_type: str
    version_name: str | None = None
    motor_description: str | None = None
    transmission_type: str | None = None
    body_style: str | None = None
    external_catalog_reference: int | None = None
    catalog_model_name: str | None = None
    catalog_conflict: bool = False
    evidence: Mapping[str, Any] = field(default_factory=dict)

    @property
    def identity_hash(self) -> str:
        payload = {
            "vehicle_sk": self.vehicle_sk,
            "brand": self.brand_name,
            "model": self.model_name,
            "year": self.model_year,
            "fuel": self.fuel_type,
            "version": self.version_name,
            "transmission": self.transmission_type,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ExternalVehicleMapping:
    target_identity_hash: str
    target_identity_evidence: Mapping[str, Any]
    mapping_status: MappingStatus
    match_method: MatchMethod
    matcher_version: str
    confidence: Decimal | None
    review_required: bool
    evidence: Mapping[str, Any]
    decision_reason: str
    vehicle_sk: int | None = None
    selected_raw_row_id: int | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    supersedes_mapping_id: int | None = None
    mapping_decision_id: int | None = None

    def __post_init__(self) -> None:
        if self.mapping_status == MappingStatus.MATCHED:
            if self.vehicle_sk is None or self.confidence is None:
                raise ValueError("matched PBEV mapping requires real vehicle_sk and confidence")
        elif self.vehicle_sk is not None:
            raise ValueError("only matched PBEV mappings may carry vehicle_sk")
        if (self.reviewed_by is None) != (self.reviewed_at is None):
            raise ValueError("review author and timestamp must be provided together")


@dataclass(frozen=True)
class EfficiencyObservation:
    vehicle_sk: int
    mapping_decision_id: int
    pbev_raw_row_id: int
    cycle_year: int
    parsed: ParsedPbevRow
    quality_status: str = "passed"
    observation_id: int | None = None


@dataclass(frozen=True)
class EfficiencyGoldRow:
    dataset_version: str
    vehicle_sk: int
    mapping_decision_id: int
    observation_id: int
    asset_id: int
    pbev_raw_row_id: int
    parser_version: str
    matcher_version: str
    data_confidence: Decimal
    quality_status: str
    publication_run_id: UUID


@dataclass(frozen=True)
class CoverageSlice:
    key: str
    universe: int
    matched: int
    coverage_percentage: Decimal


@dataclass(frozen=True)
class SourceCoverageReport:
    source_system: str
    dataset_version: str
    asset_manifest: tuple[Mapping[str, Any], ...]
    universe_count: int
    eligible_count: int
    matched_count: int
    pending_count: int
    ambiguous_count: int
    rejected_count: int
    not_found_count: int
    published_count: int
    coverage_percentage: Decimal
    by_brand: tuple[CoverageSlice, ...]
    by_year: tuple[CoverageSlice, ...]
    by_fuel: tuple[CoverageSlice, ...]
    field_coverage: Mapping[str, Mapping[str, Any]]
    reason_counts: Mapping[str, int]
    generated_at: datetime
    parser_version: str
    matcher_version: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, default=str, sort_keys=True)


@dataclass(frozen=True)
class PbevAssetParseResult:
    asset: SourceAsset
    rows: tuple[ParsedPbevRow, ...]
    pages_processed: int
    tables_found: int
    rows_rejected: int
    fallback_pages: tuple[int, ...] = ()


@dataclass(frozen=True)
class PbevPipelineResult:
    status: str
    dataset_version: str | None
    pipeline_run_ids: tuple[str, ...]
    assets_processed: int
    rows_extracted: int
    mappings_by_status: Mapping[str, int]
    published_count: int
    coverage_percentage: Decimal
    errors: tuple[str, ...] = ()

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, default=str, sort_keys=True)


def audited_asset_manifest_hash() -> str:
    encoded = json.dumps(
        [item.sha256 for item in AUDITED_ASSETS],
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def find_audited_assets(directory: Path) -> dict[AuditedAsset, Path]:
    files = tuple(path for path in directory.glob("*.pdf") if path.is_file())
    by_hash: dict[str, Path] = {}
    for path in files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        by_hash[digest] = path
    return {asset: by_hash[asset.sha256] for asset in AUDITED_ASSETS if asset.sha256 in by_hash}
