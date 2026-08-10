from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime
import json
import threading
from typing import Any, Mapping, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from data_platform.common.logging import sanitize
from data_platform.orchestration.contracts import (
    FLOW_NAME,
    FLOW_VERSION,
    OrchestrationRequest,
    OrchestrationStatus,
    StepName,
    StoredRun,
    StoredStepRun,
    TriggerType,
    sanitize_mapping,
    utc_now,
)


class OrchestrationRepository(Protocol):
    def acquire_lock(self, lock_name: str) -> AbstractContextManager[Any]: ...

    def get_run(self, run_id: UUID) -> StoredRun | None: ...

    def get_run_by_key(self, idempotency_key: str) -> StoredRun | None: ...

    def get_active_run(self) -> StoredRun | None: ...

    def create_run(
        self,
        run_id: UUID,
        request: OrchestrationRequest,
        idempotency_key: str,
        now: datetime,
    ) -> StoredRun: ...

    def reopen_run(self, run_id: UUID, now: datetime) -> StoredRun: ...

    def heartbeat(self, run_id: UUID, now: datetime) -> None: ...

    def finish_run(
        self,
        run_id: UUID,
        status: OrchestrationStatus,
        now: datetime,
        error: str | None = None,
    ) -> StoredRun: ...

    def create_step_attempt(
        self,
        run_id: UUID,
        step_name: StepName,
        attempt_number: int,
        depends_on_step_run_id: int | None,
        now: datetime,
    ) -> StoredStepRun: ...

    def finish_step_attempt(
        self,
        step_run_id: int,
        status: OrchestrationStatus,
        now: datetime,
        *,
        pipeline_run_id: UUID | None = None,
        metrics: Mapping[str, Any] | None = None,
        error: str | None = None,
    ) -> StoredStepRun: ...

    def list_step_attempts(self, run_id: UUID) -> tuple[StoredStepRun, ...]: ...


def _stored_run(row: Mapping[str, Any]) -> StoredRun:
    return StoredRun(
        orchestration_run_id=row["orchestration_run_id"],
        flow_name=str(row["flow_name"]),
        flow_version=str(row["flow_version"]),
        idempotency_key=str(row["idempotency_key"]),
        trigger_type=TriggerType(str(row["trigger_type"])),
        start_step=StepName(str(row["start_step"])),
        status=OrchestrationStatus(str(row["status"])),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        heartbeat_at=row["heartbeat_at"],
        parameters=dict(row["parameters"] or {}),
        error_summary=(
            str(row["error_summary"]) if row["error_summary"] is not None else None
        ),
    )


def _stored_step(row: Mapping[str, Any]) -> StoredStepRun:
    return StoredStepRun(
        orchestration_step_run_id=int(row["orchestration_step_run_id"]),
        orchestration_run_id=row["orchestration_run_id"],
        step_name=StepName(str(row["step_name"])),
        attempt_number=int(row["attempt_number"]),
        status=OrchestrationStatus(str(row["status"])),
        pipeline_run_id=row["pipeline_run_id"],
        depends_on_step_run_id=(
            int(row["depends_on_step_run_id"])
            if row["depends_on_step_run_id"] is not None
            else None
        ),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        metrics_summary=dict(row["metrics_summary"] or {}),
        error_summary=(
            str(row["error_summary"]) if row["error_summary"] is not None else None
        ),
    )


class _PostgresqlRunLock:
    def __init__(self, engine: Engine, lock_name: str):
        self._connection: Connection | None = engine.connect()
        self._lock_name = lock_name
        self.acquired = bool(
            self._connection.execute(
                text("SELECT pg_try_advisory_lock(hashtext(:name)::bigint)"),
                {"name": lock_name},
            ).scalar_one()
        )

    def __enter__(self) -> "_PostgresqlRunLock":
        return self

    def __exit__(self, *_args: object) -> None:
        if self._connection is None:
            return
        try:
            if self.acquired:
                self._connection.execute(
                    text("SELECT pg_advisory_unlock(hashtext(:name)::bigint)"),
                    {"name": self._lock_name},
                )
                self._connection.commit()
        finally:
            self._connection.close()
            self._connection = None


