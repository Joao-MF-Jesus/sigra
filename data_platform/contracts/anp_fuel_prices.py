from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
import json
from pathlib import Path
from typing import Mapping
from uuid import UUID


ANP_SOURCE_NAME = "anp_fuel_prices"
ANP_PARSER_VERSION = "anp-csv-v1"
ANP_NORMALIZER_VERSION = "anp-normalizer-v1"
ANP_AGGREGATION_VERSION = "anp-weekly-shadow-v1"
ANP_STORAGE_MODE = "metadata_only"


class ProductCode(StrEnum):
    GASOLINE_C_COMMON = "gasoline_c_common"
    GASOLINE_C_ADDITIZED = "gasoline_c_additized"
    ETHANOL_HYDRATED = "ethanol_hydrated"
    DIESEL_B_S500 = "diesel_b_s500"
    DIESEL_B_S10 = "diesel_b_s10"
    CNG = "cng"
    LPG_P13 = "lpg_p13"


PILOT_PRODUCTS = frozenset(
    {
        ProductCode.GASOLINE_C_COMMON,
        ProductCode.GASOLINE_C_ADDITIZED,
        ProductCode.ETHANOL_HYDRATED,
    }
)
ANP_REQUIRED_PRODUCTS = frozenset(
    {
        ProductCode.GASOLINE_C_COMMON,
        ProductCode.ETHANOL_HYDRATED,
    }
)


@dataclass(frozen=True)
class DownloadedAnpAsset:
    source_reference: str
    official_page_url: str
    download_url_sanitized: str
    filename: str
    path: Path
    collected_at: datetime
    http_status: int
    content_type: str
    byte_length: int
    etag: str | None
    last_modified: str | None
    sha256: str


@dataclass(frozen=True)
class AnpRawRow:
    line_number: int
    payload: Mapping[str, str]
    row_hash: str
    extraction_status: str = "parsed"
    error_sanitized: str | None = None
    asset_id: int | None = None
    pipeline_run_id: UUID | None = None
    anp_raw_row_id: int | None = None


@dataclass(frozen=True)
class ParsedAnpAsset:
    asset: DownloadedAnpAsset
    layout_fingerprint: str
    period_start: date | None
    period_end: date | None
    rows: tuple[AnpRawRow, ...]
    ingestion_status: str = "accepted"
    error_sanitized: str | None = None
    technical_metadata: Mapping[str, object] = field(default_factory=dict)
    asset_id: int | None = None


@dataclass(frozen=True)
class AnpQualityIssue:
    layer_name: str
    rule_code: str
    severity: str
    record_reference: str | None
    message: str
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AnpFuelPriceObservation:
    raw: AnpRawRow
    observation_key: str
    content_hash: str
    product_code: ProductCode
    sale_price: Decimal
    purchase_price: Decimal | None
    flag_name: str | None
    legal_name: str
    establishment_key: str
    cnpj_hash: str | None
    street_name: str | None
    street_number: str | None
    address_complement: str | None
    neighborhood: str | None
    postal_code: str | None
    municipality_name: str
    municipality_normalized: str
    state_code: str
    region_code: str
    collection_date: date
    week_start: date
    week_end: date
    identity_method: str
    quality_status: str
    observed_at: datetime
    observation_id: int | None = None
    supersedes_observation_id: int | None = None


@dataclass(frozen=True)
class AnpSilverBatch:
    observations: tuple[AnpFuelPriceObservation, ...]
    issues: tuple[AnpQualityIssue, ...]
    rejected_count: int
    deduplicated_count: int


@dataclass(frozen=True)
class AnpFuelPriceSnapshot:
    product_code: ProductCode
    week_start: date
    week_end: date
    geography_level: str
    geography_key: str
    municipality_name: str | None
    state_code: str
    mean_price: Decimal
    median_price: Decimal
    minimum_price: Decimal
    maximum_price: Decimal
    percentile_25: Decimal
    percentile_75: Decimal
    interquartile_range: Decimal
    observation_count: int
    establishment_count: int
    last_collection_date: date
    freshness_days: int
    sampling_status: str
    dispersion_status: str
    quality_status: str
    snapshot_fingerprint: str


@dataclass(frozen=True)
class AnpQualityResult:
    rule_code: str
    severity: str
    status: str
    observed_value: Mapping[str, object]
    expected_condition: str
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AnpPipelineResult:
    status: str
    dataset_version: str | None
    pipeline_run_ids: tuple[str, ...]
    asset_sha256: str | None
    layout_fingerprint: str | None
    rows_received: int
    observations_current: int
    snapshots_published: int
    issues: int

    def to_json(self) -> str:
        return json.dumps(
            {
                "status": self.status,
                "dataset_version": self.dataset_version,
                "pipeline_run_ids": self.pipeline_run_ids,
                "asset_sha256": self.asset_sha256,
                "layout_fingerprint": self.layout_fingerprint,
                "rows_received": self.rows_received,
                "observations_current": self.observations_current,
                "snapshots_published": self.snapshots_published,
                "issues": self.issues,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
