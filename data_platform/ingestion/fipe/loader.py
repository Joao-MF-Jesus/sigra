from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine

from data_platform.contracts.fipe import RawFipeRecord


class BronzeLoader:
    def __init__(self, engine: Engine):
        self.engine = engine

    def start_run(self, run_id: UUID, dataset_version: str, trigger_type: str, source_reference: str | None, git_commit: str | None) -> None:
        with self.engine.begin() as connection:
            connection.execute(text("""INSERT INTO meta.pipeline_run
                (pipeline_run_id,pipeline_name,pipeline_version,dataset_version,trigger_type,status,started_at,source_reference,git_commit)
                VALUES (:id,'fipe_vehicle_prices','fipe-ingestion-v1',:dataset,:trigger,'running',:started,:reference,:commit)"""),
                {"id": run_id, "dataset": dataset_version, "trigger": trigger_type, "started": datetime.now(UTC), "reference": source_reference, "commit": git_commit})

    def insert(self, run_id: UUID, record: RawFipeRecord) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(text("""INSERT INTO bronze.fipe_raw
                (pipeline_run_id,source_name,source_endpoint,vehicle_type,source_record_key,fipe_code,year_code,reference_month_raw,http_status,collected_at,payload,payload_hash,schema_fingerprint,raw_content_length,ingestion_status)
                VALUES (:run,:source,:endpoint,:vehicle_type,:record_key,:fipe_code,:year_code,:reference,:http_status,:collected_at,CAST(:payload AS jsonb),:payload_hash,:fingerprint,:raw_content_length,:ingestion_status)
                ON CONFLICT (source_name,source_endpoint,http_status,ingestion_status,payload_hash) DO NOTHING"""), {
                    "run": run_id, "source": record.source_name, "endpoint": record.source_endpoint,
                    "vehicle_type": record.vehicle_type, "record_key": record.source_record_key,
                    "fipe_code": record.fipe_code, "year_code": record.year_code,
                    "reference": record.reference_month_raw, "http_status": record.http_status,
                    "collected_at": record.collected_at,
                    "payload": __import__("json").dumps(record.payload, ensure_ascii=False) if record.payload is not None else None,
                    "payload_hash": record.payload_hash, "fingerprint": record.schema_fingerprint,
                    "raw_content_length": record.raw_content_length, "ingestion_status": record.ingestion_status,
                })
            return result.rowcount == 1

    def finish_run(self, run_id: UUID, status: str, received: int, inserted: int, duplicates: int, rejected: int, error_summary: str | None) -> None:
        with self.engine.begin() as connection:
            connection.execute(text("""UPDATE meta.pipeline_run SET status=:status,finished_at=:finished,
                records_received=:received,records_inserted=:inserted,records_deduplicated=:duplicates,
                records_rejected=:rejected,error_summary=:error WHERE pipeline_run_id=:id"""),
                {"id": run_id, "status": status, "finished": datetime.now(UTC), "received": received,
                 "inserted": inserted, "duplicates": duplicates, "rejected": rejected, "error": error_summary})
