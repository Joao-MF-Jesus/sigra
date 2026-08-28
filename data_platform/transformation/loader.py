from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from data_platform.contracts.silver_fipe import (
    BronzeFipeInput,
    SilverPersistenceOutcome,
    SilverQualityIssue,
    SilverTransformCandidate,
)
from data_platform.quality.silver_checks import quality_issue
from data_platform.transformation.fipe import decide_price_history


def historical_mapping_matches(
    candidate: SilverTransformCandidate,
    persisted_mapping: Any,
) -> bool:
    """Confirma que a Bronze ja originou exatamente esta decisao de mapping."""
    return all(
        (
            persisted_mapping["source_name"] == candidate.bronze.source_name,
            persisted_mapping["vehicle_type"] == candidate.bronze.vehicle_type,
            persisted_mapping["fipe_code"] == candidate.bronze.fipe_code,
            persisted_mapping["year_code"] == candidate.bronze.year_code,
            persisted_mapping["source_vehicle_key"] == candidate.source_vehicle_key,
            persisted_mapping["mapping_status"] == candidate.mapping_status,
        )
    )


class SilverLoader:
    def __init__(self, engine: Engine):
        self.engine = engine

    @property
    def is_postgresql(self) -> bool:
        return self.engine.dialect.name == "postgresql"

    def fetch_received_records(self) -> list[BronzeFipeInput]:
        if not self.is_postgresql:
            return []
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    """SELECT fipe_raw_id,pipeline_run_id,source_name,vehicle_type,
                        source_record_key,fipe_code,year_code,reference_month_raw,
                        http_status,collected_at,payload,payload_hash,
                        schema_fingerprint,ingestion_status
                    FROM bronze.fipe_raw
                    WHERE ingestion_status = 'received'
                      AND http_status BETWEEN 200 AND 299
                      AND payload IS NOT NULL
                    ORDER BY collected_at,fipe_raw_id"""
                )
            ).mappings().all()
        return [BronzeFipeInput.from_mapping(row) for row in rows]

    def start_run(
        self,
        run_id: UUID,
        dataset_version: str,
        trigger_type: str,
        source_reference: str | None,
        git_commit: str | None,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """INSERT INTO meta.pipeline_run
                    (pipeline_run_id,pipeline_name,pipeline_version,dataset_version,
                     trigger_type,status,started_at,source_reference,git_commit)
                    VALUES (:id,'fipe_vehicle_prices_silver','fipe-silver-v1',
                            :dataset,:trigger,'running',:started,:reference,:commit)"""
                ),
                {
                    "id": run_id,
                    "dataset": dataset_version,
                    "trigger": trigger_type,
                    "started": datetime.now(UTC),
                    "reference": source_reference,
                    "commit": git_commit,
                },
            )

    def finish_run(
        self,
        run_id: UUID,
        status: str,
        received: int,
        inserted: int,
        duplicates: int,
        rejected: int,
        error_summary: str | None,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """UPDATE meta.pipeline_run
                    SET status=:status,finished_at=:finished,
                        records_received=:received,records_inserted=:inserted,
                        records_deduplicated=:duplicates,
                        records_rejected=:rejected,error_summary=:error
                    WHERE pipeline_run_id=:id"""
                ),
                {
                    "id": run_id,
                    "status": status,
                    "finished": datetime.now(UTC),
                    "received": received,
                    "inserted": inserted,
                    "duplicates": duplicates,
                    "rejected": rejected,
                    "error": error_summary,
                },
            )

    def persist_candidate(
        self,
        run_id: UUID,
        candidate: SilverTransformCandidate,
    ) -> SilverPersistenceOutcome:
        if not self.is_postgresql:
            return SilverPersistenceOutcome(deduplicated=True)

        with self.engine.begin() as connection:
            historical_mapping = self._mapping_by_bronze_record(
                connection,
                candidate.bronze.fipe_raw_id,
            )
            if historical_mapping is not None:
                if historical_mapping_matches(candidate, historical_mapping):
                    return SilverPersistenceOutcome(deduplicated=True)
                issue_inserted = self._insert_dynamic_issue(
                    connection,
                    run_id,
                    candidate,
                    quality_issue(
                        "HISTORICAL_MAPPING_CONFLICT",
                        "Persisted mapping origin is incompatible with reprocessed Bronze evidence",
                        severity="critical",
                        entity_name="silver.vehicle_source_mapping",
                    ),
                )
                return SilverPersistenceOutcome(
                    rejected=True,
                    issues_inserted=issue_inserted,
                )

            issues_inserted = sum(
                self._insert_issue(connection, run_id, candidate, item)
                for item in candidate.issues
            )
            inserted_rows = 0
            rejected = candidate.mapping_status != "matched" or candidate.price is None

            if not candidate.can_persist_mapping:
                return SilverPersistenceOutcome(
                    rejected=True,
                    issues_inserted=issues_inserted,
                )

            current_mapping = self._current_mapping(connection, candidate)
            mapping_id: int | None = None
            vehicle_sk: int | None = None

            if (
                current_mapping is not None
                and current_mapping["source_vehicle_key"]
                != candidate.source_vehicle_key
            ):
                issues_inserted += self._insert_dynamic_issue(
                    connection,
                    run_id,
                    candidate,
                    quality_issue(
                        "SOURCE_MAPPING_KEY_CONFLICT",
                        "Current source mapping has an incompatible deterministic key",
                        severity="critical",
                        entity_name="silver.vehicle_source_mapping",
                    ),
                )
                return SilverPersistenceOutcome(
                    rejected=True,
                    issues_inserted=issues_inserted,
                )

            if candidate.mapping_status != "matched":
                if current_mapping is None:
                    mapping_id = self._insert_mapping(
                        connection,
                        run_id,
                        candidate,
                        vehicle_sk=None,
                    )
                    inserted_rows += 1
                elif current_mapping["mapping_status"] == candidate.mapping_status:
                    mapping_id = int(current_mapping["mapping_id"])
                else:
                    issues_inserted += self._insert_dynamic_issue(
                        connection,
                        run_id,
                        candidate,
                        quality_issue(
                            "SOURCE_MAPPING_CONFLICT",
                            "Current source mapping conflicts with this Bronze evidence",
                            severity="critical",
                            entity_name="silver.vehicle_source_mapping",
                        ),
                    )
                return SilverPersistenceOutcome(
                    inserted_rows=inserted_rows,
                    deduplicated=False,
                    rejected=True,
                    issues_inserted=issues_inserted,
                )

            if candidate.identity is None:
                return SilverPersistenceOutcome(
                    rejected=True,
                    issues_inserted=issues_inserted,
                )

            if current_mapping is not None:
                if current_mapping["mapping_status"] == "matched":
                    if current_mapping["canonical_key"] != candidate.identity.canonical_key:
                        issues_inserted += self._insert_dynamic_issue(
                            connection,
                            run_id,
                            candidate,
                            quality_issue(
                                "SOURCE_MAPPING_CONFLICT",
                                "Current FIPE mapping points to a different canonical identity",
                                severity="critical",
                                entity_name="silver.vehicle_source_mapping",
                            ),
                        )
                        return SilverPersistenceOutcome(
                            rejected=True,
                            issues_inserted=issues_inserted,
                        )
                    mapping_id = int(current_mapping["mapping_id"])
                    vehicle_sk = int(current_mapping["vehicle_sk"])
                elif current_mapping["mapping_status"] == "pending":
                    if candidate.bronze.collected_at <= current_mapping["valid_from"]:
                        issues_inserted += self._insert_dynamic_issue(
                            connection,
                            run_id,
                            candidate,
                            quality_issue(
                                "SOURCE_MAPPING_NON_MONOTONIC",
                                "Pending mapping cannot be closed by older evidence",
                                entity_name="silver.vehicle_source_mapping",
                            ),
                        )
                        return SilverPersistenceOutcome(
                            rejected=True,
                            issues_inserted=issues_inserted,
                        )
                    connection.execute(
                        text(
                            """UPDATE silver.vehicle_source_mapping
                            SET valid_to=:valid_to
                            WHERE mapping_id=:mapping_id"""
                        ),
                        {
                            "valid_to": candidate.bronze.collected_at,
                            "mapping_id": current_mapping["mapping_id"],
                        },
                    )
                    vehicle_sk, identity_inserted = self._get_or_create_identity(
                        connection,
                        run_id,
                        candidate,
                    )
                    inserted_rows += identity_inserted
                    mapping_id = self._insert_mapping(
                        connection,
                        run_id,
                        candidate,
                        vehicle_sk=vehicle_sk,
                    )
                    inserted_rows += 1
                else:
                    issues_inserted += self._insert_dynamic_issue(
                        connection,
                        run_id,
                        candidate,
                        quality_issue(
                            "SOURCE_MAPPING_REVIEW_REQUIRED",
                            "Ambiguous or rejected mapping requires reviewed evidence",
                            severity="critical",
                            entity_name="silver.vehicle_source_mapping",
                        ),
                    )
                    return SilverPersistenceOutcome(
                        rejected=True,
                        issues_inserted=issues_inserted,
                    )
            else:
                vehicle_sk, identity_inserted = self._get_or_create_identity(
                    connection,
                    run_id,
                    candidate,
                )
                inserted_rows += identity_inserted
                mapping_id = self._insert_mapping(
                    connection,
                    run_id,
                    candidate,
                    vehicle_sk=vehicle_sk,
                )
                inserted_rows += 1

            if candidate.price is not None and mapping_id is not None and vehicle_sk is not None:
                price_inserted, price_rejected, price_issues = self._persist_price(
                    connection,
                    run_id,
                    candidate,
                    mapping_id,
                    vehicle_sk,
                )
                inserted_rows += price_inserted
                issues_inserted += price_issues
                rejected = price_rejected

            return SilverPersistenceOutcome(
                inserted_rows=inserted_rows,
                deduplicated=inserted_rows == 0 and not rejected,
                rejected=rejected,
                issues_inserted=issues_inserted,
            )

    @staticmethod
    def _mapping_by_bronze_record(
        connection: Connection,
        bronze_record_id: int,
    ) -> Any | None:
        return connection.execute(
            text(
                """SELECT mapping_id,vehicle_sk,source_name,vehicle_type,
                    source_vehicle_key,fipe_code,year_code,mapping_status,
                    valid_from,valid_to
                FROM silver.vehicle_source_mapping
                WHERE bronze_record_id=:bronze_record_id
                FOR UPDATE"""
            ),
            {"bronze_record_id": bronze_record_id},
        ).mappings().one_or_none()

    @staticmethod
    def _current_mapping(
        connection: Connection,
        candidate: SilverTransformCandidate,
    ) -> Any | None:
        return connection.execute(
            text(
                """SELECT mapping.mapping_id,mapping.vehicle_sk,
                    mapping.vehicle_type,mapping.source_vehicle_key,
                    mapping.mapping_status,mapping.valid_from,identity.canonical_key
                FROM silver.vehicle_source_mapping AS mapping
                LEFT JOIN silver.vehicle_identity AS identity
                  ON identity.vehicle_sk = mapping.vehicle_sk
                WHERE mapping.source_name=:source
                  AND mapping.vehicle_type=:vehicle_type
                  AND mapping.fipe_code=:fipe_code
                  AND mapping.year_code=:year_code
                  AND mapping.valid_to IS NULL
                FOR UPDATE OF mapping"""
            ),
            {
                "source": candidate.bronze.source_name,
                "vehicle_type": candidate.bronze.vehicle_type,
                "fipe_code": candidate.bronze.fipe_code,
                "year_code": candidate.bronze.year_code,
            },
        ).mappings().one_or_none()

    @staticmethod
    def _get_or_create_identity(
        connection: Connection,
        run_id: UUID,
        candidate: SilverTransformCandidate,
    ) -> tuple[int, int]:
        identity = candidate.identity
        assert identity is not None
        existing = connection.execute(
            text(
                """SELECT vehicle_sk
                FROM silver.vehicle_identity
                WHERE canonical_key=:canonical_key AND is_current
                FOR UPDATE"""
            ),
            {"canonical_key": identity.canonical_key},
        ).scalar_one_or_none()
        if existing is not None:
            return int(existing), 0
        vehicle_sk = connection.execute(
            text(
                """INSERT INTO silver.vehicle_identity
                (vehicle_type,brand_name,model_name,version_name,model_year,
                 is_zero_km,fuel_type,transmission_type,canonical_key,valid_from,
                 is_current,bronze_record_id,pipeline_run_id,created_by_run_id,
                 updated_by_run_id)
                VALUES (:vehicle_type,:brand,:model,NULL,:model_year,:zero_km,
                        :fuel,NULL,:canonical_key,:valid_from,TRUE,:bronze,:run,
                        :run,:run)
                RETURNING vehicle_sk"""
            ),
            {
                "vehicle_type": identity.vehicle_type,
                "brand": identity.brand_name,
                "model": identity.model_name,
                "model_year": identity.model_year,
                "zero_km": identity.is_zero_km,
                "fuel": identity.fuel_type,
                "canonical_key": identity.canonical_key,
                "valid_from": candidate.bronze.collected_at,
                "bronze": candidate.bronze.fipe_raw_id,
                "run": run_id,
            },
        ).scalar_one()
        return int(vehicle_sk), 1

    @staticmethod
    def _insert_mapping(
        connection: Connection,
        run_id: UUID,
        candidate: SilverTransformCandidate,
        *,
        vehicle_sk: int | None,
    ) -> int:
        mapping_id = connection.execute(
            text(
                """INSERT INTO silver.vehicle_source_mapping
                (vehicle_sk,source_name,vehicle_type,source_vehicle_key,fipe_code,
                 year_code,mapping_status,match_method,confidence,valid_from,
                 pipeline_run_id,bronze_record_id,review_notes)
                VALUES (:vehicle_sk,:source,:vehicle_type,:source_key,:fipe_code,
                        :year_code,:status,:method,:confidence,:valid_from,:run,
                        :bronze,:notes)
                RETURNING mapping_id"""
            ),
            {
                "vehicle_sk": vehicle_sk,
                "source": candidate.bronze.source_name,
                "vehicle_type": candidate.bronze.vehicle_type,
                "source_key": candidate.source_vehicle_key,
                "fipe_code": candidate.bronze.fipe_code,
                "year_code": candidate.bronze.year_code,
                "status": candidate.mapping_status,
                "method": candidate.match_method,
                "confidence": candidate.confidence,
                "valid_from": candidate.bronze.collected_at,
                "run": run_id,
                "bronze": candidate.bronze.fipe_raw_id,
                "notes": candidate.review_notes,
            },
        ).scalar_one()
        return int(mapping_id)

    def _persist_price(
        self,
        connection: Connection,
        run_id: UUID,
        candidate: SilverTransformCandidate,
        mapping_id: int,
        vehicle_sk: int,
    ) -> tuple[int, bool, int]:
        price = candidate.price
        assert price is not None
        existing = connection.execute(
            text(
                """SELECT vehicle_price_id,price_amount,currency
                FROM silver.vehicle_price_history
                WHERE vehicle_sk=:vehicle_sk AND source_name=:source
                  AND reference_month=:reference_month
                FOR UPDATE"""
            ),
            {
                "vehicle_sk": vehicle_sk,
                "source": candidate.bronze.source_name,
                "reference_month": price.reference_month,
            },
        ).mappings().one_or_none()
        if existing is not None:
            decision = decide_price_history(
                price,
                existing_price=existing["price_amount"],
                existing_currency=existing["currency"].strip(),
            )
            if decision.action == "idempotent":
                return 0, False, 0
            inserted_issue = self._insert_dynamic_issue(
                connection,
                run_id,
                candidate,
                quality_issue(
                    "PRICE_CONFLICT_SAME_MONTH",
                    "A different FIPE price already exists for this reference month",
                    severity="critical",
                    entity_name="silver.vehicle_price_history",
                    details={"reference_month": price.reference_month.isoformat()},
                ),
            )
            return 0, True, inserted_issue

        predecessor = connection.execute(
            text(
                """SELECT vehicle_price_id,valid_from,valid_to,is_current
                FROM silver.vehicle_price_history
                WHERE vehicle_sk=:vehicle_sk AND source_name=:source
                  AND reference_month < :reference_month
                ORDER BY reference_month DESC
                LIMIT 1
                FOR UPDATE"""
            ),
            {
                "vehicle_sk": vehicle_sk,
                "source": candidate.bronze.source_name,
                "reference_month": price.reference_month,
            },
        ).mappings().one_or_none()
        successor = connection.execute(
            text(
                """SELECT vehicle_price_id,valid_from
                FROM silver.vehicle_price_history
                WHERE vehicle_sk=:vehicle_sk AND source_name=:source
                  AND reference_month > :reference_month
                ORDER BY reference_month
                LIMIT 1
                FOR UPDATE"""
            ),
            {
                "vehicle_sk": vehicle_sk,
                "source": candidate.bronze.source_name,
                "reference_month": price.reference_month,
            },
        ).mappings().one_or_none()

        decision = decide_price_history(
            price,
            predecessor_exists=predecessor is not None,
            successor_valid_from=(
                successor["valid_from"] if successor is not None else None
            ),
        )
        assert decision.valid_from is not None
        if decision.close_predecessor:
            connection.execute(
                text(
                    """UPDATE silver.vehicle_price_history
                    SET valid_to=:valid_to,is_current=FALSE
                    WHERE vehicle_price_id=:vehicle_price_id"""
                ),
                {
                    "valid_to": decision.valid_from,
                    "vehicle_price_id": predecessor["vehicle_price_id"],
                },
            )

        connection.execute(
            text(
                """INSERT INTO silver.vehicle_price_history
                (vehicle_sk,source_name,source_mapping_id,price_amount,currency,
                 reference_month,collected_at,valid_from,valid_to,is_current,
                 data_confidence,bronze_record_id,pipeline_run_id)
                VALUES (:vehicle_sk,:source,:mapping,:price,:currency,:reference,
                        :collected,:valid_from,:valid_to,:current,:confidence,
                        :bronze,:run)"""
            ),
            {
                "vehicle_sk": vehicle_sk,
                "source": candidate.bronze.source_name,
                "mapping": mapping_id,
                "price": price.price_amount,
                "currency": price.currency,
                "reference": price.reference_month,
                "collected": candidate.bronze.collected_at,
                "valid_from": decision.valid_from,
                "valid_to": decision.valid_to,
                "current": decision.is_current,
                "confidence": price.data_confidence,
                "bronze": candidate.bronze.fipe_raw_id,
                "run": run_id,
            },
        )
        return 1, False, 0

    def _insert_dynamic_issue(
        self,
        connection: Connection,
        run_id: UUID,
        candidate: SilverTransformCandidate,
        issue: SilverQualityIssue,
    ) -> int:
        return self._insert_issue(connection, run_id, candidate, issue)

    @staticmethod
    def _insert_issue(
        connection: Connection,
        run_id: UUID,
        candidate: SilverTransformCandidate,
        issue: SilverQualityIssue,
    ) -> int:
        result = connection.execute(
            text(
                """INSERT INTO meta.data_quality_issue
                (pipeline_run_id,layer_name,entity_name,record_reference,
                 rule_code,severity,message,details,resolution_status)
                VALUES (:run,'silver',:entity,:reference,:rule,:severity,
                        :message,CAST(:details AS jsonb),'open')
                ON CONFLICT (layer_name,entity_name,record_reference,rule_code)
                WHERE layer_name = 'silver' AND resolution_status = 'open'
                DO NOTHING"""
            ),
            {
                "run": run_id,
                "entity": issue.entity_name,
                "reference": f"bronze.fipe_raw:{candidate.bronze.fipe_raw_id}",
                "rule": issue.rule_code,
                "severity": issue.severity,
                "message": issue.message,
                "details": json.dumps(issue.details or {}, ensure_ascii=False),
            },
        )
        return 1 if result.rowcount == 1 else 0
