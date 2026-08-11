from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import tempfile
from typing import Callable

from data_platform.anp.loader import AnpAssetCorrectionError, AnpFuelPriceLoader
from data_platform.anp.sources import ANP_LAST_FOUR_WEEKS_REFERENCE, resolve_source
from data_platform.common.logging import sanitize
from data_platform.contracts.anp_fuel_prices import (
    ANP_AGGREGATION_VERSION,
    ANP_NORMALIZER_VERSION,
    ANP_PARSER_VERSION,
    AnpPipelineResult,
    ParsedAnpAsset,
)
from data_platform.ingestion.anp.client import AnpCsvClient
from data_platform.ingestion.anp.parser import AnpCsvParser, AnpLayoutDriftError
from data_platform.quality.anp_checks import build_snapshots, evaluate_quality, require_hard_gates
from data_platform.transformation.anp import transform_asset


@dataclass(frozen=True)
class AnpExecutionOptions:
    source_reference: str = ANP_LAST_FOUR_WEEKS_REFERENCE
    dry_run: bool = False
    trigger_type: str = "manual"
    git_commit: str | None = None


def run_anp_pipeline(
    loader: AnpFuelPriceLoader | None,
    options: AnpExecutionOptions | None = None,
    *,
    client: AnpCsvClient | None = None,
    parser: AnpCsvParser | None = None,
    heartbeat: Callable[[str], None] | None = None,
) -> AnpPipelineResult:
    options = options or AnpExecutionOptions()
    notify = heartbeat or (lambda _stage: None)
    if options.dry_run:
        # Deliberadamente nao resolve banco, cliente, rede ou arquivo temporario.
        return AnpPipelineResult("succeeded", None, (), None, None, 0, 0, 0, 0)
    if loader is None:
        raise ValueError("ANP loader is required outside dry-run")
    official_page, download_url, filename = resolve_source(options.source_reference)
    client = client or AnpCsvClient()
    parser = parser or AnpCsvParser()
    run_ids: list[str] = []
    with loader.source_lock(options.source_reference):
        bronze_run = loader.start_run(
            "anp_fuel_prices_bronze", ANP_PARSER_VERSION,
            f"anp-bronze-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            options.trigger_type, options.source_reference, options.git_commit,
        )
        run_ids.append(str(bronze_run))
        try:
            with tempfile.TemporaryDirectory(prefix="sigra-anp-") as temporary:
                asset = client.download(
                    source_reference=options.source_reference,
                    official_page_url=official_page,
                    download_url=download_url,
                    filename=filename,
                    destination_directory=Path(temporary),
                )
                try:
                    parsed = parser.parse(asset)
                except AnpLayoutDriftError as exc:
                    quarantined = ParsedAnpAsset(
                        asset=asset,
                        layout_fingerprint=exc.fingerprint,
                        period_start=None,
                        period_end=None,
                        rows=(),
                        ingestion_status="quarantined",
                        error_sanitized="ANP CSV layout drift requires schema review",
                        technical_metadata={
                            "parser_version": ANP_PARSER_VERSION,
                            "storage_mode": "metadata_only",
                        },
                    )
                    loader.persist_bronze(bronze_run, quarantined)
                    raise
                parsed, bronze_inserted, bronze_deduplicated = loader.persist_bronze(bronze_run, parsed)
                notify("bronze:accepted")
            loader.finish_run(
                bronze_run, "succeeded", received=len(parsed.rows),
                inserted=bronze_inserted, deduplicated=bronze_deduplicated,
                rejected=0,
            )
        except AnpAssetCorrectionError as exc:
            loader.finish_run(
                bronze_run, "failed", received=exc.received,
                inserted=exc.inserted, deduplicated=exc.deduplicated,
                rejected=exc.received, error=sanitize(exc),
            )
            raise
        except Exception as exc:
            loader.finish_run(bronze_run, "failed", received=0, inserted=0,
                              deduplicated=0, rejected=0, error=sanitize(exc))
            raise

        silver_run = loader.start_run(
            "anp_fuel_prices_silver", ANP_NORMALIZER_VERSION,
            f"anp-silver-{parsed.asset.sha256[:16]}", options.trigger_type,
            options.source_reference, options.git_commit,
        )
        run_ids.append(str(silver_run))
        try:
            batch = transform_asset(parsed)
            current, silver_inserted, silver_deduplicated, all_issues = loader.persist_silver(
                silver_run, batch.observations, batch.issues,
            )
            loader.finish_run(
                silver_run, "succeeded", received=len(parsed.rows),
                inserted=silver_inserted,
                deduplicated=silver_deduplicated + batch.deduplicated_count,
                rejected=batch.rejected_count,
            )
            notify("silver:normalized")
        except Exception as exc:
            loader.finish_run(silver_run, "failed", received=0, inserted=0,
                              deduplicated=0, rejected=0, error=sanitize(exc))
            raise

        gold_run = loader.start_run(
            "anp_fuel_prices_gold_shadow", ANP_AGGREGATION_VERSION,
            f"anp-shadow-building-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            options.trigger_type, options.source_reference, options.git_commit,
        )
        run_ids.append(str(gold_run))
        try:
            if parsed.period_start is None or parsed.period_end is None:
                raise ValueError("accepted ANP asset has no valid reference period")
            snapshots = build_snapshots(current, reference_period_end=parsed.period_end)
            quality_results = evaluate_quality(current, snapshots, all_issues)
            require_hard_gates(quality_results)
            manifest = ({
                "asset_id": parsed.asset_id,
                "source_reference": parsed.asset.source_reference,
                "sha256": parsed.asset.sha256,
                "schema_fingerprint": parsed.layout_fingerprint,
                "period_start": parsed.period_start.isoformat(),
                "period_end": parsed.period_end.isoformat(),
                "byte_length": parsed.asset.byte_length,
                "storage_mode": "metadata_only",
            },)
            dataset_version, deduplicated = loader.publish_shadow(
                gold_run, asset_manifest=manifest, observations=current,
                snapshots=snapshots, quality_results=quality_results,
                reference_period_start=parsed.period_start,
                reference_period_end=parsed.period_end,
            )
            loader.finish_run(
                gold_run, "succeeded", received=len(current),
                inserted=0 if deduplicated else len(snapshots),
                deduplicated=len(snapshots) if deduplicated else 0,
                rejected=0,
            )
            notify("gold:shadow_published")
            return AnpPipelineResult(
                "deduplicated" if deduplicated else "succeeded",
                dataset_version, tuple(run_ids), parsed.asset.sha256,
                parsed.layout_fingerprint, len(parsed.rows), len(current),
                len(snapshots), len(all_issues),
            )
        except Exception as exc:
            loader.finish_run(gold_run, "failed", received=0, inserted=0,
                              deduplicated=0, rejected=0, error=sanitize(exc))
            raise
