from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import tempfile
from pathlib import Path
from typing import Callable

from data_platform.carpedia.loader import CarpediaVehicleSpecsLoader
from data_platform.common.logging import sanitize
from data_platform.contracts.carpedia_vehicle_specs import (
    CARPEDIA_ATTRIBUTION,
    CARPEDIA_LICENSE_STATUS,
    CARPEDIA_OFFICIAL_BASE_URL,
    CarpediaMappingStatus,
    CarpediaPipelineResult,
    CarpediaRequest,
    CarpediaTarget,
)
from data_platform.ingestion.carpedia.client import CarpediaApiClient
from data_platform.ingestion.carpedia.parser import CarpediaJsonParser
from data_platform.quality.carpedia_checks import (
    build_snapshots,
    evaluate_quality,
    require_hard_gates,
)
from data_platform.transformation.carpedia import build_specification


@dataclass(frozen=True)
class CarpediaExecutionOptions:
    targets: tuple[CarpediaTarget, ...] = ()
    dry_run: bool = False
    trigger_type: str = "manual"
    git_commit: str | None = None


def _request(target: CarpediaTarget) -> CarpediaRequest:
    return CarpediaRequest(
        logical_endpoint="vehicle_specification",
        path=f"/api/v1/ficha/{target.external_vehicle_id}/{target.model_year}",
        external_vehicle_id=target.external_vehicle_id,
        source_reference=target.source_reference,
    )


def _dry_run_result(options: CarpediaExecutionOptions) -> CarpediaPipelineResult:
    # Deliberadamente puro: não resolve ambiente, não abre banco, não chama rede,
    # não adquire lock e não grava arquivos.
    return CarpediaPipelineResult(
        status="planned",
        dataset_version=None,
        pipeline_run_id=None,
        targets=len(options.targets),
        records_received=0,
        matched=0,
        ambiguous=0,
        rejected=0,
        not_found=0,
        pending=0,
        snapshots_published=0,
        plan={
            "source": CARPEDIA_OFFICIAL_BASE_URL,
            "license_status": CARPEDIA_LICENSE_STATUS,
            "attribution": CARPEDIA_ATTRIBUTION,
            "publication_mode": "shadow",
            "storage_mode": "database_json",
            "targets": sorted(target.source_reference for target in options.targets),
        },
    )


def run_carpedia_pipeline(
    loader: CarpediaVehicleSpecsLoader | None,
    client: CarpediaApiClient | None,
    options: CarpediaExecutionOptions | None = None,
    *,
    parser_factory: Callable[[], CarpediaJsonParser] = CarpediaJsonParser,
) -> CarpediaPipelineResult:
    options = options or CarpediaExecutionOptions()
    if options.dry_run:
        return _dry_run_result(options)
    if loader is None or client is None:
        raise ValueError("Carpedia loader and client are required outside dry-run")
    if not options.targets:
        raise ValueError("Carpedia execution requires explicit official vehicle targets")
    if len({target.source_reference for target in options.targets}) != len(options.targets):
        raise ValueError("Carpedia targets contain duplicate external identities")
    ordered_targets = tuple(
        sorted(options.targets, key=lambda item: (item.external_vehicle_id, item.model_year))
    )

    run_id = loader.start_run(
        "carpedia-shadow-building",
        options.trigger_type,
        options.git_commit,
    )
    inserted = deduplicated = 0
    persisted = []
    asset_manifest = []
    try:
        parser = parser_factory()
        with loader.source_lock(), tempfile.TemporaryDirectory(prefix="sigra-carpedia-") as temporary:
            directory = Path(temporary)
            for target in ordered_targets:
                asset = client.fetch(_request(target), destination_directory=directory)
                parsed = parser.parse(asset)
                parsed, bronze_inserted = loader.persist_bronze(run_id, parsed)
                inserted += int(bronze_inserted)
                deduplicated += int(not bronze_inserted)
                candidates = loader.identity_candidates(parsed)
                specification = build_specification(parsed, candidates)
                specification, silver_inserted = loader.persist_silver(run_id, specification)
                inserted += int(silver_inserted)
                deduplicated += int(not silver_inserted)
                persisted.append(specification)
                asset_manifest.append(
                    {
                        "logical_endpoint": asset.request.logical_endpoint,
                        "external_vehicle_id": parsed.raw.external_vehicle_id,
                        "source_reference": parsed.source_reference,
                        "sha256": asset.sha256,
                        "byte_length": asset.byte_length,
                    }
                )

            specifications = tuple(persisted)
            snapshots = build_snapshots(specifications)
            lineage_evidence = loader.audit_lineage(specifications, snapshots)
            quality_results = evaluate_quality(
                specifications,
                snapshots,
                lineage_evidence=lineage_evidence,
            )
            require_hard_gates(quality_results)
            dataset_version, was_deduplicated = loader.publish_shadow(
                run_id,
                asset_manifest=tuple(asset_manifest),
                specifications=specifications,
                snapshots=snapshots,
                quality_results=quality_results,
            )

        distribution = Counter(item.mapping.status for item in specifications)
        loader.finish_run(
            run_id,
            "succeeded",
            received=len(specifications),
            inserted=inserted,
            deduplicated=deduplicated + int(was_deduplicated),
            rejected=len(specifications) - distribution[CarpediaMappingStatus.MATCHED],
        )
        return CarpediaPipelineResult(
            status="deduplicated" if was_deduplicated else "succeeded",
            dataset_version=dataset_version,
            pipeline_run_id=str(run_id),
            targets=len(options.targets),
            records_received=len(specifications),
            matched=distribution[CarpediaMappingStatus.MATCHED],
            ambiguous=distribution[CarpediaMappingStatus.AMBIGUOUS],
            rejected=distribution[CarpediaMappingStatus.REJECTED],
            not_found=distribution[CarpediaMappingStatus.NOT_FOUND],
            pending=distribution[CarpediaMappingStatus.PENDING],
            snapshots_published=len(snapshots),
        )
    except Exception as exc:
        loader.finish_run(
            run_id,
            "failed",
            received=len(persisted),
            inserted=inserted,
            deduplicated=deduplicated,
            rejected=max(0, len(options.targets) - len(persisted)),
            error=sanitize(exc),
        )
        raise


__all__ = ["CarpediaExecutionOptions", "run_carpedia_pipeline"]
