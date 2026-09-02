from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Iterable, Iterator, Mapping, Sequence
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from data_platform.common.logging import sanitize
from data_platform.contracts.carpedia_vehicle_specs import (
    CARPEDIA_CONTRACT_VERSION,
    CARPEDIA_LICENSE_STATUS,
    CARPEDIA_MATCHER_VERSION,
    CARPEDIA_NORMALIZER_VERSION,
    CARPEDIA_PARSER_VERSION,
    CARPEDIA_PUBLICATION_VERSION,
    CARPEDIA_SOURCE_NAME,
    CarpediaMappingStatus,
    CarpediaQualityIssue,
    CarpediaQualityResult,
    CarpediaSnapshot,
    CarpediaSpecification,
    ParsedCarpediaSpecification,
    VehicleIdentityCandidate,
)


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda item: item.isoformat() if isinstance(item, (date, datetime)) else str(item),
    )


def _event_fingerprint(
    event_type: str,
    dataset_version: str,
    related_dataset_version: str | None,
    reason: str,
) -> str:
    return hashlib.sha256(
        _json([event_type, dataset_version, related_dataset_version, reason]).encode("utf-8")
    ).hexdigest()


def _mapping_decision_is_valid(
    status: object,
    vehicle_sk: object,
    confidence: object,
    review_required: object,
) -> bool:
    try:
        normalized_status = CarpediaMappingStatus(str(status))
    except ValueError:
        return False
    if normalized_status == CarpediaMappingStatus.MATCHED:
        try:
            normalized_confidence = Decimal(str(confidence))
        except (InvalidOperation, ValueError):
            return False
        return (
            vehicle_sk is not None
            and normalized_confidence == Decimal("100")
            and not bool(review_required)
        )
    return vehicle_sk is None


def _mapping_decision_is_publishable(
    status: object,
    vehicle_sk: object,
    confidence: object,
    review_required: object,
) -> bool:
    return (
        str(status) == CarpediaMappingStatus.MATCHED.value
        and _mapping_decision_is_valid(status, vehicle_sk, confidence, review_required)
    )


def _same_mapping_decision(
    prior_mapping: Mapping[str, object] | None,
    specification: CarpediaSpecification,
) -> bool:
    mapping = specification.mapping
    return prior_mapping is not None and (
        str(prior_mapping["mapping_status"]) == mapping.status.value
        and str(prior_mapping["match_method"]) == mapping.match_method
        and prior_mapping["vehicle_sk"] == mapping.vehicle_sk
        and prior_mapping["confidence"] == mapping.confidence
        and bool(prior_mapping["review_required"]) == mapping.review_required
        and str(prior_mapping["matcher_version"]) == CARPEDIA_MATCHER_VERSION
        and _json(prior_mapping["identity_evidence"]) == _json(mapping.identity_evidence)
        and _json(prior_mapping["candidate_evidence"]) == _json(mapping.candidate_evidence)
        and str(prior_mapping["decision_reason"]) == mapping.decision_reason
        and _mapping_decision_is_valid(
            prior_mapping["mapping_status"],
            prior_mapping["vehicle_sk"],
            prior_mapping["confidence"],
            prior_mapping["review_required"],
        )
    )


def _can_reuse_specification(
    prior_specification: Mapping[str, object] | None,
    mapping_decision_id: int,
    specification: CarpediaSpecification,
) -> bool:
    mapping = specification.mapping
    return prior_specification is not None and (
        str(prior_specification["normalized_fingerprint"])
        == specification.normalized_fingerprint
        and int(prior_specification["mapping_decision_id"]) == mapping_decision_id
        and prior_specification["vehicle_sk"] == mapping.vehicle_sk
        and str(prior_specification["mapping_status"]) == mapping.status.value
        and _mapping_decision_is_valid(
            mapping.status.value,
            mapping.vehicle_sk,
            mapping.confidence,
            mapping.review_required,
        )
    )


