from __future__ import annotations

import hashlib
import json
from typing import Any

from data_platform.common.logging import sanitize_endpoint
from data_platform.contracts.fipe import FipeTarget, RawFipeRecord
from data_platform.ingestion.fipe.client import FipeResponse


def canonical_json(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def payload_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def raw_content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _shape(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        shapes = {_canonical_shape(_shape(item)) for item in value}
        return [json.loads(item) for item in sorted(shapes)]
    return type(value).__name__


def _canonical_shape(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def schema_fingerprint(payload: Any) -> str:
    return hashlib.sha256(_canonical_shape(_shape(payload)).encode("utf-8")).hexdigest()


def extract_record(response: FipeResponse, target: FipeTarget, source_name: str = "Tabela FIPE via API Parallelum") -> RawFipeRecord:
    endpoint = sanitize_endpoint(response.endpoint)
    common = {
        "source_name": source_name,
        "source_endpoint": endpoint,
        "vehicle_type": target.vehicle_type,
        "year_code": target.year_code,
        "http_status": response.status_code,
        "collected_at": response.collected_at,
        "raw_content_length": len(response.body),
    }
    if not 200 <= response.status_code < 300:
        return RawFipeRecord(
            **common,
            source_record_key=f"{target.fipe_code}:{target.year_code}",
            fipe_code=target.fipe_code,
            reference_month_raw=None,
            payload=None,
            payload_hash=raw_content_hash(response.body),
            schema_fingerprint=None,
            ingestion_status="http_error",
        )
    try:
        payload = json.loads(response.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return RawFipeRecord(
            **common,
            source_record_key=f"{target.fipe_code}:{target.year_code}",
            fipe_code=target.fipe_code,
            reference_month_raw=None,
            payload=None,
            payload_hash=raw_content_hash(response.body),
            schema_fingerprint=None,
            ingestion_status="invalid_json",
        )
    code = str(payload.get("codeFipe") or target.fipe_code) if isinstance(payload, dict) else target.fipe_code
    reference = str(payload.get("referenceMonth")) if isinstance(payload, dict) and payload.get("referenceMonth") is not None else None
    return RawFipeRecord(
        **common,
        source_record_key=f"{code}:{target.year_code}",
        fipe_code=code,
        reference_month_raw=reference,
        payload=payload,
        payload_hash=payload_hash(payload),
        schema_fingerprint=schema_fingerprint(payload),
        ingestion_status="received",
    )
