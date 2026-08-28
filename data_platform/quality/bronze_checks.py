import re

from data_platform.contracts.fipe import RawFipeRecord


def validate_record(record: RawFipeRecord) -> list[str]:
    issues = []
    if record.collected_at.tzinfo is None:
        issues.append("collected_at_not_utc")
    if not re.fullmatch(r"[0-9a-f]{64}", record.payload_hash):
        issues.append("invalid_payload_hash")
    if record.raw_content_length < 0:
        issues.append("invalid_raw_content_length")
    if record.ingestion_status == "received" and not re.fullmatch(r"[0-9a-f]{64}", record.schema_fingerprint or ""):
        issues.append("invalid_schema_fingerprint")
    if record.ingestion_status != "received" and record.schema_fingerprint is not None:
        issues.append("unexpected_schema_fingerprint")
    if record.ingestion_status == "received" and record.payload is None:
        issues.append("missing_payload")
    if record.ingestion_status != "received" and record.payload is not None:
        issues.append("unexpected_payload")
    return issues
