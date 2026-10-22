from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from uuid import uuid4

import httpx

from data_platform.common.logging import sanitize
from data_platform.contracts.fipe import FipeTarget
from data_platform.ingestion.fipe.extractor import extract_record
from data_platform.quality.bronze_checks import validate_record


@dataclass(frozen=True)
class RunResult:
    pipeline_run_id: str
    dataset_version: str
    status: str
    records_received: int
    records_validated: int
    records_inserted: int
    records_deduplicated: int
    records_rejected: int
    errors: tuple[str, ...]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class PipelinePersistenceError(RuntimeError):
    """Erro de persistencia com mensagem segura para CLI e logs."""


def _finish_failed(loader, run_id, received, inserted, duplicates, rejected, errors) -> None:
    summary = "; ".join(errors) or "persistence failure"
    try:
        loader.finish_run(run_id, "failed", received, inserted, duplicates, rejected, summary)
    except Exception as exc:
        safe_error = sanitize(exc)
        errors.append(f"failed to finalize pipeline run: {safe_error}")
        raise PipelinePersistenceError("; ".join(errors)) from None


def run_pipeline(targets: list[FipeTarget], client, loader=None, *, dry_run=False, trigger_type="manual", source_reference=None, git_commit=None) -> RunResult:
    run_id = uuid4()
    dataset_version = f"fipe-{source_reference or 'manual'}-run-{str(run_id)[:8]}"
    if not dry_run:
        if loader is None:
            raise ValueError("loader e obrigatorio fora do dry-run")
        try:
            loader.start_run(run_id, dataset_version, trigger_type, source_reference, git_commit)
        except Exception as exc:
            raise PipelinePersistenceError(f"failed to start pipeline run: {sanitize(exc)}") from None
    received = validated = inserted = duplicates = rejected = 0
    errors: list[str] = []
    persistence_failed = False
    for target in targets:
        try:
            response = client.fetch(target.endpoint)
            received += 1
            record = extract_record(response, target)
            issues = validate_record(record)
            if issues:
                raise ValueError(",".join(issues))
            if record.ingestion_status == "received":
                validated += 1
            else:
                rejected += 1
                errors.append(
                    f"{record.ingestion_status} at {record.source_endpoint} "
                    f"(HTTP {record.http_status}, content_sha256={record.payload_hash})"
                )
            if dry_run:
                continue
            try:
                was_inserted = loader.insert(run_id, record)
            except Exception as exc:
                if record.ingestion_status == "received":
                    rejected += 1
                errors.append(f"failed to persist Bronze record: {sanitize(exc)}")
                persistence_failed = True
                break
            if was_inserted:
                inserted += 1
            else:
                duplicates += 1
        except (httpx.TimeoutException, httpx.HTTPError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            rejected += 1
            errors.append(sanitize(exc))
    status = "failed" if persistence_failed else (
        "succeeded" if rejected == 0 else ("partial" if validated else "failed")
    )
    summary = "; ".join(errors) or None
    if not dry_run:
        try:
            loader.finish_run(run_id, status, received, inserted, duplicates, rejected, summary)
        except Exception as exc:
            errors.append(f"failed to finalize pipeline run: {sanitize(exc)}")
            _finish_failed(loader, run_id, received, inserted, duplicates, rejected, errors)
            status = "failed"
    return RunResult(str(run_id), dataset_version, status, received, validated, inserted, duplicates, rejected, tuple(errors))