class PostgresqlOrchestrationRepository:
    def __init__(self, engine: Engine):
        if engine.dialect.name != "postgresql":
            raise ValueError("Orchestration repository requires PostgreSQL")
        self.engine = engine

    def acquire_lock(self, lock_name: str) -> _PostgresqlRunLock:
        return _PostgresqlRunLock(self.engine, lock_name)

    def get_run(self, run_id: UUID) -> StoredRun | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    """SELECT * FROM meta.orchestration_run
                    WHERE orchestration_run_id=:run"""
                ),
                {"run": run_id},
            ).mappings().one_or_none()
        return _stored_run(row) if row is not None else None

    def get_run_by_key(self, idempotency_key: str) -> StoredRun | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    """SELECT * FROM meta.orchestration_run
                    WHERE flow_name=:flow AND idempotency_key=:key"""
                ),
                {"flow": FLOW_NAME, "key": idempotency_key},
            ).mappings().one_or_none()
        return _stored_run(row) if row is not None else None

    def get_active_run(self) -> StoredRun | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    """SELECT * FROM meta.orchestration_run
                    WHERE flow_name=:flow AND status='running'
                    ORDER BY heartbeat_at DESC
                    LIMIT 1"""
                ),
                {"flow": FLOW_NAME},
            ).mappings().one_or_none()
        return _stored_run(row) if row is not None else None

    def create_run(
        self,
        run_id: UUID,
        request: OrchestrationRequest,
        idempotency_key: str,
        now: datetime,
    ) -> StoredRun:
        with self.engine.begin() as connection:
            row = connection.execute(
                text(
                    """INSERT INTO meta.orchestration_run
                    (orchestration_run_id,flow_name,flow_version,idempotency_key,
                     trigger_type,start_step,status,started_at,heartbeat_at,parameters)
                    VALUES (:run,:flow,:version,:key,:trigger,:start,'running',
                            :now,:now,CAST(:parameters AS jsonb))
                    RETURNING *"""
                ),
                {
                    "run": run_id,
                    "flow": FLOW_NAME,
                    "version": FLOW_VERSION,
                    "key": idempotency_key,
                    "trigger": request.trigger_type.value,
                    "start": request.start_at.value,
                    "now": now,
                    "parameters": json.dumps(
                        request.safe_parameters,
                        ensure_ascii=False,
                    ),
                },
            ).mappings().one()
        return _stored_run(row)

    def reopen_run(self, run_id: UUID, now: datetime) -> StoredRun:
        with self.engine.begin() as connection:
            row = connection.execute(
                text(
                    """UPDATE meta.orchestration_run
                    SET status='running',finished_at=NULL,heartbeat_at=:now,
                        error_summary=NULL
                    WHERE orchestration_run_id=:run
                    RETURNING *"""
                ),
                {"run": run_id, "now": now},
            ).mappings().one()
        return _stored_run(row)

    def heartbeat(self, run_id: UUID, now: datetime) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """UPDATE meta.orchestration_run
                    SET heartbeat_at=:now
                    WHERE orchestration_run_id=:run AND status='running'"""
                ),
                {"run": run_id, "now": now},
            )

    def finish_run(
        self,
        run_id: UUID,
        status: OrchestrationStatus,
        now: datetime,
        error: str | None = None,
    ) -> StoredRun:
        if status in {OrchestrationStatus.PENDING, OrchestrationStatus.RUNNING}:
            raise ValueError("finish_run requires a terminal status")
        with self.engine.begin() as connection:
            row = connection.execute(
                text(
                    """UPDATE meta.orchestration_run
                    SET status=:status,finished_at=:now,heartbeat_at=:now,
                        error_summary=:error
                    WHERE orchestration_run_id=:run
                    RETURNING *"""
                ),
                {
                    "run": run_id,
                    "status": status.value,
                    "now": now,
                    "error": sanitize(error) if error else None,
                },
            ).mappings().one()
        return _stored_run(row)

    def create_step_attempt(
        self,
        run_id: UUID,
        step_name: StepName,
        attempt_number: int,
        depends_on_step_run_id: int | None,
        now: datetime,
    ) -> StoredStepRun:
        with self.engine.begin() as connection:
            row = connection.execute(
                text(
                    """INSERT INTO meta.orchestration_step_run
                    (orchestration_run_id,step_name,attempt_number,status,
                     depends_on_step_run_id,started_at)
                    VALUES (:run,:step,:attempt,'running',:dependency,:now)
                    RETURNING *"""
                ),
                {
                    "run": run_id,
                    "step": step_name.value,
                    "attempt": attempt_number,
                    "dependency": depends_on_step_run_id,
                    "now": now,
                },
            ).mappings().one()
        return _stored_step(row)

    def finish_step_attempt(
        self,
        step_run_id: int,
        status: OrchestrationStatus,
        now: datetime,
        *,
        pipeline_run_id: UUID | None = None,
        metrics: Mapping[str, Any] | None = None,
        error: str | None = None,
    ) -> StoredStepRun:
        if status in {OrchestrationStatus.PENDING, OrchestrationStatus.RUNNING}:
            raise ValueError("step completion requires a terminal status")
        with self.engine.begin() as connection:
            row = connection.execute(
                text(
                    """UPDATE meta.orchestration_step_run
                    SET status=:status,pipeline_run_id=:pipeline,finished_at=:now,
                        metrics_summary=CAST(:metrics AS jsonb),error_summary=:error
                    WHERE orchestration_step_run_id=:step_run
                    RETURNING *"""
                ),
                {
                    "step_run": step_run_id,
                    "status": status.value,
                    "pipeline": pipeline_run_id,
                    "now": now,
                    "metrics": json.dumps(
                        sanitize_mapping(metrics),
                        ensure_ascii=False,
                    ),
                    "error": sanitize(error) if error else None,
                },
            ).mappings().one()
        return _stored_step(row)

    def list_step_attempts(self, run_id: UUID) -> tuple[StoredStepRun, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    """SELECT * FROM meta.orchestration_step_run
                    WHERE orchestration_run_id=:run
                    ORDER BY orchestration_step_run_id"""
                ),
                {"run": run_id},
            ).mappings().all()
        return tuple(_stored_step(row) for row in rows)


