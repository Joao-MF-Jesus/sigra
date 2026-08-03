from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
import json
from typing import Any, Mapping
from uuid import UUID


@dataclass(frozen=True)
class BronzeFipeInput:
    fipe_raw_id: int
    bronze_pipeline_run_id: UUID
    source_name: str
    vehicle_type: str
    source_record_key: str
    fipe_code: str | None
    year_code: str | None
    reference_month_raw: str | None
    http_status: int
    collected_at: datetime
    payload: Any
    payload_hash: str
    schema_fingerprint: str | None
    ingestion_status: str

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "BronzeFipeInput":
        return cls(
            fipe_raw_id=int(row["fipe_raw_id"]),
            bronze_pipeline_run_id=row["pipeline_run_id"],
            source_name=str(row["source_name"]),
            vehicle_type=str(row["vehicle_type"]),
            source_record_key=str(row["source_record_key"]),
            fipe_code=str(row["fipe_code"]) if row["fipe_code"] is not None else None,
            year_code=str(row["year_code"]) if row["year_code"] is not None else None,
            reference_month_raw=(
                str(row["reference_month_raw"])
                if row["reference_month_raw"] is not None
                else None
            ),
            http_status=int(row["http_status"]),
            collected_at=row["collected_at"],
            payload=row["payload"],
            payload_hash=str(row["payload_hash"]),
            schema_fingerprint=(
                str(row["schema_fingerprint"])
                if row["schema_fingerprint"] is not None
                else None
            ),
            ingestion_status=str(row["ingestion_status"]),
        )


@dataclass(frozen=True)
class SilverQualityIssue:
    rule_code: str
    severity: str
    message: str
    entity_name: str = "bronze.fipe_raw"
    details: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class VehicleIdentityCandidate:
    vehicle_type: str
    brand_name: str
    model_name: str
    model_year: int | None
    is_zero_km: bool
    fuel_type: str
    canonical_key: str
    version_name: None = None
    transmission_type: None = None


@dataclass(frozen=True)
class VehiclePriceCandidate:
    price_amount: Decimal
    currency: str
    reference_month: date
    data_confidence: Decimal = Decimal("100.00")


@dataclass(frozen=True)
class PriceHistoryDecision:
    action: str
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    is_current: bool = False
    close_predecessor: bool = False


@dataclass(frozen=True)
class SilverTransformCandidate:
    bronze: BronzeFipeInput
    mapping_status: str
    match_method: str | None
    confidence: Decimal | None
    review_notes: str | None
    identity: VehicleIdentityCandidate | None
    price: VehiclePriceCandidate | None
    issues: tuple[SilverQualityIssue, ...]
    source_vehicle_key: str | None

    @property
    def can_persist_mapping(self) -> bool:
        return bool(
            self.source_vehicle_key
            and self.bronze.fipe_code
            and self.bronze.year_code
        )

    @property
    def has_blocking_issue(self) -> bool:
        return any(item.severity in {"error", "critical"} for item in self.issues)


@dataclass(frozen=True)
class SilverPersistenceOutcome:
    inserted_rows: int = 0
    deduplicated: bool = False
    rejected: bool = False
    issues_inserted: int = 0


@dataclass(frozen=True)
class SilverRunResult:
    pipeline_run_id: str | None
    dataset_version: str | None
    status: str
    records_received: int
    records_inserted: int
    records_deduplicated: int
    records_rejected: int
    issues_inserted: int
    errors: tuple[str, ...]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)
