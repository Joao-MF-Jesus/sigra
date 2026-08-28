from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import json
from typing import Any, Iterator, Mapping, Sequence
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from data_platform.common.logging import sanitize
from data_platform.contracts.gold_vehicle_features import (
    GOLD_SOURCE_NAME,
    GOLD_VEHICLE_TYPE,
    GoldBlockedMapping,
    GoldPublicationPlan,
    GoldScopeRow,
    GoldSnapshotCandidate,
)
from data_platform.quality.gold_checks import safe_issue_details


ADVISORY_LOCK_NAME = "sigra_gold_vehicle_features_v1"


class GoldLoader:
    def __init__(self, engine: Engine):
        self.engine = engine

    @property
    def is_postgresql(self) -> bool:
        return self.engine.dialect.name == "postgresql"

    def start_run(
        self,
        run_id: UUID,
        dataset_version: str,
        *,
        pipeline_name: str,
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
                    VALUES (:run,:name,'gold-vehicle-features-v1',:dataset,
                            :trigger,'running',:started,:reference,:commit)"""
                ),
                {
                    "run": run_id,
                    "name": pipeline_name,
                    "dataset": dataset_version,
                    "trigger": trigger_type,
                    "started": datetime.now(UTC),
                    "reference": source_reference,
                    "commit": git_commit,
                },
            )

    def finish_failed(self, run_id: UUID, error: object) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """UPDATE meta.pipeline_run
                    SET status='failed',finished_at=:finished,
                        error_summary=:error
                    WHERE pipeline_run_id=:run"""
                ),
                {
                    "run": run_id,
                    "finished": datetime.now(UTC),
                    "error": sanitize(error),
                },
            )

    @contextmanager
    def publication_transaction(self) -> Iterator[Connection]:
        connection = self.engine.connect()
        lock_acquired = False
        transaction = None
        try:
            # O lock de sessao e adquirido antes do snapshot REPEATABLE READ.
            # Assim, uma publicacao concorrente espera a anterior e depois
            # enxerga o dataset que ela acabou de ativar.
            connection.execute(
                text("SELECT pg_advisory_lock(hashtext(:name)::bigint)"),
                {"name": ADVISORY_LOCK_NAME},
            )
            connection.commit()
            lock_acquired = True
            connection = connection.execution_options(
                isolation_level="REPEATABLE READ"
            )
            transaction = connection.begin()
            yield connection
            transaction.commit()
        except BaseException:
            if transaction is not None and transaction.is_active:
                transaction.rollback()
            raise
        finally:
            if lock_acquired:
                connection = connection.execution_options(
                    isolation_level="AUTOCOMMIT"
                )
                connection.execute(
                    text("SELECT pg_advisory_unlock(hashtext(:name)::bigint)"),
                    {"name": ADVISORY_LOCK_NAME},
                )
            connection.close()

    @staticmethod
    def acquire_lock(connection: Connection) -> None:
        """Disponivel para validacoes; a transacao publica usa lock de sessao."""
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:name)::bigint)"),
            {"name": ADVISORY_LOCK_NAME},
        )

    @staticmethod
    def database_now(connection: Connection) -> datetime:
        return connection.execute(text("SELECT CURRENT_TIMESTAMP")).scalar_one()

    @staticmethod
    def fetch_scope(connection: Connection) -> tuple[GoldScopeRow, ...]:
        rows = connection.execute(
            text(
                """SELECT
                    mapping.mapping_id,
                    mapping.mapping_status,
                    mapping.vehicle_sk,
                    mapping.vehicle_type,
                    mapping.source_name,
                    mapping.source_vehicle_key,
                    mapping.fipe_code,
                    mapping.year_code,
                    mapping.pipeline_run_id AS mapping_run_id,
                    identity.vehicle_sk AS identity_vehicle_sk,
                    identity.vehicle_type AS identity_vehicle_type,
                    identity.brand_name,
                    identity.model_name,
                    identity.version_name,
                    identity.model_year,
                    identity.is_zero_km,
                    identity.fuel_type,
                    identity.transmission_type,
                    identity.pipeline_run_id AS identity_run_id,
                    price.vehicle_price_id AS silver_price_id,
                    price.vehicle_sk AS price_vehicle_sk,
                    price.price_amount,
                    price.currency,
                    price.reference_month,
                    price.collected_at AS price_collected_at,
                    price.data_confidence,
                    price.pipeline_run_id AS price_run_id
                FROM silver.vehicle_source_mapping AS mapping
                LEFT JOIN silver.vehicle_identity AS identity
                  ON identity.vehicle_sk = mapping.vehicle_sk
                 AND identity.is_current
                LEFT JOIN silver.vehicle_price_history AS price
                  ON price.source_mapping_id = mapping.mapping_id
                 AND price.source_name = mapping.source_name
                 AND price.is_current
                WHERE mapping.source_name = :source
                  AND mapping.vehicle_type = :vehicle_type
                  AND mapping.valid_to IS NULL
                  AND mapping.mapping_status IN
                      ('matched','pending','ambiguous','rejected')
                ORDER BY mapping.mapping_id"""
            ),
            {"source": GOLD_SOURCE_NAME, "vehicle_type": GOLD_VEHICLE_TYPE},
        ).mappings().all()
        return tuple(GoldScopeRow.from_mapping(row) for row in rows)

    @staticmethod
    def fetch_applicable_issues(connection: Connection) -> tuple[Mapping[str, Any], ...]:
        return tuple(
            connection.execute(
                text(
                    """SELECT issue_id,layer_name,entity_name,record_reference,
                        rule_code,severity,message,details,resolution_status,resolved_at
                    FROM meta.data_quality_issue
                    WHERE layer_name IN ('silver','gold')
                      AND resolution_status IN ('open','accepted')
                      AND NOT (
                          layer_name='gold'
                          AND rule_code='GOLD_MAPPING_BLOCKED'
                      )
                    ORDER BY issue_id"""
                )
            ).mappings().all()
        )

    @staticmethod
    def active_dataset(connection: Connection, *, for_update: bool = True) -> Mapping[str, Any] | None:
        lock = " FOR UPDATE" if for_update else ""
        return connection.execute(
            text(
                """SELECT dataset_version,dataset_fingerprint,status,is_active,
                    expected_vehicle_count,published_vehicle_count,
                    blocked_vehicle_count,coverage_percentage,
                    minimum_reference_month,maximum_reference_month,
                    base_quality_status,last_activation_event_id,activation_run_id
                FROM gold.vehicle_feature_dataset
                WHERE is_active""" + lock
            )
        ).mappings().one_or_none()

    @staticmethod
    def dataset(connection: Connection, dataset_version: str, *, for_update: bool = True) -> Mapping[str, Any] | None:
        lock = " FOR UPDATE" if for_update else ""
        return connection.execute(
            text(
                """SELECT dataset_version,dataset_fingerprint,status,is_active,
                    expected_vehicle_count,published_vehicle_count,
                    blocked_vehicle_count,coverage_percentage,
                    minimum_reference_month,maximum_reference_month,
                    base_quality_status,last_activation_event_id,activation_run_id
                FROM gold.vehicle_feature_dataset
                WHERE dataset_version=:dataset""" + lock
            ),
            {"dataset": dataset_version},
        ).mappings().one_or_none()

    @staticmethod
    def validate_dataset_snapshot(
        connection: Connection,
        dataset: Mapping[str, Any],
    ) -> bool:
        aggregate = connection.execute(
            text(
                """SELECT COUNT(*) AS row_count,
                    COUNT(DISTINCT vehicle_sk) AS vehicle_count,
                    MIN(price_reference_month) AS minimum_reference_month,
                    MAX(price_reference_month) AS maximum_reference_month
                FROM gold.vehicle_features_snapshot
                WHERE dataset_version=:dataset"""
            ),
            {"dataset": dataset["dataset_version"]},
        ).mappings().one()
        expected_rows = int(dataset["published_vehicle_count"])
        return all(
            (
                int(aggregate["row_count"]) == expected_rows,
                int(aggregate["vehicle_count"]) == expected_rows,
                aggregate["minimum_reference_month"]
                == dataset["minimum_reference_month"],
                aggregate["maximum_reference_month"]
                == dataset["maximum_reference_month"],
            )
        )

    @staticmethod
    def update_run_dataset_version(
        connection: Connection,
        run_id: UUID,
        dataset_version: str,
    ) -> None:
        connection.execute(
            text(
                """UPDATE meta.pipeline_run
                SET dataset_version=:dataset
                WHERE pipeline_run_id=:run"""
            ),
            {"run": run_id, "dataset": dataset_version},
        )

    @staticmethod
    def finish_run(
        connection: Connection,
        run_id: UUID,
        status: str,
        *,
        expected: int,
        inserted: int,
        deduplicated: int,
        rejected: int,
        error_summary: str | None = None,
    ) -> None:
        connection.execute(
            text(
                """UPDATE meta.pipeline_run
                SET status=:status,finished_at=CURRENT_TIMESTAMP,
                    records_received=:expected,records_inserted=:inserted,
                    records_deduplicated=:deduplicated,
                    records_rejected=:rejected,error_summary=:error
                WHERE pipeline_run_id=:run"""
            ),
            {
                "run": run_id,
                "status": status,
                "expected": expected,
                "inserted": inserted,
                "deduplicated": deduplicated,
                "rejected": rejected,
                "error": sanitize(error_summary) if error_summary else None,
            },
        )

    @staticmethod
    def record_blocked_issue(
        connection: Connection,
        run_id: UUID,
        blocked: GoldBlockedMapping,
    ) -> int:
        reference = f"silver.vehicle_source_mapping:{blocked.mapping_id}"
        existing = connection.execute(
            text(
                """SELECT issue_id,resolution_status,details
                FROM meta.data_quality_issue
                WHERE layer_name='gold'
                  AND entity_name='silver.vehicle_source_mapping'
                  AND record_reference=:reference
                  AND rule_code='GOLD_MAPPING_BLOCKED'
                  AND resolution_status IN ('open','accepted')
                ORDER BY CASE resolution_status WHEN 'open' THEN 0 ELSE 1 END,
                         issue_id DESC
                LIMIT 1
                FOR UPDATE"""
            ),
            {"reference": reference},
        ).mappings().one_or_none()
        safe = safe_issue_details(
            {
                "mapping_id": blocked.mapping_id,
                "reason_code": blocked.reason_code,
            }
        )
        run_text = str(run_id)
        if existing is not None:
            details = dict(existing["details"] or {})
            publication_runs = list(details.get("publication_run_ids", []))
            if run_text not in publication_runs:
                publication_runs.append(run_text)
            details.update(safe)
            details["publication_run_ids"] = publication_runs[-50:]
            connection.execute(
                text(
                    """UPDATE meta.data_quality_issue
                    SET details=CAST(:details AS jsonb)
                    WHERE issue_id=:issue"""
                ),
                {
                    "issue": existing["issue_id"],
                    "details": json.dumps(details, ensure_ascii=False),
                },
            )
            return int(existing["issue_id"])

        details = {**safe, "publication_run_ids": [run_text]}
        return int(
            connection.execute(
                text(
                    """INSERT INTO meta.data_quality_issue
                    (pipeline_run_id,layer_name,entity_name,record_reference,
                     rule_code,severity,message,details,resolution_status)
                    VALUES (:run,'gold','silver.vehicle_source_mapping',:reference,
                            'GOLD_MAPPING_BLOCKED',:severity,:message,
                            CAST(:details AS jsonb),'open')
                    RETURNING issue_id"""
                ),
                {
                    "run": run_id,
                    "reference": reference,
                    "severity": blocked.severity,
                    "message": sanitize(blocked.message),
                    "details": json.dumps(details, ensure_ascii=False),
                },
            ).scalar_one()
        )

    @staticmethod
    def resolve_cleared_blocked_issues(
        connection: Connection,
        run_id: UUID,
        blocked_mapping_ids: set[int],
    ) -> int:
        rows = connection.execute(
            text(
                """SELECT issue_id,record_reference,details
                FROM meta.data_quality_issue
                WHERE layer_name='gold'
                  AND entity_name='silver.vehicle_source_mapping'
                  AND rule_code='GOLD_MAPPING_BLOCKED'
                  AND resolution_status='open'
                FOR UPDATE"""
            )
        ).mappings().all()
        resolved = 0
        for row in rows:
            reference = str(row["record_reference"] or "")
            try:
                mapping_id = int(reference.rsplit(":", 1)[1])
            except (IndexError, ValueError):
                continue
            if mapping_id in blocked_mapping_ids:
                continue
            details = dict(row["details"] or {})
            details["resolved_by_run_id"] = str(run_id)
            details["resolution_reason"] = "mapping_no_longer_blocked"
            connection.execute(
                text(
                    """UPDATE meta.data_quality_issue
                    SET resolution_status='resolved',resolved_at=CURRENT_TIMESTAMP,
                        details=CAST(:details AS jsonb)
                    WHERE issue_id=:issue"""
                ),
                {
                    "issue": row["issue_id"],
                    "details": json.dumps(details, ensure_ascii=False),
                },
            )
            resolved += 1
        return resolved

    @staticmethod
    def record_run_issue(
        connection: Connection,
        run_id: UUID,
        *,
        rule_code: str,
        severity: str,
        message: str,
        details: Mapping[str, Any],
    ) -> int:
        return int(
            connection.execute(
                text(
                    """INSERT INTO meta.data_quality_issue
                    (pipeline_run_id,layer_name,entity_name,record_reference,
                     rule_code,severity,message,details,resolution_status)
                    VALUES (:run,'gold','gold.vehicle_feature_dataset',:reference,
                            :rule,:severity,:message,CAST(:details AS jsonb),'open')
                    RETURNING issue_id"""
                ),
                {
                    "run": run_id,
                    "reference": f"gold.publication_run:{run_id}",
                    "rule": rule_code,
                    "severity": severity,
                    "message": sanitize(message),
                    "details": json.dumps(safe_issue_details(details), ensure_ascii=False),
                },
            ).scalar_one()
        )

    @staticmethod
    def insert_dataset(
        connection: Connection,
        run_id: UUID,
        dataset_version: str,
        plan: GoldPublicationPlan,
        *,
        minimum_reference_month,
        maximum_reference_month,
    ) -> None:
        connection.execute(
            text(
                """INSERT INTO gold.vehicle_feature_dataset
                (dataset_version,publication_run_id,dataset_fingerprint,
                 scope_vehicle_type,source_name,status,expected_vehicle_count,
                 published_vehicle_count,blocked_vehicle_count,coverage_percentage,
                 minimum_reference_month,maximum_reference_month,
                 base_quality_status,is_active)
                VALUES (:dataset,:run,:fingerprint,:vehicle_type,:source,'building',
                        :expected,:published,:blocked,:coverage,:minimum,:maximum,
                        :quality,FALSE)"""
            ),
            {
                "dataset": dataset_version,
                "run": run_id,
                "fingerprint": plan.fingerprint,
                "vehicle_type": GOLD_VEHICLE_TYPE,
                "source": GOLD_SOURCE_NAME,
                "expected": plan.expected_count,
                "published": plan.published_count,
                "blocked": plan.blocked_count,
                "coverage": plan.coverage_percentage,
                "minimum": minimum_reference_month,
                "maximum": maximum_reference_month,
                "quality": plan.base_quality_status,
            },
        )

    @staticmethod
    def insert_snapshot(
        connection: Connection,
        run_id: UUID,
        dataset_version: str,
        candidates: Sequence[GoldSnapshotCandidate],
        published_at: datetime,
    ) -> None:
        statement = text(
            """INSERT INTO gold.vehicle_features_snapshot
            (dataset_version,vehicle_sk,vehicle_type,brand_name,model_name,
             version_name,model_year,is_zero_km,fuel_type,transmission_type,
             source_mapping_id,silver_price_id,fipe_code,year_code,
             source_vehicle_key,current_price,currency,price_source,
             price_reference_month,price_collected_at,data_confidence,
             base_quality_status,silver_identity_run_id,silver_mapping_run_id,
             silver_price_run_id,publication_run_id,published_at)
            VALUES (:dataset,:vehicle_sk,:vehicle_type,:brand,:model,:version,
                    :model_year,:zero_km,:fuel,:transmission,:mapping,:price_id,
                    :fipe_code,:year_code,:source_key,:price,:currency,:source,
                    :reference,:collected,:confidence,:quality,:identity_run,
                    :mapping_run,:price_run,:publication_run,:published_at)"""
        )
        parameters = [
            {
                "dataset": dataset_version,
                "vehicle_sk": item.vehicle_sk,
                "vehicle_type": item.vehicle_type,
                "brand": item.brand_name,
                "model": item.model_name,
                "version": item.version_name,
                "model_year": item.model_year,
                "zero_km": item.is_zero_km,
                "fuel": item.fuel_type,
                "transmission": item.transmission_type,
                "mapping": item.mapping_id,
                "price_id": item.silver_price_id,
                "fipe_code": item.fipe_code,
                "year_code": item.year_code,
                "source_key": item.source_vehicle_key,
                "price": item.current_price,
                "currency": item.currency,
                "source": item.price_source,
                "reference": item.price_reference_month,
                "collected": item.price_collected_at,
                "confidence": item.data_confidence,
                "quality": item.base_quality_status,
                "identity_run": item.silver_identity_run_id,
                "mapping_run": item.silver_mapping_run_id,
                "price_run": item.silver_price_run_id,
                "publication_run": run_id,
                "published_at": published_at,
            }
            for item in candidates
        ]
        connection.execute(statement, parameters)

    @staticmethod
    def activate_dataset(
        connection: Connection,
        run_id: UUID,
        dataset_version: str,
        *,
        previous_dataset_version: str | None,
        activation_type: str,
        activated_at: datetime,
    ) -> int:
        event_id = int(
            connection.execute(
                text(
                    """INSERT INTO gold.vehicle_feature_dataset_activation
                    (dataset_version,activation_run_id,previous_dataset_version,
                     activation_type,activated_at)
                    VALUES (:dataset,:run,:previous,:type,:activated)
                    RETURNING activation_event_id"""
                ),
                {
                    "dataset": dataset_version,
                    "run": run_id,
                    "previous": previous_dataset_version,
                    "type": activation_type,
                    "activated": activated_at,
                },
            ).scalar_one()
        )
        if previous_dataset_version is not None:
            connection.execute(
                text(
                    """UPDATE gold.vehicle_feature_dataset
                    SET status='retired',is_active=FALSE,retired_at=:activated
                    WHERE dataset_version=:previous AND is_active"""
                ),
                {"previous": previous_dataset_version, "activated": activated_at},
            )
        connection.execute(
            text(
                """UPDATE gold.vehicle_feature_dataset
                SET status='published',is_active=TRUE,
                    published_at=COALESCE(published_at,:activated),retired_at=NULL,
                    last_activation_event_id=:event,activation_run_id=:run
                WHERE dataset_version=:dataset"""
            ),
            {
                "dataset": dataset_version,
                "event": event_id,
                "run": run_id,
                "activated": activated_at,
            },
        )
        active_count = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM gold.vehicle_feature_dataset WHERE is_active"
                )
            ).scalar_one()
        )
        if active_count != 1:
            raise RuntimeError("Gold activation did not produce exactly one active dataset")
        return event_id

    @staticmethod
    def snapshot_vehicle_ids(
        connection: Connection,
        dataset_version: str,
    ) -> tuple[int, ...]:
        return tuple(
            int(value)
            for value in connection.execute(
                text(
                    """SELECT vehicle_sk
                    FROM gold.vehicle_features_snapshot
                    WHERE dataset_version=:dataset
                    ORDER BY vehicle_sk"""
                ),
                {"dataset": dataset_version},
            ).scalars()
        )

    @staticmethod
    def snapshot_base_quality_by_vehicle(
        connection: Connection,
        dataset_version: str,
    ) -> dict[int, str]:
        rows = connection.execute(
            text(
                """SELECT vehicle_sk,base_quality_status
                FROM gold.vehicle_features_snapshot
                WHERE dataset_version=:dataset
                ORDER BY vehicle_sk"""
            ),
            {"dataset": dataset_version},
        ).mappings()
        return {
            int(row["vehicle_sk"]): str(row["base_quality_status"])
            for row in rows
        }