class _MemoryRunLock:
    def __init__(self, lock: threading.Lock):
        self._lock = lock
        self.acquired = lock.acquire(blocking=False)

    def __enter__(self) -> "_MemoryRunLock":
        return self

    def __exit__(self, *_args: object) -> None:
        if self.acquired:
            self._lock.release()


class InMemoryOrchestrationRepository:
    """Repositorio deterministico para testes, sem banco ou chamadas externas."""

    def __init__(self):
        self._mutex = threading.RLock()
        self._locks: dict[str, threading.Lock] = {}
        self._runs: dict[UUID, StoredRun] = {}
        self._keys: dict[str, UUID] = {}
        self._steps: dict[int, StoredStepRun] = {}
        self._next_step_id = 1

    def acquire_lock(self, lock_name: str) -> _MemoryRunLock:
        with self._mutex:
            lock = self._locks.setdefault(lock_name, threading.Lock())
        return _MemoryRunLock(lock)

    def get_run(self, run_id: UUID) -> StoredRun | None:
        with self._mutex:
            return self._runs.get(run_id)

    def get_run_by_key(self, idempotency_key: str) -> StoredRun | None:
        with self._mutex:
            run_id = self._keys.get(idempotency_key)
            return self._runs.get(run_id) if run_id is not None else None

    def get_active_run(self) -> StoredRun | None:
        with self._mutex:
            active = [
                run
                for run in self._runs.values()
                if run.flow_name == FLOW_NAME
                and run.status == OrchestrationStatus.RUNNING
            ]
            return max(active, key=lambda run: run.heartbeat_at) if active else None

    def create_run(
        self,
        run_id: UUID,
        request: OrchestrationRequest,
        idempotency_key: str,
        now: datetime,
    ) -> StoredRun:
        run = StoredRun(
            orchestration_run_id=run_id,
            flow_name=FLOW_NAME,
            flow_version=FLOW_VERSION,
            idempotency_key=idempotency_key,
            trigger_type=request.trigger_type,
            start_step=request.start_at,
            status=OrchestrationStatus.RUNNING,
            started_at=now,
            finished_at=None,
            heartbeat_at=now,
            parameters=request.safe_parameters,
        )
        with self._mutex:
            if idempotency_key in self._keys:
                return self._runs[self._keys[idempotency_key]]
            self._runs[run_id] = run
            self._keys[idempotency_key] = run_id
        return run

    def reopen_run(self, run_id: UUID, now: datetime) -> StoredRun:
        with self._mutex:
            current = self._runs[run_id]
            run = StoredRun(
                **{
                    **current.__dict__,
                    "status": OrchestrationStatus.RUNNING,
                    "finished_at": None,
                    "heartbeat_at": now,
                    "error_summary": None,
                }
            )
            self._runs[run_id] = run
            return run

    def heartbeat(self, run_id: UUID, now: datetime) -> None:
        with self._mutex:
            current = self._runs[run_id]
            self._runs[run_id] = StoredRun(
                **{**current.__dict__, "heartbeat_at": now}
            )

    def finish_run(
        self,
        run_id: UUID,
        status: OrchestrationStatus,
        now: datetime,
        error: str | None = None,
    ) -> StoredRun:
        with self._mutex:
            current = self._runs[run_id]
            run = StoredRun(
                **{
                    **current.__dict__,
                    "status": status,
                    "finished_at": now,
                    "heartbeat_at": now,
                    "error_summary": sanitize(error) if error else None,
                }
            )
            self._runs[run_id] = run
            return run

    def create_step_attempt(
        self,
        run_id: UUID,
        step_name: StepName,
        attempt_number: int,
        depends_on_step_run_id: int | None,
        now: datetime,
    ) -> StoredStepRun:
        with self._mutex:
            step_run_id = self._next_step_id
            self._next_step_id += 1
            step = StoredStepRun(
                orchestration_step_run_id=step_run_id,
                orchestration_run_id=run_id,
                step_name=step_name,
                attempt_number=attempt_number,
                status=OrchestrationStatus.RUNNING,
                pipeline_run_id=None,
                depends_on_step_run_id=depends_on_step_run_id,
                started_at=now,
                finished_at=None,
                metrics_summary={},
            )
            self._steps[step_run_id] = step
            return step

    def finish_step_attempt(
        self,
        step_run_id: int,
        status: OrchestrationStatus,
        now: datetime,
        *,
        pipeline_run_id: UUID | None = None,
        metrics: Mapping[str, Any] | None = None,
        error: str | None = None,
    ) -> StoredStepRun:
        with self._mutex:
            current = self._steps[step_run_id]
            step = StoredStepRun(
                **{
                    **current.__dict__,
                    "status": status,
                    "pipeline_run_id": pipeline_run_id,
                    "finished_at": now,
                    "metrics_summary": sanitize_mapping(metrics),
                    "error_summary": sanitize(error) if error else None,
                }
            )
            self._steps[step_run_id] = step
            return step

    def list_step_attempts(self, run_id: UUID) -> tuple[StoredStepRun, ...]:
        with self._mutex:
            return tuple(
                step
                for step in self._steps.values()
                if step.orchestration_run_id == run_id
            )

    def force_heartbeat(self, run_id: UUID, heartbeat_at: datetime) -> None:
        """Apoio explicito a testes de recuperacao de execucao stale."""
        with self._mutex:
            current = self._runs[run_id]
            self._runs[run_id] = StoredRun(
                **{**current.__dict__, "heartbeat_at": heartbeat_at}
            )


def latest_step_attempts(
    attempts: tuple[StoredStepRun, ...],
) -> dict[StepName, StoredStepRun]:
    latest: dict[StepName, StoredStepRun] = {}
    for attempt in attempts:
        previous = latest.get(attempt.step_name)
        if previous is None or attempt.attempt_number > previous.attempt_number:
            latest[attempt.step_name] = attempt
    return latest


def repository_result(
    repository: OrchestrationRepository,
    run_id: UUID,
) -> tuple[StoredRun, tuple[StoredStepRun, ...]]:
    run = repository.get_run(run_id)
    if run is None:
        raise KeyError(f"orchestration run not found: {run_id}")
    return run, repository.list_step_attempts(run_id)