class CarpediaVehicleSpecsLoader:
    def __init__(self, engine: Engine) -> None:
        if engine.dialect.name != "postgresql":
            raise ValueError("Carpedia persistence requires PostgreSQL")
        self.engine = engine

    @contextmanager
    def source_lock(self) -> Iterator[None]:
        connection = self.engine.connect()
        try:
            connection.execute(text("SELECT pg_advisory_lock(hashtext('carpedia:vehicle-specs')::bigint)"))
            connection.commit()
            yield
        finally:
            try:
                connection.execute(text("SELECT pg_advisory_unlock(hashtext('carpedia:vehicle-specs')::bigint)"))
                connection.commit()
            finally:
                connection.close()

    def start_run(self, dataset_version: str, trigger_type: str, git_commit: str | None) -> UUID:
        run_id = uuid4()
        with self.engine.begin() as connection:
            connection.execute(
                text("""INSERT INTO meta.pipeline_run
                    (pipeline_run_id,pipeline_name,pipeline_version,dataset_version,
                     trigger_type,status,started_at,source_reference,git_commit)
                    VALUES (:run,'carpedia_vehicle_specs_shadow',:version,:dataset,
                            :trigger,'running',clock_timestamp(),'carpedia-api-v1',:git)"""),
                {
                    "run": run_id,
                    "version": CARPEDIA_PUBLICATION_VERSION,
                    "dataset": dataset_version,
                    "trigger": trigger_type,
                    "git": git_commit,
                },
            )
        return run_id

    def finish_run(
        self,
        run_id: UUID,
        status: str,
        *,
        received: int,
        inserted: int,
        deduplicated: int,
        rejected: int,
        error: object | None = None,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text("""UPDATE meta.pipeline_run SET status=:status,
                    finished_at=clock_timestamp(),records_received=:received,
                    records_inserted=:inserted,records_deduplicated=:deduplicated,
                    records_rejected=:rejected,error_summary=:error
                    WHERE pipeline_run_id=:run"""),
                {
                    "run": run_id,
                    "status": status,
                    "received": received,
                    "inserted": inserted,
                    "deduplicated": deduplicated,
                    "rejected": rejected,
                    "error": sanitize(error) if error is not None else None,
                },
            )

    def identity_candidates(
        self,
        parsed: ParsedCarpediaSpecification,
    ) -> tuple[VehicleIdentityCandidate, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text("""SELECT vehicle_sk,brand_name,model_name,version_name,
                    model_year,is_zero_km,fuel_type
                    FROM silver.vehicle_identity
                    WHERE is_current AND vehicle_type='car' AND model_year=:year"""),
                {"year": parsed.model_year},
            ).mappings().all()
        return tuple(
            VehicleIdentityCandidate(
                vehicle_sk=int(row["vehicle_sk"]),
                brand_name=str(row["brand_name"]),
                model_name=str(row["model_name"]),
                version_name=row["version_name"],
                model_year=row["model_year"],
                is_zero_km=bool(row["is_zero_km"]),
                fuel_type=str(row["fuel_type"]),
            )
            for row in rows
        )

    @staticmethod
    def _audit_lineage_with_connection(
        connection: Connection,
        specifications: Sequence[CarpediaSpecification],
        snapshots: Sequence[CarpediaSnapshot],
    ) -> Mapping[str, object]:
        issues: list[str] = []
        rows_by_specification: dict[int, Mapping[str, object]] = {}
        specifications_by_id: dict[int, CarpediaSpecification] = {}
        for specification in specifications:
            mapping_id = specification.mapping.mapping_decision_id
            specification_id = specification.specification_id
            if mapping_id is None or specification_id is None:
                issues.append("missing_persisted_lineage")
                continue
            if specification_id in specifications_by_id:
                issues.append("duplicate_specification_lineage")
                continue
            specifications_by_id[specification_id] = specification
            row = connection.execute(
                text("""SELECT
                    specification.specification_id,
                    specification.raw_record_id AS specification_raw_record_id,
                    specification.mapping_decision_id AS specification_mapping_decision_id,
                    specification.vehicle_sk AS specification_vehicle_sk,
                    specification.mapping_status AS specification_mapping_status,
                    mapping.mapping_decision_id,
                    mapping.raw_record_id AS mapping_raw_record_id,
                    mapping.vehicle_sk AS mapping_vehicle_sk,
                    mapping.mapping_status,
                    mapping.confidence,
                    mapping.review_required,
                    NOT EXISTS (
                      SELECT 1 FROM silver.carpedia_vehicle_specification AS successor
                      WHERE successor.supersedes_specification_id=specification.specification_id
                    ) AS specification_current,
                    NOT EXISTS (
                      SELECT 1 FROM silver.carpedia_vehicle_mapping AS successor
                      WHERE successor.supersedes_mapping_id=mapping.mapping_decision_id
                    ) AS mapping_current
                    FROM silver.carpedia_vehicle_specification AS specification
                    JOIN silver.carpedia_vehicle_mapping AS mapping
                      ON mapping.mapping_decision_id=specification.mapping_decision_id
                    WHERE specification.specification_id=:specification"""),
                {"specification": specification_id},
            ).mappings().one_or_none()
            if row is None:
                issues.append("persisted_lineage_not_found")
                continue
            rows_by_specification[specification_id] = row
            if (
                int(row["specification_mapping_decision_id"]) != mapping_id
                or int(row["mapping_decision_id"]) != mapping_id
                or row["specification_raw_record_id"] != row["mapping_raw_record_id"]
                or row["specification_vehicle_sk"] != specification.mapping.vehicle_sk
                or row["mapping_vehicle_sk"] != specification.mapping.vehicle_sk
                or str(row["specification_mapping_status"]) != specification.mapping.status.value
                or str(row["mapping_status"]) != specification.mapping.status.value
            ):
                issues.append("persisted_identity_mismatch")
            if not bool(row["specification_current"]) or not bool(row["mapping_current"]):
                issues.append("superseded_lineage")
            if not _mapping_decision_is_valid(
                row["mapping_status"],
                row["mapping_vehicle_sk"],
                row["confidence"],
                row["review_required"],
            ):
                issues.append("invalid_mapping_decision")

        publishable_snapshots = 0
        for snapshot in snapshots:
            specification = specifications_by_id.get(snapshot.specification_id)
            row = rows_by_specification.get(snapshot.specification_id)
            if specification is None or row is None:
                issues.append("snapshot_specification_not_found")
                continue
            if (
                snapshot.vehicle_sk != specification.mapping.vehicle_sk
                or snapshot.vehicle_sk != row["specification_vehicle_sk"]
                or snapshot.vehicle_sk != row["mapping_vehicle_sk"]
                or not _mapping_decision_is_publishable(
                    row["mapping_status"],
                    row["mapping_vehicle_sk"],
                    row["confidence"],
                    row["review_required"],
                )
            ):
                issues.append("snapshot_identity_not_publishable")
                continue
            publishable_snapshots += 1
        unique_issues = tuple(sorted(set(issues)))
        return {
            "coherent": not unique_issues,
            "specifications": len(specifications),
            "snapshots": len(snapshots),
            "publishable_snapshots": publishable_snapshots,
            "issue_codes": unique_issues,
        }

    def audit_lineage(
        self,
        specifications: Sequence[CarpediaSpecification],
        snapshots: Sequence[CarpediaSnapshot],
    ) -> Mapping[str, object]:
        with self.engine.connect() as connection:
            return self._audit_lineage_with_connection(connection, specifications, snapshots)

    def persist_bronze(
        self,
        run_id: UUID,
        parsed: ParsedCarpediaSpecification,
    ) -> tuple[ParsedCarpediaSpecification, bool]:
        with self.engine.begin() as connection:
            asset_id = connection.execute(
                text("""INSERT INTO bronze.carpedia_source_asset
                    (pipeline_run_id,source_name,logical_endpoint,external_vehicle_id,
                     source_reference,endpoint_path,collected_at,http_status,
                     content_type,byte_length,sha256,schema_fingerprint,
                     contract_version,license_status,storage_mode,payload_sanitized,
                     ingestion_status,error_sanitized,technical_metadata)
                    VALUES (:run,:source,:logical,:external,:reference,:path,:collected,
                            :http,:content_type,:size,:sha,:schema,:contract,:license,
                            'database_json',CAST(:payload AS jsonb),'accepted',NULL,
                            CAST(:metadata AS jsonb))
                    ON CONFLICT (logical_endpoint,external_vehicle_id,source_reference,sha256)
                    DO NOTHING RETURNING asset_id"""),
                {
                    "run": run_id,
                    "source": CARPEDIA_SOURCE_NAME,
                    "logical": parsed.asset.request.logical_endpoint,
                    "external": parsed.raw.external_vehicle_id,
                    "reference": parsed.source_reference,
                    "path": parsed.asset.request.path,
                    "collected": parsed.asset.collected_at,
                    "http": parsed.asset.http_status,
                    "content_type": parsed.asset.content_type,
                    "size": parsed.asset.byte_length,
                    "sha": parsed.asset.sha256,
                    "schema": parsed.schema_fingerprint,
                    "contract": CARPEDIA_CONTRACT_VERSION,
                    "license": CARPEDIA_LICENSE_STATUS,
                    "payload": _json(parsed.raw.payload),
                    "metadata": _json({
                        "parser_version": CARPEDIA_PARSER_VERSION,
                        "attribution_required": True,
                        "redistribution": "catalog_mass_redistribution_forbidden",
                    }),
                },
            ).scalar_one_or_none()
            inserted = asset_id is not None
            if asset_id is None:
                asset_id = connection.execute(
                    text("""SELECT asset_id FROM bronze.carpedia_source_asset
                        WHERE logical_endpoint=:logical AND external_vehicle_id=:external
                          AND source_reference=:reference AND sha256=:sha"""),
                    {
                        "logical": parsed.asset.request.logical_endpoint,
                        "external": parsed.raw.external_vehicle_id,
                        "reference": parsed.source_reference,
                        "sha": parsed.asset.sha256,
                    },
                ).scalar_one()
            raw_id = connection.execute(
                text("""INSERT INTO bronze.carpedia_vehicle_raw
                    (asset_id,pipeline_run_id,external_vehicle_id,model_year,
                     parser_version,source_record_key,raw_payload,row_hash,
                     parsing_status,error_sanitized,parsed_at)
                    VALUES (:asset,:run,:external,:year,:parser,:key,
                            CAST(:payload AS jsonb),:hash,'parsed',NULL,:parsed)
                    ON CONFLICT (asset_id,source_record_key) DO NOTHING
                    RETURNING raw_record_id"""),
                {
                    "asset": asset_id,
                    "run": run_id,
                    "external": parsed.raw.external_vehicle_id,
                    "year": parsed.raw.model_year,
                    "parser": CARPEDIA_PARSER_VERSION,
                    "key": parsed.raw.source_record_key,
                    "payload": _json(parsed.raw.payload),
                    "hash": parsed.raw.row_hash,
                    "parsed": parsed.raw.parsed_at,
                },
            ).scalar_one_or_none()
            if raw_id is None:
                raw_id = connection.execute(
                    text("""SELECT raw_record_id FROM bronze.carpedia_vehicle_raw
                        WHERE asset_id=:asset AND source_record_key=:key"""),
                    {"asset": asset_id, "key": parsed.raw.source_record_key},
                ).scalar_one()
        persisted_raw = replace(
            parsed.raw,
            asset_id=int(asset_id),
            raw_record_id=int(raw_id),
            pipeline_run_id=run_id,
        )
        return replace(parsed, raw=persisted_raw), inserted

    def persist_silver(
        self,
        run_id: UUID,
        specification: CarpediaSpecification,
        issues: Iterable[CarpediaQualityIssue] = (),
    ) -> tuple[CarpediaSpecification, bool]:
        raw_id = specification.parsed.raw.raw_record_id
        if raw_id is None:
            raise ValueError("Carpedia Silver requires persisted Bronze lineage")
        with self.engine.begin() as connection:
            prior_mapping = connection.execute(
                text("""SELECT mapping_decision_id,mapping_status,match_method,
                    vehicle_sk,confidence,review_required,matcher_version,
                    identity_evidence,candidate_evidence,decision_reason
                    FROM silver.carpedia_vehicle_mapping_current
                    WHERE raw_record_id=:raw"""),
                {"raw": raw_id},
            ).mappings().one_or_none()
            same_mapping = _same_mapping_decision(prior_mapping, specification)
            if same_mapping:
                mapping_id = int(prior_mapping["mapping_decision_id"])
                persisted_mapping = replace(specification.mapping, mapping_decision_id=mapping_id)
            else:
                mapping_id = int(connection.execute(
                    text("""INSERT INTO silver.carpedia_vehicle_mapping
                        (raw_record_id,pipeline_run_id,vehicle_sk,mapping_status,
                         match_method,confidence,review_required,matcher_version,
                         identity_evidence,candidate_evidence,decision_reason,
                         effective_at,supersedes_mapping_id)
                        VALUES (:raw,:run,:vehicle,:status,:method,:confidence,:review,
                                :matcher,CAST(:identity AS jsonb),CAST(:candidates AS jsonb),
                                :reason,clock_timestamp(),:supersedes)
                        RETURNING mapping_decision_id"""),
                    {
                        "raw": raw_id,
                        "run": run_id,
                        "vehicle": specification.mapping.vehicle_sk,
                        "status": specification.mapping.status.value,
                        "method": specification.mapping.match_method,
                        "confidence": specification.mapping.confidence,
                        "review": specification.mapping.review_required,
                        "matcher": CARPEDIA_MATCHER_VERSION,
                        "identity": _json(specification.mapping.identity_evidence),
                        "candidates": _json(specification.mapping.candidate_evidence),
                        "reason": specification.mapping.decision_reason,
                        "supersedes": int(prior_mapping["mapping_decision_id"]) if prior_mapping else None,
                    },
                ).scalar_one())
                persisted_mapping = replace(
                    specification.mapping,
                    mapping_decision_id=mapping_id,
                    supersedes_mapping_id=int(prior_mapping["mapping_decision_id"]) if prior_mapping else None,
                )
            prior_spec = connection.execute(
                text("""SELECT specification_id,normalized_fingerprint,
                    mapping_decision_id,vehicle_sk,mapping_status
                    FROM silver.carpedia_vehicle_specification_current
                    WHERE external_vehicle_id=:external AND model_year=:year"""),
                {
                    "external": specification.parsed.raw.external_vehicle_id,
                    "year": specification.parsed.model_year,
                },
            ).mappings().one_or_none()
            if _can_reuse_specification(prior_spec, mapping_id, specification):
                specification_id = int(prior_spec["specification_id"])
                inserted = False
                supersedes_specification_id = None
            else:
                supersedes_specification_id = int(prior_spec["specification_id"]) if prior_spec else None
                specification_id = int(connection.execute(
                    text("""INSERT INTO silver.carpedia_vehicle_specification
                        (raw_record_id,mapping_decision_id,pipeline_run_id,vehicle_sk,
                         external_vehicle_id,source_reference,brand_name,model_name,
                         version_name,model_year,mapping_status,attributes,
                         attribute_provenance,source_fingerprint,normalized_fingerprint,
                         quality_status,observed_at,supersedes_specification_id)
                        VALUES (:raw,:mapping,:run,:vehicle,:external,:reference,:brand,
                                :model,:version,:year,:mapping_status,CAST(:attributes AS jsonb),
                                CAST(:provenance AS jsonb),:source_hash,:normalized_hash,
                                :quality,:observed,:supersedes)
                        RETURNING specification_id"""),
                    {
                        "raw": raw_id,
                        "mapping": mapping_id,
                        "run": run_id,
                        "vehicle": persisted_mapping.vehicle_sk,
                        "external": specification.parsed.raw.external_vehicle_id,
                        "reference": specification.parsed.source_reference,
                        "brand": specification.parsed.brand_name,
                        "model": specification.parsed.model_name,
                        "version": specification.parsed.version_name,
                        "year": specification.parsed.model_year,
                        "mapping_status": persisted_mapping.status.value,
                        "attributes": _json(specification.attributes),
                        "provenance": _json(specification.attribute_provenance),
                        "source_hash": specification.source_fingerprint,
                        "normalized_hash": specification.normalized_fingerprint,
                        "quality": specification.quality_status,
                        "observed": specification.parsed.asset.collected_at,
                        "supersedes": supersedes_specification_id,
                    },
                ).scalar_one())
                inserted = True
            self._persist_issues(connection, run_id, issues)
        return replace(
            specification,
            mapping=persisted_mapping,
            specification_id=specification_id,
            supersedes_specification_id=supersedes_specification_id,
        ), inserted

    @staticmethod
    def _persist_issues(
        connection: Connection,
        run_id: UUID,
        issues: Iterable[CarpediaQualityIssue],
    ) -> None:
        for issue in issues:
            connection.execute(
                text("""INSERT INTO meta.data_quality_issue
                    (pipeline_run_id,layer_name,entity_name,record_reference,
                     rule_code,severity,message,details,resolution_status)
                    VALUES (:run,:layer,'carpedia_vehicle_specs',:reference,:rule,
                            :severity,:message,CAST(:details AS jsonb),'open')
                    ON CONFLICT DO NOTHING"""),
                {
                    "run": run_id,
                    "layer": issue.layer_name,
                    "reference": issue.record_reference,
                    "rule": issue.rule_code,
                    "severity": issue.severity,
                    "message": sanitize(issue.message),
                    "details": _json(issue.details),
                },
            )

    def publish_shadow(
        self,
        run_id: UUID,
        *,
        asset_manifest: Sequence[Mapping[str, object]],
        specifications: Sequence[CarpediaSpecification],
        snapshots: Sequence[CarpediaSnapshot],
        quality_results: Sequence[CarpediaQualityResult],
    ) -> tuple[str, bool]:
        if not specifications or not snapshots:
            raise ValueError("empty Carpedia Gold shadow is forbidden")
        matched_specifications = tuple(
            item for item in specifications
            if item.mapping.status == CarpediaMappingStatus.MATCHED
        )
        if len(matched_specifications) != len(snapshots):
            raise ValueError("Carpedia matched Silver and Gold snapshot counts differ")
        if any(item.severity == "critical" and item.status != "passed" for item in quality_results):
            raise ValueError("Carpedia Gold shadow hard gates failed")
        if len({item.vehicle_sk for item in snapshots}) != len(snapshots):
            raise ValueError("Carpedia Gold shadow contains duplicate vehicle grains")
        fingerprint_payload = {
            "assets": asset_manifest,
            "parser": CARPEDIA_PARSER_VERSION,
            "normalizer": CARPEDIA_NORMALIZER_VERSION,
            "matcher": CARPEDIA_MATCHER_VERSION,
            "publication": CARPEDIA_PUBLICATION_VERSION,
            "snapshots": [item.snapshot_fingerprint for item in snapshots],
        }
        fingerprint = hashlib.sha256(_json(fingerprint_payload).encode("utf-8")).hexdigest()
        dataset_version = f"carpedia-shadow-v1-{fingerprint[:24]}"
        with self.engine.begin() as connection:
            connection.execute(text("SELECT meta.assert_carpedia_lineage_consistent()"))
            lineage = self._audit_lineage_with_connection(
                connection,
                specifications,
                snapshots,
            )
            if not bool(lineage["coherent"]):
                raise ValueError("Carpedia Silver-to-Gold lineage is inconsistent")
            active = connection.execute(
                text("""SELECT dataset_version,dataset_fingerprint
                    FROM gold.carpedia_vehicle_spec_dataset
                    WHERE is_active_shadow FOR UPDATE""")
            ).mappings().one_or_none()
            if active is not None and active["dataset_fingerprint"] == fingerprint:
                connection.execute(
                    text("UPDATE meta.pipeline_run SET dataset_version=:dataset WHERE pipeline_run_id=:run"),
                    {"dataset": active["dataset_version"], "run": run_id},
                )
                return str(active["dataset_version"]), True
            connection.execute(
                text("""INSERT INTO gold.carpedia_vehicle_spec_dataset
                    (dataset_version,publication_run_id,source_asset_manifest,
                     parser_version,normalizer_version,matcher_version,
                     publication_version,status,is_active_shadow,source_record_count,
                     matched_count,snapshot_count,dataset_fingerprint,quality_status,
                     supersedes_dataset_version)
                    VALUES (:dataset,:run,CAST(:manifest AS jsonb),:parser,:normalizer,
                            :matcher,:publication,'building',FALSE,:records,:matched,
                            :snapshots,:fingerprint,'passed',:supersedes)"""),
                {
                    "dataset": dataset_version,
                    "run": run_id,
                    "manifest": _json(asset_manifest),
                    "parser": CARPEDIA_PARSER_VERSION,
                    "normalizer": CARPEDIA_NORMALIZER_VERSION,
                    "matcher": CARPEDIA_MATCHER_VERSION,
                    "publication": CARPEDIA_PUBLICATION_VERSION,
                    "records": len(specifications),
                    "matched": len(matched_specifications),
                    "snapshots": len(snapshots),
                    "fingerprint": fingerprint,
                    "supersedes": active["dataset_version"] if active else None,
                },
            )
            for item in snapshots:
                connection.execute(
                    text("""INSERT INTO gold.carpedia_vehicle_spec_snapshot
                        (dataset_version,publication_run_id,vehicle_sk,specification_id,
                         external_vehicle_id,source_reference,model_year,attributes,
                         attribute_provenance,quality_status,snapshot_fingerprint)
                        VALUES (:dataset,:run,:vehicle,:specification,:external,
                                :reference,:year,CAST(:attributes AS jsonb),
                                CAST(:provenance AS jsonb),'passed',:fingerprint)"""),
                    {
                        "dataset": dataset_version,
                        "run": run_id,
                        "vehicle": item.vehicle_sk,
                        "specification": item.specification_id,
                        "external": item.external_vehicle_id,
                        "reference": item.source_reference,
                        "year": item.model_year,
                        "attributes": _json(item.attributes),
                        "provenance": _json(item.attribute_provenance),
                        "fingerprint": item.snapshot_fingerprint,
                    },
                )
            for result in quality_results:
                connection.execute(
                    text("""INSERT INTO gold.carpedia_vehicle_spec_quality_result
                        (dataset_version,pipeline_run_id,rule_code,severity,status,
                         observed_value,expected_condition,details,evaluated_at)
                        VALUES (:dataset,:run,:rule,:severity,:status,
                                CAST(:observed AS jsonb),:expected,
                                CAST(:details AS jsonb),clock_timestamp())"""),
                    {
                        "dataset": dataset_version,
                        "run": run_id,
                        "rule": result.rule_code,
                        "severity": result.severity,
                        "status": result.status,
                        "observed": _json(result.observed_value),
                        "expected": result.expected_condition,
                        "details": _json(result.details),
                    },
                )
            if active is not None:
                connection.execute(
                    text("""UPDATE gold.carpedia_vehicle_spec_dataset
                        SET status='retired',is_active_shadow=FALSE,
                            retired_at=clock_timestamp()
                        WHERE dataset_version=:dataset"""),
                    {"dataset": active["dataset_version"]},
                )
                self._insert_event(
                    connection,
                    run_id,
                    str(active["dataset_version"]),
                    "superseded",
                    dataset_version,
                    "superseded by a newly validated Carpedia shadow dataset",
                )
            connection.execute(
                text("""UPDATE gold.carpedia_vehicle_spec_dataset
                    SET status='shadow_published',is_active_shadow=TRUE,
                        published_at=clock_timestamp()
                    WHERE dataset_version=:dataset"""),
                {"dataset": dataset_version},
            )
            self._insert_event(
                connection,
                run_id,
                dataset_version,
                "activated",
                str(active["dataset_version"]) if active else None,
                "validated Carpedia dataset activated in shadow mode",
            )
            connection.execute(
                text("UPDATE meta.pipeline_run SET dataset_version=:dataset WHERE pipeline_run_id=:run"),
                {"dataset": dataset_version, "run": run_id},
            )
        return dataset_version, False

    @staticmethod
    def _insert_event(
        connection: Connection,
        run_id: UUID,
        dataset_version: str,
        event_type: str,
        related_dataset_version: str | None,
        reason: str,
    ) -> None:
        connection.execute(
            text("""INSERT INTO gold.carpedia_vehicle_spec_dataset_event
                (dataset_version,pipeline_run_id,event_type,related_dataset_version,
                 reason,event_fingerprint,occurred_at)
                VALUES (:dataset,:run,:event,:related,:reason,:fingerprint,
                        clock_timestamp())"""),
            {
                "dataset": dataset_version,
                "run": run_id,
                "event": event_type,
                "related": related_dataset_version,
                "reason": reason,
                "fingerprint": _event_fingerprint(event_type, dataset_version, related_dataset_version, reason),
            },
        )

    def invalidate_shadow(self, run_id: UUID, dataset_version: str, reason: str) -> None:
        clean_reason = sanitize(reason)
        if not clean_reason.strip():
            raise ValueError("Carpedia invalidation requires a reason")
        with self.engine.begin() as connection:
            updated = connection.execute(
                text("""UPDATE gold.carpedia_vehicle_spec_dataset
                    SET status='invalidated',is_active_shadow=FALSE,
                        invalidated_at=clock_timestamp(),invalidation_reason=:reason
                    WHERE dataset_version=:dataset AND status='shadow_published'
                      AND is_active_shadow RETURNING dataset_version"""),
                {"dataset": dataset_version, "reason": clean_reason},
            ).scalar_one_or_none()
            if updated is None:
                raise ValueError("Carpedia dataset is not the active shadow dataset")
            self._insert_event(connection, run_id, dataset_version, "invalidated", None, clean_reason)

    def rollback_shadow(self, run_id: UUID, target_dataset_version: str, reason: str) -> None:
        clean_reason = sanitize(reason)
        if not clean_reason.strip():
            raise ValueError("Carpedia rollback requires a reason")
        with self.engine.begin() as connection:
            active = connection.execute(
                text("""SELECT dataset_version FROM gold.carpedia_vehicle_spec_dataset
                    WHERE is_active_shadow FOR UPDATE""")
            ).scalar_one_or_none()
            target = connection.execute(
                text("""SELECT status FROM gold.carpedia_vehicle_spec_dataset
                    WHERE dataset_version=:dataset FOR UPDATE"""),
                {"dataset": target_dataset_version},
            ).scalar_one_or_none()
            if active is None or target != "retired" or active == target_dataset_version:
                raise ValueError("Carpedia rollback target is not an eligible retired dataset")
            connection.execute(
                text("""UPDATE gold.carpedia_vehicle_spec_dataset
                    SET status='retired',is_active_shadow=FALSE,retired_at=clock_timestamp()
                    WHERE dataset_version=:dataset"""),
                {"dataset": active},
            )
            connection.execute(
                text("""UPDATE gold.carpedia_vehicle_spec_dataset
                    SET status='shadow_published',is_active_shadow=TRUE,
                        retired_at=NULL,invalidated_at=NULL,invalidation_reason=NULL
                    WHERE dataset_version=:dataset"""),
                {"dataset": target_dataset_version},
            )
            self._insert_event(
                connection,
                run_id,
                target_dataset_version,
                "rolled_back",
                str(active),
                clean_reason,
            )
