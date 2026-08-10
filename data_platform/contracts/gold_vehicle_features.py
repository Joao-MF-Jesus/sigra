from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
import json
from typing import Any, Mapping
from uuid import UUID


GOLD_SOURCE_NAME = "Tabela FIPE via API Parallelum"
GOLD_VEHICLE_TYPE = "car"
GOLD_MINIMUM_COVERAGE = Decimal("80.00")


@dataclass(frozen=True)
class GoldScopeRow:
    mapping_id: int
    mapping_status: str
    vehicle_sk: int | None
    vehicle_type: str
    source_name: str
    source_vehicle_key: str
    fipe_code: str
    year_code: str
    mapping_run_id: UUID
    identity_vehicle_sk: int | None
    identity_vehicle_type: str | None
    brand_name: str | None
    model_name: str | None
    version_name: str | None
    model_year: int | None
    is_zero_km: bool | None
    fuel_type: str | None
    transmission_type: str | None
    identity_run_id: UUID | None
    silver_price_id: int | None
    price_vehicle_sk: int | None
    price_amount: Decimal | None
    currency: str | None
    reference_month: date | None
    price_collected_at: datetime | None
    data_confidence: Decimal | None
    price_run_id: UUID | None

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "GoldScopeRow":
        def optional_int(value: Any) -> int | None:
            return int(value) if value is not None else None

        def optional_decimal(value: Any) -> Decimal | None:
            return Decimal(value) if value is not None else None

        return cls(
            mapping_id=int(row["mapping_id"]),
            mapping_status=str(row["mapping_status"]),
            vehicle_sk=optional_int(row["vehicle_sk"]),
            vehicle_type=str(row["vehicle_type"]),
            source_name=str(row["source_name"]),
            source_vehicle_key=str(row["source_vehicle_key"]),
            fipe_code=str(row["fipe_code"]),
            year_code=str(row["year_code"]),
            mapping_run_id=row["mapping_run_id"],
            identity_vehicle_sk=optional_int(row["identity_vehicle_sk"]),
            identity_vehicle_type=(
                str(row["identity_vehicle_type"])
                if row["identity_vehicle_type"] is not None
                else None
            ),
            brand_name=(str(row["brand_name"]) if row["brand_name"] is not None else None),
            model_name=(str(row["model_name"]) if row["model_name"] is not None else None),
            version_name=(str(row["version_name"]) if row["version_name"] is not None else None),
            model_year=optional_int(row["model_year"]),
            is_zero_km=(bool(row["is_zero_km"]) if row["is_zero_km"] is not None else None),
            fuel_type=(str(row["fuel_type"]) if row["fuel_type"] is not None else None),
            transmission_type=(
                str(row["transmission_type"])
                if row["transmission_type"] is not None
                else None
            ),
            identity_run_id=row["identity_run_id"],
            silver_price_id=optional_int(row["silver_price_id"]),
            price_vehicle_sk=optional_int(row["price_vehicle_sk"]),
            price_amount=optional_decimal(row["price_amount"]),
            currency=(str(row["currency"]).strip() if row["currency"] is not None else None),
            reference_month=row["reference_month"],
            price_collected_at=row["price_collected_at"],
            data_confidence=optional_decimal(row["data_confidence"]),
            price_run_id=row["price_run_id"],
        )


@dataclass(frozen=True)
class GoldSnapshotCandidate:
    mapping_id: int
    vehicle_sk: int
    vehicle_type: str
    brand_name: str
    model_name: str
    version_name: str | None
    model_year: int | None
    is_zero_km: bool
    fuel_type: str
    transmission_type: str | None
    silver_price_id: int
    fipe_code: str
    year_code: str
    source_vehicle_key: str
    current_price: Decimal
    currency: str
    price_source: str
    price_reference_month: date
    price_collected_at: datetime
    data_confidence: Decimal
    base_quality_status: str
    silver_identity_run_id: UUID
    silver_mapping_run_id: UUID
    silver_price_run_id: UUID


@dataclass(frozen=True)
class GoldBlockedMapping:
    mapping_id: int
    reason_code: str
    message: str
    severity: str = "error"


@dataclass(frozen=True)
class GoldPublicationPlan:
    expected_count: int
    published_count: int
    blocked_count: int
    coverage_percentage: Decimal
    fingerprint: str
    base_quality_status: str
    candidates: tuple[GoldSnapshotCandidate, ...]
    blocked_mappings: tuple[GoldBlockedMapping, ...]
    global_blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class GoldPublicationResult:
    pipeline_run_id: str | None
    dataset_version: str | None
    status: str
    expected_count: int
    published_count: int
    blocked_count: int
    coverage_percentage: Decimal
    fingerprint: str | None
    issues_recorded: int
    errors: tuple[str, ...] = ()

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, default=str)


@dataclass(frozen=True)
class GoldRollbackResult:
    pipeline_run_id: str | None
    dataset_version: str | None
    previous_dataset_version: str | None
    status: str
    expected_count: int
    published_count: int
    blocked_count: int
    coverage_percentage: Decimal
    errors: tuple[str, ...] = ()

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, default=str)
