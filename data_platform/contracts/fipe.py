from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class FipeTarget:
    vehicle_type: str
    fipe_code: str
    year_code: str

    @property
    def endpoint(self) -> str:
        return f"/{self.vehicle_type}s/{self.fipe_code}/years/{self.year_code}"


@dataclass(frozen=True)
class RawFipeRecord:
    source_name: str
    source_endpoint: str
    vehicle_type: str
    source_record_key: str
    fipe_code: str | None
    year_code: str | None
    reference_month_raw: str | None
    http_status: int
    collected_at: datetime
    payload: Any | None
    payload_hash: str
    schema_fingerprint: str | None
    raw_content_length: int
    ingestion_status: str
