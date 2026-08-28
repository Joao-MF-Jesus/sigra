from __future__ import annotations

from uuid import uuid4

from data_platform.common.logging import sanitize
from data_platform.contracts.silver_fipe import SilverRunResult
from data_platform.transformation.fipe import transform_bronze_record


class SilverPipelinePersistenceError(RuntimeError):
    """Erro de persistencia Silver com mensagem sanitizada."""


def _finish_failed(loader, run_id, received, inserted, duplicates, rejected, errors) -> None:
    summary = "; ".join(errors) or "Silver persistence failure"
    try:
        loader.finish_run(
            run_id,
            "failed",
            received,
            inserted,
            duplicates,
            rejected,
            summary,
        )
    except Exception as exc:
        errors.append(f"failed to finalize Silver pipeline run: {sanitize(exc)}")
        raise SilverPipelinePersistenceError("; ".join(errors)) from None


def run_silver_pipeline(
    loader,
    *,
    dry_run: bool = False,
    trigger_type: str = "manual",
    source_reference: str | None = None,
    git_commit: str | None = None,
) -> SilverRunResult:
    if not loader.is_postgresql:
        return SilverRunResult(
            pipeline_run_id=None,
            dataset_version=None,
            status="skipped",
            records_received=0,
            records_inserted=0,
            records_deduplicated=0,
            records_rejected=0,
            issues_inserted=0,
            errors=("SQLite no-op: Silver FIPE requires PostgreSQL",),
        )

    run_id = uuid4()
    dataset_version = f"fipe-silver-{source_reference or 'manual'}-run-{str(run_id)[:8]}"
    errors: list[str] = []
    inserted = duplicates = rejected = issues_inserted = 0
    try:
        records = loader.fetch_received_records()
    except Exception as exc:
        raise SilverPipelinePersistenceError(
            f"failed to read eligible Bronze records: {sanitize(exc)}"
        ) from None

    if not dry_run:
        try:
            loader.start_run(
                run_id,
                dataset_version,
                trigger_type,
                source_reference,
                git_commit,
            )
        except Exception as exc:
            raise SilverPipelinePersistenceError(
                f"failed to start Silver pipeline run: {sanitize(exc)}"
            ) from None

    persistence_failed = False
    for bronze in records:
        candidate = transform_bronze_record(bronze)
        if dry_run:
            if candidate.mapping_status != "matched" or candidate.price is None:
                rejected += 1
            continue
        try:
            outcome = loader.persist_candidate(run_id, candidate)
        except Exception as exc:
            errors.append(f"failed to persist Silver record: {sanitize(exc)}")
            rejected += 1
            persistence_failed = True
            break
        if outcome.inserted_rows:
            inserted += 1
        if outcome.deduplicated:
            duplicates += 1
        if outcome.rejected:
            rejected += 1
        issues_inserted += outcome.issues_inserted

    if persistence_failed:
        status = "failed"
    elif rejected == 0:
        status = "succeeded"
    elif inserted or duplicates:
        status = "partial"
    else:
        status = "rejected"

    if not dry_run:
        try:
            loader.finish_run(
                run_id,
                status,
                len(records),
                inserted,
                duplicates,
                rejected,
                "; ".join(errors) or None,
            )
        except Exception as exc:
            errors.append(f"failed to finalize Silver pipeline run: {sanitize(exc)}")
            _finish_failed(
                loader,
                run_id,
                len(records),
                inserted,
                duplicates,
                rejected,
                errors,
            )
            status = "failed"

    return SilverRunResult(
        pipeline_run_id=str(run_id),
        dataset_version=dataset_version,
        status=status,
        records_received=len(records),
        records_inserted=0 if dry_run else inserted,
        records_deduplicated=duplicates,
        records_rejected=rejected,
        issues_inserted=0 if dry_run else issues_inserted,
        errors=tuple(errors),
    )
