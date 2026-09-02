from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from typing import Iterable, Iterator, Mapping, Sequence
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from data_platform.common.logging import sanitize
from data_platform.contracts.pbev import (
    PBEV_MATCHER_VERSION,
    PBEV_PARSER_VERSION,
    PBEV_SOURCE_SYSTEM,
    EfficiencyObservation,
    ExternalVehicleMapping,
    MappingStatus,
    PbevAssetParseResult,
    ParsedPbevRow,
    SourceCoverageReport,
)


PBEV_OFFICIAL_METHODOLOGY_REFERENCE = "PBE Veicular official cycle"


class PbevLoader:
    def __init__(
        self,
        engine: Engine,
        *,
        methodology_reference: str = PBEV_OFFICIAL_METHODOLOGY_REFERENCE,
    ):
        if engine.dialect.name != "postgresql":
            raise ValueError("PBEV persistence requires PostgreSQL")
        if not methodology_reference.strip() or len(methodology_reference) > 120:
            raise ValueError("PBEV methodology reference must contain 1 to 120 characters")
        self.engine = engine
        self.methodology_reference = methodology_reference.strip()

    @contextmanager
    def cycle_locks(self, cycle_years: Iterable[int]) -> Iterator[None]:
        connections: list[tuple[Connection, str]] = []
        try:
            for year in sorted(set(cycle_years)):
                lock_name = f"pbev:{year}"
                connection = self.engine.connect()
                connection.execute(
                    text("SELECT pg_advisory_lock(hashtext(:name)::bigint)"),
                    {"name": lock_name},
                )
                connection.commit()
                connections.append((connection, lock_name))
            yield
        finally:
            for connection, lock_name in reversed(connections):
                connection.execution_options(isolation_level="AUTOCOMMIT").execute(
                    text("SELECT pg_advisory_unlock(hashtext(:name)::bigint)"),
                    {"name": lock_name},
                )
                connection.close()

    def start_run(self, name: str, version: str, dataset_version: str, trigger_type: str, source_reference: str | None, git_commit: str | None) -> UUID:
        run_id = uuid4()
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """INSERT INTO meta.pipeline_run
                    (pipeline_run_id,pipeline_name,pipeline_version,dataset_version,
                     trigger_type,status,started_at,source_reference,git_commit)
                    VALUES (:run,:name,:version,:dataset,:trigger,'running',
                            :started,:reference,:commit)"""
                ),
                {"run": run_id, "name": name, "version": version, "dataset": dataset_version, "trigger": trigger_type, "started": datetime.now(UTC), "reference": source_reference, "commit": git_commit},
            )
        return run_id

    def finish_run(self, run_id: UUID, status: str, *, received: int, inserted: int, deduplicated: int, rejected: int, error: str | None = None) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """UPDATE meta.pipeline_run SET status=:status,
                    finished_at=:finished,records_received=:received,
                    records_inserted=:inserted,records_deduplicated=:deduplicated,
                    records_rejected=:rejected,error_summary=:error
                    WHERE pipeline_run_id=:run"""
                ),
                {"run": run_id, "status": status, "finished": datetime.now(UTC), "received": received, "inserted": inserted, "deduplicated": deduplicated, "rejected": rejected, "error": sanitize(error) if error else None},
            )

    def persist_bronze(self, run_id: UUID, results: Sequence[PbevAssetParseResult]) -> tuple[tuple[ParsedPbevRow, ...], int, int]:
        persisted: list[ParsedPbevRow] = []
        inserted = deduplicated = 0
        with self.engine.begin() as connection:
            for result in results:
                asset = result.asset
                asset_id = connection.execute(
                    text(
                        """INSERT INTO bronze.pbev_source_asset
                        (pipeline_run_id,source_system,official_page_url,
                         download_url_sanitized,document_title,cycle_year,
                         published_at,accessed_at,content_type,byte_length,page_count,
                         sha256,layout_family,document_metadata,document_bytes,
                         storage_mode,license_code,attribution_text,license_url,
                         asset_status,validation_details)
                        VALUES (:run,'inmetro_pbev',:page,:download,:title,:cycle,
                                :published,:accessed,:mime,:bytes,:pages,:sha,:layout,
                                CAST(:metadata AS jsonb),NULL,'metadata_only',:license,
                                :attribution,:license_url,:status,CAST(:validation AS jsonb))
                        ON CONFLICT (source_system,cycle_year,sha256) DO NOTHING
                        RETURNING asset_id"""
                    ),
                    {"run": run_id, "page": asset.official_page_url, "download": asset.download_url_sanitized, "title": asset.document_title, "cycle": asset.cycle_year, "published": asset.published_at, "accessed": asset.accessed_at, "mime": asset.content_type, "bytes": asset.byte_length, "pages": asset.page_count, "sha": asset.sha256, "layout": asset.layout_family, "metadata": json.dumps(asset.document_metadata, ensure_ascii=False), "license": asset.license_code, "attribution": asset.attribution_text, "license_url": asset.license_url, "status": asset.asset_status, "validation": json.dumps(asset.validation_details, ensure_ascii=False)},
                ).scalar_one_or_none()
                if asset_id is None:
                    asset_id = connection.execute(
                        text("SELECT asset_id FROM bronze.pbev_source_asset WHERE source_system='inmetro_pbev' AND cycle_year=:cycle AND sha256=:sha"),
                        {"cycle": asset.cycle_year, "sha": asset.sha256},
                    ).scalar_one()
                    deduplicated += 1
                else:
                    inserted += 1
                for parsed in result.rows:
                    raw = parsed.raw
                    raw_id = connection.execute(
                        text(
                            """INSERT INTO bronze.pbev_raw_row
                            (asset_id,pipeline_run_id,page_number,row_number,
                             source_record_key,parser_version,layout_family,
                             schema_fingerprint,raw_cells,raw_text,row_hash,
                             extraction_status,extraction_method,extracted_at)
                            VALUES (:asset,:run,:page,:row,:key,:parser,:layout,
                                    :schema,CAST(:cells AS jsonb),:text,:hash,
                                    :status,:method,:extracted)
                            ON CONFLICT (asset_id,page_number,row_number) DO NOTHING
                            RETURNING pbev_raw_row_id"""
                        ),
                        {"asset": asset_id, "run": run_id, "page": raw.page_number, "row": raw.row_number, "key": raw.source_record_key, "parser": raw.parser_version, "layout": raw.layout_family, "schema": raw.schema_fingerprint, "cells": json.dumps(raw.raw_cells, ensure_ascii=False), "text": raw.raw_text, "hash": raw.row_hash, "status": raw.extraction_status, "method": raw.extraction_method, "extracted": datetime.now(UTC)},
                    ).scalar_one_or_none()
                    if raw_id is None:
                        raw_id = connection.execute(
                            text("SELECT pbev_raw_row_id FROM bronze.pbev_raw_row WHERE asset_id=:asset AND page_number=:page AND row_number=:row"),
                            {"asset": asset_id, "page": raw.page_number, "row": raw.row_number},
                        ).scalar_one()
                        deduplicated += 1
                    else:
                        inserted += 1
                    persisted.append(replace(parsed, raw=replace(raw, asset_id=int(asset_id), pipeline_run_id=run_id, pbev_raw_row_id=int(raw_id))))
        return tuple(persisted), inserted, deduplicated

    def persist_mappings(self, run_id: UUID, mappings: Sequence[ExternalVehicleMapping], rows: Sequence[ParsedPbevRow]) -> tuple[tuple[ExternalVehicleMapping, ...], tuple[EfficiencyObservation, ...], int]:
        row_by_hash = {row.raw.row_hash: row for row in rows}
        persisted: list[ExternalVehicleMapping] = []
        observations: list[EfficiencyObservation] = []
        inserted = 0
        effective = datetime.now(UTC)
        with self.engine.begin() as connection:
            for index, mapping in enumerate(mappings):
                selected_hash = mapping.evidence.get("selected_row_hash")
                selected = row_by_hash.get(str(selected_hash)) if selected_hash else None
                raw_id = selected.raw.pbev_raw_row_id if selected is not None else None
                current = connection.execute(
                    text("SELECT * FROM silver.pbev_vehicle_mapping_current WHERE source_system='inmetro_pbev' AND target_identity_hash=:target FOR UPDATE"),
                    {"target": mapping.target_identity_hash},
                ).mappings().one_or_none()
                if current is not None and all((str(current["mapping_status"]) == mapping.mapping_status.value, str(current["matcher_version"]) == mapping.matcher_version, current["selected_raw_row_id"] == raw_id, current["vehicle_sk"] == mapping.vehicle_sk)):
                    stored = replace(mapping, mapping_decision_id=int(current["mapping_decision_id"]), selected_raw_row_id=raw_id)
                    persisted.append(stored)
                    if stored.mapping_status == MappingStatus.MATCHED and selected is not None:
                        observation_id = self._insert_observation(
                            connection,
                            run_id,
                            stored,
                            selected,
                        )
                        observations.append(EfficiencyObservation(stored.vehicle_sk, stored.mapping_decision_id, int(raw_id), selected.raw.cycle_year, selected, observation_id=int(observation_id)))
                    continue
                decision_id = connection.execute(
                    text(
                        """INSERT INTO silver.pbev_vehicle_mapping
                        (pipeline_run_id,source_system,target_identity_hash,
                         target_identity_evidence,target_vehicle_type,
                         selected_raw_row_id,vehicle_sk,mapping_status,match_method,
                         confidence,review_required,matcher_version,evidence,
                         decision_reason,reviewed_by,reviewed_at,effective_at,
                         supersedes_mapping_id)
                        VALUES (:run,'inmetro_pbev',:target,CAST(:target_evidence AS jsonb),
                                'car',:raw,:vehicle,:status,:method,:confidence,
                                :review_required,:matcher,CAST(:evidence AS jsonb),
                                :reason,:reviewer,:reviewed,:effective,:supersedes)
                        RETURNING mapping_decision_id"""
                    ),
                    {"run": run_id, "target": mapping.target_identity_hash, "target_evidence": json.dumps(mapping.target_identity_evidence, ensure_ascii=False), "raw": raw_id, "vehicle": mapping.vehicle_sk, "status": mapping.mapping_status.value, "method": mapping.match_method.value, "confidence": mapping.confidence, "review_required": mapping.review_required, "matcher": mapping.matcher_version, "evidence": json.dumps(mapping.evidence, ensure_ascii=False, default=str), "reason": mapping.decision_reason, "reviewer": mapping.reviewed_by, "reviewed": mapping.reviewed_at, "effective": effective + timedelta(microseconds=index), "supersedes": int(current["mapping_decision_id"]) if current else mapping.supersedes_mapping_id},
                ).scalar_one()
                stored = replace(mapping, mapping_decision_id=int(decision_id), selected_raw_row_id=raw_id)
                persisted.append(stored)
                inserted += 1
                if stored.mapping_status == MappingStatus.MATCHED and selected is not None:
                    observation_id = self._insert_observation(connection, run_id, stored, selected)
                    observations.append(EfficiencyObservation(stored.vehicle_sk, int(decision_id), int(raw_id), selected.raw.cycle_year, selected, observation_id=int(observation_id)))
                    inserted += 1
        return tuple(persisted), tuple(observations), inserted

    def _insert_observation(self, connection: Connection, run_id: UUID, mapping: ExternalVehicleMapping, row: ParsedPbevRow) -> int:
        assert mapping.mapping_decision_id is not None and mapping.vehicle_sk is not None and row.raw.pbev_raw_row_id is not None
        values = row
        parameters = {
            "run": run_id, "vehicle": mapping.vehicle_sk, "mapping": mapping.mapping_decision_id, "raw": row.raw.pbev_raw_row_id, "cycle": row.raw.cycle_year, "category": row.category_name, "brand": row.brand_name, "model": row.model_name, "version": row.version_name, "motor": row.motor_description, "transmission": row.transmission_code, "propulsion": row.propulsion_type, "fuel": row.fuel_type, "schema": row.emission_schema_version, "emission_raw": json.dumps(row.emission_raw, ensure_ascii=False), "consumption_raw": json.dumps(row.consumption_raw, ensure_ascii=False), "nmhc": row.nmhc_mg_km, "nox": row.nox_mg_km, "nmog_nox": row.nmog_nox_mg_km, "co": row.co_mg_km, "cho": row.cho_mg_km, "co2e": row.co2_ethanol_g_km, "co2f": row.co2_fossil_g_km, "reduction": row.pollutant_reduction_class, "ec": row.ethanol_city_km_l, "eh": row.ethanol_highway_km_l, "fc": row.fossil_city_km_l, "fh": row.fossil_highway_km_l, "elc": row.electric_city_km_l_equivalent, "elh": row.electric_highway_km_l_equivalent, "energy": row.energy_mj_km, "relative": row.pbe_relative_class, "absolute": row.pbe_absolute_class, "conpet": row.conpet_seal, "methodology": self.methodology_reference, "observed": datetime.now(UTC),
        }
        observation_id = connection.execute(
            text(
                """INSERT INTO silver.vehicle_efficiency_observation
                (pipeline_run_id,vehicle_sk,mapping_decision_id,pbev_raw_row_id,
                 cycle_year,category_name,brand_name,model_name,version_name,
                 motor_description,transmission_code,propulsion_type,fuel_type,
                 emission_schema_version,emission_raw,consumption_raw,nmhc_mg_km,
                 nox_mg_km,nmog_nox_mg_km,co_mg_km,cho_mg_km,
                 co2_ethanol_g_km,co2_fossil_g_km,pollutant_reduction_class,
                 ethanol_city_km_l,ethanol_highway_km_l,fossil_city_km_l,
                 fossil_highway_km_l,electric_city_km_l_equivalent,
                 electric_highway_km_l_equivalent,energy_mj_km,
                 pbe_relative_class,pbe_absolute_class,conpet_seal,
                 methodology_reference,quality_status,observed_at)
                VALUES (:run,:vehicle,:mapping,:raw,:cycle,:category,:brand,:model,
                        :version,:motor,:transmission,:propulsion,:fuel,:schema,
                        CAST(:emission_raw AS jsonb),CAST(:consumption_raw AS jsonb),
                        :nmhc,:nox,:nmog_nox,:co,:cho,:co2e,:co2f,:reduction,
                        :ec,:eh,:fc,:fh,:elc,:elh,:energy,:relative,:absolute,
                        :conpet,:methodology,'passed',:observed)
                ON CONFLICT (mapping_decision_id,pbev_raw_row_id) DO NOTHING
                RETURNING observation_id"""
            ),
            parameters,
        ).scalar_one_or_none()
        if observation_id is None:
            observation_id = connection.execute(
                text("SELECT observation_id FROM silver.vehicle_efficiency_observation WHERE mapping_decision_id=:mapping AND pbev_raw_row_id=:raw"),
                {"mapping": mapping.mapping_decision_id, "raw": row.raw.pbev_raw_row_id},
            ).scalar_one()
        return int(observation_id)

    def publish_shadow(self, run_id: UUID, report: SourceCoverageReport, mappings: Sequence[ExternalVehicleMapping], observations: Sequence[EfficiencyObservation]) -> tuple[str, bool]:
        payload = {
            "assets": report.asset_manifest,
            "parser": report.parser_version,
            "matcher": report.matcher_version,
            "mappings": [(item.target_identity_hash, item.mapping_status.value, item.selected_raw_row_id, str(item.confidence)) for item in mappings],
            "observations": [(item.vehicle_sk, item.mapping_decision_id, item.pbev_raw_row_id) for item in observations],
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        fingerprint = hashlib.sha256(encoded).hexdigest()
        asset_set_hash = hashlib.sha256(json.dumps([item["sha256"] for item in report.asset_manifest], separators=(",", ":")).encode("ascii")).hexdigest()
        dataset_version = f"pbev-shadow-v1-{fingerprint[:12]}-{str(run_id)[:8]}"
        report_payload = json.loads(report.to_json())
        report_payload["dataset_version"] = dataset_version
        with self.engine.begin() as connection:
            active = connection.execute(text("SELECT dataset_version,dataset_fingerprint FROM gold.vehicle_efficiency_dataset WHERE is_active_shadow FOR UPDATE")).mappings().one_or_none()
            if active is not None and active["dataset_fingerprint"] == fingerprint:
                connection.execute(
                    text("UPDATE meta.pipeline_run SET dataset_version=:dataset WHERE pipeline_run_id=:run"),
                    {"dataset": active["dataset_version"], "run": run_id},
                )
                return str(active["dataset_version"]), True
            connection.execute(
                text(
                    """INSERT INTO gold.vehicle_efficiency_dataset
                    (dataset_version,publication_run_id,source_system,
                     source_asset_manifest,source_asset_set_hash,parser_version,
                     matcher_version,status,is_active_shadow,universe_count,
                     eligible_count,matched_count,pending_count,ambiguous_count,
                     rejected_count,not_found_count,published_count,
                     coverage_percentage,coverage_report,dataset_fingerprint,
                     quality_status)
                    VALUES (:dataset,:run,'inmetro_pbev',CAST(:manifest AS jsonb),
                            :asset_hash,:parser,:matcher,'building',FALSE,:universe,
                            :eligible,:matched,:pending,:ambiguous,:rejected,
                            :not_found,:published,:coverage,CAST(:report AS jsonb),
                            :fingerprint,'passed')"""
                ),
                {"dataset": dataset_version, "run": run_id, "manifest": json.dumps(report.asset_manifest, ensure_ascii=False), "asset_hash": asset_set_hash, "parser": report.parser_version, "matcher": report.matcher_version, "universe": report.universe_count, "eligible": report.eligible_count, "matched": report.matched_count, "pending": report.pending_count, "ambiguous": report.ambiguous_count, "rejected": report.rejected_count, "not_found": report.not_found_count, "published": report.published_count, "coverage": report.coverage_percentage, "report": json.dumps(report_payload, ensure_ascii=False), "fingerprint": fingerprint},
            )
            for observation in observations:
                row = observation.parsed
                connection.execute(
                    text(
                        """INSERT INTO gold.vehicle_efficiency_snapshot
                        (dataset_version,publication_run_id,vehicle_sk,
                         mapping_decision_id,observation_id,asset_id,pbev_raw_row_id,
                         cycle_year,brand_name,model_name,version_name,
                         motor_description,transmission_code,propulsion_type,
                         fuel_type,emission_schema_version,nmhc_mg_km,nox_mg_km,
                         nmog_nox_mg_km,co_mg_km,cho_mg_km,co2_ethanol_g_km,
                         co2_fossil_g_km,ethanol_city_km_l,ethanol_highway_km_l,
                         fossil_city_km_l,fossil_highway_km_l,
                         electric_city_km_l_equivalent,
                         electric_highway_km_l_equivalent,energy_mj_km,
                         pbe_relative_class,pbe_absolute_class,conpet_seal,
                         parser_version,matcher_version,data_confidence,
                         quality_status,published_at)
                        VALUES (:dataset,:run,:vehicle,:mapping,:observation,:asset,
                                :raw,:cycle,:brand,:model,:version,:motor,
                                :transmission,:propulsion,:fuel,:schema,:nmhc,:nox,
                                :nmog,:co,:cho,:co2e,:co2f,:ec,:eh,:fc,:fh,:elc,
                                :elh,:energy,:relative,:absolute,:conpet,:parser,
                                :matcher,:confidence,'passed',:published)"""
                    ),
                    {"dataset": dataset_version, "run": run_id, "vehicle": observation.vehicle_sk, "mapping": observation.mapping_decision_id, "observation": observation.observation_id, "asset": row.raw.asset_id, "raw": row.raw.pbev_raw_row_id, "cycle": row.raw.cycle_year, "brand": row.brand_name, "model": row.model_name, "version": row.version_name, "motor": row.motor_description, "transmission": row.transmission_code, "propulsion": row.propulsion_type, "fuel": row.fuel_type, "schema": row.emission_schema_version, "nmhc": row.nmhc_mg_km, "nox": row.nox_mg_km, "nmog": row.nmog_nox_mg_km, "co": row.co_mg_km, "cho": row.cho_mg_km, "co2e": row.co2_ethanol_g_km, "co2f": row.co2_fossil_g_km, "ec": row.ethanol_city_km_l, "eh": row.ethanol_highway_km_l, "fc": row.fossil_city_km_l, "fh": row.fossil_highway_km_l, "elc": row.electric_city_km_l_equivalent, "elh": row.electric_highway_km_l_equivalent, "energy": row.energy_mj_km, "relative": row.pbe_relative_class, "absolute": row.pbe_absolute_class, "conpet": row.conpet_seal, "parser": PBEV_PARSER_VERSION, "matcher": PBEV_MATCHER_VERSION, "confidence": next(item.confidence for item in mappings if item.mapping_decision_id == observation.mapping_decision_id), "published": datetime.now(UTC)},
                )
            connection.execute(
                text(
                    """INSERT INTO gold.vehicle_efficiency_quality_result
                    (dataset_version,pipeline_run_id,rule_code,severity,
                     entity_name,record_reference,status,observed_value,
                     expected_condition,details,evaluated_at)
                    VALUES (:dataset,:run,'PBEV_SHADOW_GATES','critical',
                            'gold.vehicle_efficiency_dataset',:reference,'passed',
                            CAST(:observed AS jsonb),'all shadow publication gates pass',
                            '{}'::jsonb,:evaluated)"""
                ),
                {"dataset": dataset_version, "run": run_id, "reference": dataset_version, "observed": json.dumps({"published_count": report.published_count, "coverage_percentage": str(report.coverage_percentage)}), "evaluated": datetime.now(UTC)},
            )
            if active is not None:
                connection.execute(text("UPDATE gold.vehicle_efficiency_dataset SET status='retired',is_active_shadow=FALSE,retired_at=CURRENT_TIMESTAMP WHERE dataset_version=:dataset"), {"dataset": active["dataset_version"]})
            connection.execute(text("UPDATE gold.vehicle_efficiency_dataset SET status='shadow_published',is_active_shadow=TRUE,published_at=CURRENT_TIMESTAMP WHERE dataset_version=:dataset"), {"dataset": dataset_version})
            connection.execute(
                text("UPDATE meta.pipeline_run SET dataset_version=:dataset WHERE pipeline_run_id=:run"),
                {"dataset": dataset_version, "run": run_id},
            )
        return dataset_version, False
