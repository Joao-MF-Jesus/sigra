from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
import hashlib
import json
from typing import Iterable, Iterator, Mapping, Sequence
from uuid import UUID, uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection, Engine

from data_platform.common.logging import sanitize
from data_platform.contracts.anp_fuel_prices import (
    ANP_AGGREGATION_VERSION,
    ANP_NORMALIZER_VERSION,
    ANP_PARSER_VERSION,
    ANP_SOURCE_NAME,
    AnpFuelPriceObservation,
    AnpFuelPriceSnapshot,
    AnpQualityIssue,
    AnpQualityResult,
    ParsedAnpAsset,
)


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda item: item.isoformat() if isinstance(item, (date, datetime)) else str(item),
    )


class AnpAssetCorrectionError(ValueError):
    def __init__(self, *, received: int, inserted: int, deduplicated: int) -> None:
        self.received = received
        self.inserted = inserted
        self.deduplicated = deduplicated
        super().__init__("ANP asset content changed for an existing period and requires review")


class AnpFuelPriceLoader:
    def __init__(self, engine: Engine) -> None:
        if engine.dialect.name != "postgresql":
            raise ValueError("ANP persistence requires PostgreSQL")
        self.engine = engine

    @contextmanager
    def source_lock(self, source_reference: str) -> Iterator[None]:
        lock_name = f"anp:{source_reference}"
        connection = self.engine.connect()
        try:
            connection.execute(text("SELECT pg_advisory_lock(hashtext(:name)::bigint)"), {"name": lock_name})
            connection.commit()
            yield
        finally:
            try:
                connection.execute(text("SELECT pg_advisory_unlock(hashtext(:name)::bigint)"), {"name": lock_name})
                connection.commit()
            finally:
                connection.close()

    def start_run(
        self,
        pipeline_name: str,
        pipeline_version: str,
        dataset_version: str,
        trigger_type: str,
        source_reference: str,
        git_commit: str | None,
    ) -> UUID:
        run_id = uuid4()
        with self.engine.begin() as connection:
            connection.execute(
                text("""INSERT INTO meta.pipeline_run
                    (pipeline_run_id,pipeline_name,pipeline_version,dataset_version,
                     trigger_type,status,started_at,source_reference,git_commit)
                    VALUES (:run,:name,:version,:dataset,:trigger,'running',:started,
                            :source,:git)"""),
                {"run": run_id, "name": pipeline_name, "version": pipeline_version,
                 "dataset": dataset_version, "trigger": trigger_type,
                 "started": datetime.now(UTC), "source": source_reference,
                 "git": git_commit},
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
                    finished_at=:finished,records_received=:received,
                    records_inserted=:inserted,records_deduplicated=:deduplicated,
                    records_rejected=:rejected,error_summary=:error
                    WHERE pipeline_run_id=:run"""),
                {"run": run_id, "status": status, "finished": datetime.now(UTC),
                 "received": received, "inserted": inserted,
                 "deduplicated": deduplicated, "rejected": rejected,
                 "error": sanitize(error) if error is not None else None},
            )

    def persist_bronze(
        self,
        run_id: UUID,
        parsed: ParsedAnpAsset,
    ) -> tuple[ParsedAnpAsset, int, int]:
        correction_blocked = False
        with self.engine.begin() as connection:
            prior_same_period = False
            if parsed.period_start is not None and parsed.period_end is not None:
                prior_same_period = connection.execute(
                    text("""SELECT EXISTS(
                        SELECT 1 FROM bronze.anp_source_asset
                        WHERE source_name='anp_fuel_prices'
                          AND source_reference=:reference
                          AND period_start=:period_start AND period_end=:period_end
                          AND sha256<>:sha
                    )"""),
                    {"reference": parsed.asset.source_reference,
                     "period_start": parsed.period_start,
                     "period_end": parsed.period_end,
                     "sha": parsed.asset.sha256},
                ).scalar_one()
            asset_id = connection.execute(
                text("""INSERT INTO bronze.anp_source_asset
                    (pipeline_run_id,source_name,source_reference,official_page_url,
                     download_url_sanitized,filename,period_start,period_end,
                     collected_at,http_status,content_type,byte_length,etag,
                     last_modified,sha256,schema_fingerprint,storage_mode,
                     ingestion_status,error_sanitized,technical_metadata)
                    VALUES (:run,'anp_fuel_prices',:reference,:official,:download,
                            :filename,:period_start,:period_end,:collected,:http,
                            :content_type,:size,:etag,:last_modified,:sha,
                            :fingerprint,'metadata_only',:status,:error,
                            CAST(:metadata AS jsonb))
                    ON CONFLICT (source_name,source_reference,sha256) DO NOTHING
                    RETURNING asset_id"""),
                {"run": run_id, "reference": parsed.asset.source_reference,
                 "official": parsed.asset.official_page_url,
                 "download": parsed.asset.download_url_sanitized,
                 "filename": parsed.asset.filename, "period_start": parsed.period_start,
                 "period_end": parsed.period_end, "collected": parsed.asset.collected_at,
                 "http": parsed.asset.http_status, "content_type": parsed.asset.content_type,
                 "size": parsed.asset.byte_length, "etag": parsed.asset.etag,
                 "last_modified": parsed.asset.last_modified, "sha": parsed.asset.sha256,
                 "fingerprint": parsed.layout_fingerprint,
                 "status": parsed.ingestion_status,
                 "error": sanitize(parsed.error_sanitized) if parsed.error_sanitized else None,
                 "metadata": _json(parsed.technical_metadata)},
            ).scalar_one_or_none()
            if asset_id is None:
                asset_id = connection.execute(
                    text("""SELECT asset_id FROM bronze.anp_source_asset
                        WHERE source_name='anp_fuel_prices' AND source_reference=:reference
                        AND sha256=:sha"""),
                    {"reference": parsed.asset.source_reference, "sha": parsed.asset.sha256},
                ).scalar_one()
            persisted_rows = []
            inserted = 0
            for raw in parsed.rows:
                raw_id = connection.execute(
                    text("""INSERT INTO bronze.anp_fuel_price_raw
                        (asset_id,pipeline_run_id,line_number,parser_version,
                         layout_fingerprint,raw_payload,row_hash,extraction_status,
                         error_sanitized,extracted_at)
                        VALUES (:asset,:run,:line,:parser,:layout,CAST(:payload AS jsonb),
                                :hash,:status,:error,:extracted)
                        ON CONFLICT (asset_id,line_number) DO NOTHING
                        RETURNING anp_raw_row_id"""),
                    {"asset": asset_id, "run": run_id, "line": raw.line_number,
                     "parser": ANP_PARSER_VERSION, "layout": parsed.layout_fingerprint,
                     "payload": _json(raw.payload), "hash": raw.row_hash,
                     "status": raw.extraction_status,
                     "error": sanitize(raw.error_sanitized) if raw.error_sanitized else None,
                     "extracted": parsed.asset.collected_at},
                ).scalar_one_or_none()
                if raw_id is None:
                    raw_id = connection.execute(
                        text("""SELECT anp_raw_row_id FROM bronze.anp_fuel_price_raw
                            WHERE asset_id=:asset AND line_number=:line"""),
                        {"asset": asset_id, "line": raw.line_number},
                    ).scalar_one()
                else:
                    inserted += 1
                persisted_rows.append(replace(raw, asset_id=int(asset_id), pipeline_run_id=run_id, anp_raw_row_id=int(raw_id)))
            if prior_same_period:
                record_reference = f"asset:{asset_id}"
                review_status = connection.execute(
                    text("""SELECT resolution_status FROM meta.data_quality_issue
                        WHERE entity_name='anp_fuel_prices'
                          AND record_reference=:reference
                          AND rule_code='ANP_RETROACTIVE_ASSET_CORRECTION_REVIEW'
                        ORDER BY issue_id DESC LIMIT 1"""),
                    {"reference": record_reference},
                ).scalar_one_or_none()
                if review_status not in {"accepted", "resolved"}:
                    self._persist_issues(
                        connection,
                        run_id,
                        (AnpQualityIssue(
                            layer_name="bronze",
                            rule_code="ANP_RETROACTIVE_ASSET_CORRECTION_REVIEW",
                            severity="critical",
                            record_reference=record_reference,
                            message="The ANP asset changed content for an existing reference period and requires review",
                            details={"storage_mode": "metadata_only"},
                        ),),
                    )
                    correction_blocked = True
        deduplicated = len(parsed.rows) - inserted
        if correction_blocked:
            raise AnpAssetCorrectionError(
                received=len(parsed.rows),
                inserted=inserted,
                deduplicated=deduplicated,
            )
        return replace(parsed, asset_id=int(asset_id), rows=tuple(persisted_rows)), inserted, deduplicated

    def persist_silver(
        self,
        run_id: UUID,
        observations: Sequence[AnpFuelPriceObservation],
        issues: Sequence[AnpQualityIssue],
    ) -> tuple[tuple[AnpFuelPriceObservation, ...], int, int, tuple[AnpQualityIssue, ...]]:
        keys = [item.observation_key for item in observations]
        with self.engine.begin() as connection:
            current: dict[str, Mapping[str, object]] = {}
            if keys:
                statement = text("""SELECT observation_id,observation_key,content_hash
                    FROM silver.anp_fuel_price_observation_current
                    WHERE observation_key IN :keys""").bindparams(bindparam("keys", expanding=True))
                current = {
                    str(row["observation_key"]): row
                    for row in connection.execute(statement, {"keys": keys}).mappings()
                }
            persisted = []
            inserted = 0
            deduplicated = 0
            generated_issues = list(issues)
            for observation in observations:
                prior = current.get(observation.observation_key)
                if prior is not None and prior["content_hash"] == observation.content_hash:
                    persisted.append(replace(observation, observation_id=int(prior["observation_id"])))
                    deduplicated += 1
                    continue
                supersedes = int(prior["observation_id"]) if prior is not None else None
                observation_id = self._insert_observation(connection, run_id, observation, supersedes)
                persisted_item = replace(observation, observation_id=observation_id, supersedes_observation_id=supersedes)
                persisted.append(persisted_item)
                current[observation.observation_key] = {
                    "observation_id": observation_id,
                    "observation_key": observation.observation_key,
                    "content_hash": observation.content_hash,
                }
                inserted += 1
                if supersedes is not None:
                    generated_issues.append(
                        AnpQualityIssue(
                            layer_name="silver",
                            rule_code="ANP_RETROACTIVE_CORRECTION_REVIEW",
                            severity="critical",
                            record_reference=f"observation:{observation.observation_key}",
                            message="A later ANP asset changed a current observation and requires review",
                            details={"supersedes_observation_id": supersedes},
                        )
                    )
            self._persist_issues(connection, run_id, generated_issues)
            critical_rows = connection.execute(
                text("""SELECT rule_code,record_reference,message,details
                    FROM meta.data_quality_issue
                    WHERE entity_name='anp_fuel_prices' AND severity='critical'
                      AND resolution_status='open'""")
            ).mappings().all()
            effective_issues = [item for item in generated_issues if item.severity != "critical"]
            effective_issues.extend(
                AnpQualityIssue(
                    layer_name="silver",
                    rule_code=str(row["rule_code"]),
                    severity="critical",
                    record_reference=row["record_reference"],
                    message=str(row["message"]),
                    details=row["details"] or {},
                )
                for row in critical_rows
            )
        return tuple(persisted), inserted, deduplicated, tuple(effective_issues)

    @staticmethod
    def _insert_observation(
        connection: Connection,
        run_id: UUID,
        item: AnpFuelPriceObservation,
        supersedes: int | None,
    ) -> int:
        if item.raw.anp_raw_row_id is None or item.raw.asset_id is None:
            raise ValueError("ANP Silver observation requires persisted Bronze lineage")
        return int(connection.execute(
            text("""INSERT INTO silver.anp_fuel_price_observation
                (anp_raw_row_id,asset_id,pipeline_run_id,observation_key,
                 content_hash,supersedes_observation_id,product_code,currency_code,
                 unit_code,sale_price,purchase_price,flag_name,legal_name,
                 establishment_key,cnpj_hash,street_name,street_number,
                 address_complement,neighborhood,postal_code,municipality_name,
                 municipality_normalized,state_code,region_code,collection_date,
                 week_start,week_end,identity_method,quality_status,observed_at)
                VALUES (:raw,:asset,:run,:key,:content,:supersedes,:product,'BRL',
                        'liter',:sale,:purchase,:flag,:legal,:establishment,:cnpj,
                        :street,:number,:complement,:neighborhood,:postal,
                        :municipality,:municipality_normalized,:state,:region,
                        :collection,:week_start,:week_end,:identity,:quality,:observed)
                RETURNING observation_id"""),
            {"raw": item.raw.anp_raw_row_id, "asset": item.raw.asset_id, "run": run_id,
             "key": item.observation_key, "content": item.content_hash,
             "supersedes": supersedes, "product": item.product_code.value,
             "sale": item.sale_price, "purchase": item.purchase_price,
             "flag": item.flag_name, "legal": item.legal_name,
             "establishment": item.establishment_key, "cnpj": item.cnpj_hash,
             "street": item.street_name, "number": item.street_number,
             "complement": item.address_complement,
             "neighborhood": item.neighborhood, "postal": item.postal_code,
             "municipality": item.municipality_name,
             "municipality_normalized": item.municipality_normalized,
             "state": item.state_code, "region": item.region_code,
             "collection": item.collection_date, "week_start": item.week_start,
             "week_end": item.week_end, "identity": item.identity_method,
             "quality": item.quality_status, "observed": item.observed_at},
        ).scalar_one())

    @staticmethod
    def _persist_issues(connection: Connection, run_id: UUID, issues: Iterable[AnpQualityIssue]) -> None:
        for issue in issues:
            connection.execute(
                text("""INSERT INTO meta.data_quality_issue
                    (pipeline_run_id,layer_name,entity_name,record_reference,
                     rule_code,severity,message,details,resolution_status)
                    VALUES (:run,:layer,'anp_fuel_prices',:reference,:rule,
                            :severity,:message,CAST(:details AS jsonb),'open')
                    ON CONFLICT DO NOTHING"""),
                {"run": run_id, "layer": issue.layer_name,
                 "reference": issue.record_reference, "rule": issue.rule_code,
                 "severity": issue.severity, "message": sanitize(issue.message),
                 "details": _json(issue.details)},
            )

    def publish_shadow(
        self,
        run_id: UUID,
        *,
        asset_manifest: Sequence[Mapping[str, object]],
        observations: Sequence[AnpFuelPriceObservation],
        snapshots: Sequence[AnpFuelPriceSnapshot],
        quality_results: Sequence[AnpQualityResult],
        reference_period_start: date,
        reference_period_end: date,
    ) -> tuple[str, bool]:
        if not observations or not snapshots:
            raise ValueError("empty ANP Gold shadow is forbidden")
        if any(item.get("storage_mode") != "metadata_only" for item in asset_manifest):
            raise ValueError("ANP Gold shadow requires metadata_only assets")
        if any(item.severity == "critical" and item.status != "passed" for item in quality_results):
            raise ValueError("ANP Gold shadow hard gates failed")
        grains = {
            (item.product_code.value, item.week_start, item.geography_level, item.geography_key)
            for item in snapshots
        }
        if len(grains) != len(snapshots):
            raise ValueError("ANP Gold shadow contains duplicate snapshot grains")
        fingerprint_payload = {
            "assets": asset_manifest,
            "parser_version": ANP_PARSER_VERSION,
            "normalizer_version": ANP_NORMALIZER_VERSION,
            "aggregation_version": ANP_AGGREGATION_VERSION,
            "snapshots": [item.snapshot_fingerprint for item in snapshots],
        }
        fingerprint = hashlib.sha256(_json(fingerprint_payload).encode("utf-8")).hexdigest()
        asset_set_hash = hashlib.sha256(_json([item["sha256"] for item in asset_manifest]).encode("ascii")).hexdigest()
        dataset_version = f"anp-shadow-v1-{fingerprint[:12]}-{str(run_id)[:8]}"
        with self.engine.begin() as connection:
            if connection.execute(
                text("""SELECT EXISTS(
                    SELECT 1 FROM meta.data_quality_issue
                    WHERE entity_name='anp_fuel_prices' AND severity='critical'
                      AND resolution_status='open'
                )""")
            ).scalar_one():
                raise ValueError("ANP Gold shadow is blocked by an open critical issue")
            active = connection.execute(
                text("""SELECT dataset_version,dataset_fingerprint
                    FROM gold.anp_fuel_price_dataset
                    WHERE is_active_shadow FOR UPDATE""")
            ).mappings().one_or_none()
            if active is not None and active["dataset_fingerprint"] == fingerprint:
                connection.execute(
                    text("UPDATE meta.pipeline_run SET dataset_version=:dataset WHERE pipeline_run_id=:run"),
                    {"dataset": active["dataset_version"], "run": run_id},
                )
                return str(active["dataset_version"]), True
            connection.execute(
                text("""INSERT INTO gold.anp_fuel_price_dataset
                    (dataset_version,publication_run_id,source_asset_manifest,
                     source_asset_set_hash,parser_version,normalizer_version,
                     aggregation_version,reference_period_start,reference_period_end,
                     status,is_active_shadow,observation_count,snapshot_count,
                     dataset_fingerprint,quality_status)
                    VALUES (:dataset,:run,CAST(:manifest AS jsonb),:asset_hash,:parser,
                            :normalizer,:aggregation,:period_start,:period_end,
                            'building',FALSE,:observations,:snapshots,:fingerprint,'passed')"""),
                {"dataset": dataset_version, "run": run_id,
                 "manifest": _json(asset_manifest), "asset_hash": asset_set_hash,
                 "parser": ANP_PARSER_VERSION, "normalizer": ANP_NORMALIZER_VERSION,
                 "aggregation": ANP_AGGREGATION_VERSION,
                 "period_start": reference_period_start, "period_end": reference_period_end,
                 "observations": len(observations), "snapshots": len(snapshots),
                 "fingerprint": fingerprint},
            )
            for item in snapshots:
                connection.execute(
                    text("""INSERT INTO gold.anp_fuel_price_snapshot
                        (dataset_version,publication_run_id,product_code,week_start,
                         week_end,geography_level,geography_key,municipality_name,
                         state_code,currency_code,unit_code,mean_price,median_price,
                         minimum_price,maximum_price,percentile_25,percentile_75,
                         interquartile_range,observation_count,establishment_count,
                         last_collection_date,freshness_days,sampling_status,
                         dispersion_status,quality_status,snapshot_fingerprint)
                        VALUES (:dataset,:run,:product,:week_start,:week_end,:level,
                                :key,:municipality,:state,'BRL','liter',:mean,:median,
                                :minimum,:maximum,:p25,:p75,:iqr,:observations,
                                :establishments,:last_collection,:freshness,
                                'not_calibrated','not_calibrated','passed',:fingerprint)"""),
                    {"dataset": dataset_version, "run": run_id,
                     "product": item.product_code.value, "week_start": item.week_start,
                     "week_end": item.week_end, "level": item.geography_level,
                     "key": item.geography_key, "municipality": item.municipality_name,
                     "state": item.state_code, "mean": item.mean_price,
                     "median": item.median_price, "minimum": item.minimum_price,
                     "maximum": item.maximum_price, "p25": item.percentile_25,
                     "p75": item.percentile_75, "iqr": item.interquartile_range,
                     "observations": item.observation_count,
                     "establishments": item.establishment_count,
                     "last_collection": item.last_collection_date,
                     "freshness": item.freshness_days,
                     "fingerprint": item.snapshot_fingerprint},
                )
            for result in quality_results:
                connection.execute(
                    text("""INSERT INTO gold.anp_fuel_price_quality_result
                        (dataset_version,pipeline_run_id,rule_code,severity,status,
                         observed_value,expected_condition,details,evaluated_at)
                        VALUES (:dataset,:run,:rule,:severity,:status,
                                CAST(:observed AS jsonb),:expected,
                                CAST(:details AS jsonb),:evaluated)"""),
                    {"dataset": dataset_version, "run": run_id,
                     "rule": result.rule_code, "severity": result.severity,
                     "status": result.status, "observed": _json(result.observed_value),
                     "expected": result.expected_condition,
                     "details": _json(result.details), "evaluated": datetime.now(UTC)},
                )
            if active is not None:
                connection.execute(
                    text("""UPDATE gold.anp_fuel_price_dataset
                        SET status='retired',is_active_shadow=FALSE,
                            retired_at=CURRENT_TIMESTAMP
                        WHERE dataset_version=:dataset"""),
                    {"dataset": active["dataset_version"]},
                )
            connection.execute(
                text("""UPDATE gold.anp_fuel_price_dataset
                    SET status='shadow_published',is_active_shadow=TRUE,
                        published_at=CURRENT_TIMESTAMP
                    WHERE dataset_version=:dataset"""),
                {"dataset": dataset_version},
            )
            connection.execute(
                text("UPDATE meta.pipeline_run SET dataset_version=:dataset WHERE pipeline_run_id=:run"),
                {"dataset": dataset_version, "run": run_id},
            )
        return dataset_version, False
