from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import time
from typing import Callable

from data_platform.common.logging import sanitize
from data_platform.contracts.pbev import (
    AUDITED_ASSETS,
    PBEV_MATCHER_VERSION,
    PBEV_PARSER_VERSION,
    MappingStatus,
    PbevAssetParseResult,
    PbevPipelineResult,
    find_audited_assets,
)
from data_platform.ingestion.pbev.parser import PbevPdfParser
from data_platform.orchestration.contracts import CancellationToken, StepTimeoutError
from data_platform.pbev.loader import PbevLoader
from data_platform.pbev.targets import load_current_catalog_targets
from data_platform.quality.pbev_checks import (
    build_coverage_report,
    enforce_audited_pilot_baseline,
    validate_shadow_rows,
)
from data_platform.transformation.pbev import match_all


@dataclass(frozen=True)
class PbevExecutionOptions:
    asset_directory: Path | None = None
    dry_run: bool = False
    trigger_type: str = "manual"
    source_reference: str | None = None
    git_commit: str | None = None
    timeout_seconds: float = 1800.0


def pbev_idempotency_key() -> str:
    payload = {
        "asset_hashes": [item.sha256 for item in AUDITED_ASSETS],
        "parser_version": PBEV_PARSER_VERSION,
        "matcher_version": PBEV_MATCHER_VERSION,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _field_coverage(observations) -> dict[str, dict[str, object]]:
    fields = (
        "energy_mj_km",
        "pbe_relative_class",
        "pbe_absolute_class",
        "transmission_code",
        "propulsion_type",
        "conpet_seal",
    )
    total = len(observations)
    coverage: dict[str, dict[str, object]] = {}
    for field in fields:
        present = sum(getattr(item.parsed, field) is not None for item in observations)
        percentage = (
            (Decimal(present) * Decimal("100") / Decimal(total)).quantize(Decimal("0.01"))
            if total
            else Decimal("0.00")
        )
        coverage[field] = {
            "present": present,
            "total": total,
            "coverage_percentage": str(percentage),
        }
    return coverage


def _checkpoint(token: CancellationToken, deadline: float) -> None:
    token.raise_if_cancelled()
    if time.monotonic() >= deadline:
        raise StepTimeoutError("PBEV pipeline timed out")


def run_pbev_pipeline(
    loader: PbevLoader | None,
    options: PbevExecutionOptions | None = None,
    *,
    cancellation_token: CancellationToken | None = None,
    heartbeat: Callable[[str], None] | None = None,
) -> PbevPipelineResult:
    options = options or PbevExecutionOptions()
    token = cancellation_token or CancellationToken()
    notify = heartbeat or (lambda _stage: None)
    if options.dry_run:
        # Deliberadamente nao resolve paths, nao importa pdfplumber, nao abre
        # banco, nao chama rede e nao escreve.
        return PbevPipelineResult(
            status="succeeded",
            dataset_version=None,
            pipeline_run_ids=(),
            assets_processed=0,
            rows_extracted=0,
            mappings_by_status={},
            published_count=0,
            coverage_percentage=Decimal("0.00"),
        )
    if loader is None:
        raise ValueError("PBEV loader is required outside dry-run")
    if options.asset_directory is None:
        raise ValueError("PBEV external asset directory is required")
    deadline = time.monotonic() + options.timeout_seconds
    located = find_audited_assets(options.asset_directory.resolve(strict=True))
    if len(located) != len(AUDITED_ASSETS):
        parser = PbevPdfParser()
        quarantined = []
        for asset in AUDITED_ASSETS:
            if asset in located:
                continue
            candidate = options.asset_directory / asset.filename
            if candidate.is_file():
                quarantined.append(
                    PbevAssetParseResult(
                        asset=parser.inspect_hash_drift(candidate, asset),
                        rows=(),
                        pages_processed=0,
                        tables_found=0,
                        rows_rejected=0,
                    )
                )
        if quarantined:
            quarantine_run = loader.start_run(
                "inmetro_pbev_bronze",
                PBEV_PARSER_VERSION,
                f"pbev-quarantine-{pbev_idempotency_key()[:16]}",
                options.trigger_type,
                options.source_reference,
                options.git_commit,
            )
            _, inserted, deduplicated = loader.persist_bronze(
                quarantine_run,
                quarantined,
            )
            loader.finish_run(
                quarantine_run,
                "failed",
                received=len(quarantined),
                inserted=inserted,
                deduplicated=deduplicated,
                rejected=len(quarantined),
                error="PBEV asset hash drift requires a new layout review",
            )
        raise ValueError("external PBEV directory does not contain all six audited hashes")

    run_ids = []
    idempotency_key = pbev_idempotency_key()
    bronze_run = loader.start_run(
        "inmetro_pbev_bronze",
        PBEV_PARSER_VERSION,
        f"pbev-bronze-{idempotency_key[:16]}",
        options.trigger_type,
        options.source_reference,
        options.git_commit,
    )
    run_ids.append(str(bronze_run))
    parsed_results = []
    try:
        parser = PbevPdfParser()
        with loader.cycle_locks(item.cycle_year for item in AUDITED_ASSETS):
            for asset in AUDITED_ASSETS:
                _checkpoint(token, deadline)
                parsed_results.append(parser.parse(located[asset], asset))
                notify(f"bronze:{asset.cycle_year}")
            rows, bronze_inserted, bronze_deduplicated = loader.persist_bronze(
                bronze_run,
                parsed_results,
            )
        loader.finish_run(
            bronze_run,
            "succeeded",
            received=sum(item.pages_processed for item in parsed_results),
            inserted=bronze_inserted,
            deduplicated=bronze_deduplicated,
            rejected=sum(item.rows_rejected for item in parsed_results),
        )
    except Exception as exc:
        loader.finish_run(bronze_run, "failed", received=0, inserted=0, deduplicated=0, rejected=0, error=sanitize(exc))
        raise

    _checkpoint(token, deadline)
    silver_run = loader.start_run(
        "inmetro_pbev_silver",
        PBEV_MATCHER_VERSION,
        f"pbev-silver-{idempotency_key[:16]}",
        options.trigger_type,
        options.source_reference,
        options.git_commit,
    )
    run_ids.append(str(silver_run))
    try:
        targets = load_current_catalog_targets(loader.engine)
        if len(targets) != 34:
            raise ValueError(
                f"current PBEV target universe must resolve 34 real Silver identities, got {len(targets)}"
            )
        mappings = match_all(targets, rows)
        persisted_mappings, observations, silver_inserted = loader.persist_mappings(
            silver_run,
            mappings,
            rows,
        )
        manifest = tuple(
            {
                "cycle_year": item.asset.cycle_year,
                "sha256": item.asset.sha256,
                "page_count": item.asset.page_count,
                "byte_length": item.asset.byte_length,
                "layout_family": item.asset.layout_family,
            }
            for item in parsed_results
        )
        enforce_audited_pilot_baseline(persisted_mappings, baseline_applicable=True)
        notify("silver:matched")
        loader.finish_run(
            silver_run,
            "succeeded",
            received=len(targets),
            inserted=silver_inserted,
            deduplicated=max(0, len(targets) - silver_inserted),
            rejected=sum(item.mapping_status != MappingStatus.MATCHED for item in persisted_mappings),
        )
    except Exception as exc:
        loader.finish_run(silver_run, "failed", received=0, inserted=0, deduplicated=0, rejected=0, error=sanitize(exc))
        raise

    _checkpoint(token, deadline)
    gold_run = loader.start_run(
        "inmetro_pbev_gold_shadow",
        "pbev-gold-shadow-v1",
        f"pbev-shadow-building-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
        options.trigger_type,
        options.source_reference,
        options.git_commit,
    )
    run_ids.append(str(gold_run))
    try:
        validate_shadow_rows(
            persisted_mappings,
            [item.vehicle_sk for item in observations],
        )
        provisional = f"pbev-shadow-{str(gold_run)[:8]}"
        report = build_coverage_report(
            dataset_version=provisional,
            asset_manifest=manifest,
            targets=targets,
            mappings=persisted_mappings,
            field_coverage=_field_coverage(observations),
            generated_at=datetime.now(UTC),
        )
        dataset_version, deduplicated = loader.publish_shadow(
            gold_run,
            report,
            persisted_mappings,
            observations,
        )
        loader.finish_run(
            gold_run,
            "succeeded",
            received=report.universe_count,
            inserted=0 if deduplicated else report.published_count,
            deduplicated=report.published_count if deduplicated else 0,
            rejected=report.universe_count - report.published_count,
        )
        notify("gold:shadow_published")
        counts = Counter(item.mapping_status.value for item in persisted_mappings)
        return PbevPipelineResult(
            status="deduplicated" if deduplicated else "succeeded",
            dataset_version=dataset_version,
            pipeline_run_ids=tuple(run_ids),
            assets_processed=len(parsed_results),
            rows_extracted=len(rows),
            mappings_by_status=dict(sorted(counts.items())),
            published_count=report.published_count,
            coverage_percentage=report.coverage_percentage,
        )
    except Exception as exc:
        loader.finish_run(gold_run, "failed", received=0, inserted=0, deduplicated=0, rejected=0, error=sanitize(exc))
        raise
