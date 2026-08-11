from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from data_platform.tests.postgresql_safety import disposable_postgresql_url


POSTGRESQL_URL = disposable_postgresql_url()
REQUIRES_SAFE_POSTGRESQL = pytest.mark.skipif(
    not POSTGRESQL_URL,
    reason="PostgreSQL descartavel terminado em _test nao configurado",
)


def _config(monkeypatch):
    from alembic.config import Config

    root = Path(__file__).parents[2]
    monkeypatch.setenv("MIGRATION_DATABASE_URL", POSTGRESQL_URL)
    return Config(str(root / "backend" / "alembic.ini"))


@REQUIRES_SAFE_POSTGRESQL
def test_postgresql_orchestration_migration_contract_and_reupgrade(monkeypatch):
    from alembic import command
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.dialects.postgresql import JSONB, UUID
    from sqlalchemy.sql.sqltypes import DateTime

    config = _config(monkeypatch)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_engine(POSTGRESQL_URL)
    try:
        database = inspect(engine)
        assert {
            "orchestration_run",
            "orchestration_step_run",
            "pipeline_run",
            "data_quality_issue",
        }.issubset(database.get_table_names(schema="meta"))

        run_columns = {
            item["name"]: item
            for item in database.get_columns("orchestration_run", schema="meta")
        }
        step_columns = {
            item["name"]: item
            for item in database.get_columns(
                "orchestration_step_run",
                schema="meta",
            )
        }
        assert isinstance(run_columns["orchestration_run_id"]["type"], UUID)
        assert isinstance(run_columns["parameters"]["type"], JSONB)
        assert isinstance(run_columns["started_at"]["type"], DateTime)
        assert run_columns["started_at"]["type"].timezone is True
        assert isinstance(step_columns["metrics_summary"]["type"], JSONB)
        assert isinstance(step_columns["pipeline_run_id"]["type"], UUID)

        run_constraints = {
            item["name"]
            for item in database.get_check_constraints(
                "orchestration_run",
                schema="meta",
            )
        }
        step_constraints = {
            item["name"]
            for item in database.get_check_constraints(
                "orchestration_step_run",
                schema="meta",
            )
        }
        assert {
            "ck_orchestration_run_timestamps",
            "ck_orchestration_run_heartbeat",
            "ck_orchestration_run_terminal",
        }.issubset(run_constraints)
        assert {
            "ck_orchestration_step_attempt",
            "ck_orchestration_step_timestamps",
            "ck_orchestration_step_terminal",
            "ck_orchestration_step_dependency",
        }.issubset(step_constraints)

        run_uniques = {
            item["name"]
            for item in database.get_unique_constraints(
                "orchestration_run",
                schema="meta",
            )
        }
        step_uniques = {
            item["name"]
            for item in database.get_unique_constraints(
                "orchestration_step_run",
                schema="meta",
            )
        }
        assert "uq_orchestration_run_idempotency" in run_uniques
        assert "uq_orchestration_step_attempt" in step_uniques
        run_indexes = {
            item["name"]
            for item in database.get_indexes(
                "orchestration_run",
                schema="meta",
            )
        }
        assert "uq_orchestration_run_active_flow" in run_indexes

        step_foreign_keys = {
            item["name"]: item
            for item in database.get_foreign_keys(
                "orchestration_step_run",
                schema="meta",
            )
        }
        assert {
            "orchestration_run_id",
            "pipeline_run_id",
            "depends_on_step_run_id",
        } == {
            item["constrained_columns"][0]
            for item in step_foreign_keys.values()
        }
        step_indexes = {
            item["name"]
            for item in database.get_indexes(
                "orchestration_step_run",
                schema="meta",
            )
        }
        assert {
            "ix_orchestration_step_run_status",
            "ix_orchestration_step_pipeline_run",
            "ix_orchestration_step_dependency",
        }.issubset(step_indexes)

        with engine.connect() as connection:
            enums = {
                row["typname"]: tuple(row["labels"])
                for row in connection.execute(
                    text(
                        """SELECT type.typname,
                                  array_agg(enum.enumlabel ORDER BY enum.enumsortorder) AS labels
                           FROM pg_type AS type
                           JOIN pg_namespace AS namespace
                             ON namespace.oid=type.typnamespace
                           JOIN pg_enum AS enum ON enum.enumtypid=type.oid
                           WHERE namespace.nspname='meta'
                             AND type.typname LIKE 'orchestration_%'
                           GROUP BY type.typname"""
                    )
                ).mappings()
            }
        assert enums["orchestration_status"] == (
            "pending",
            "running",
            "succeeded",
            "partial",
            "failed",
            "skipped",
            "cancelled",
        )
        assert enums["orchestration_step"] == (
            "bronze",
            "silver",
            "gold",
            "pbev",
            "anp_fuel_prices",
        )
        assert enums["orchestration_trigger"] == (
            "manual",
            "scheduled",
            "retry",
            "backfill",
        )
    finally:
        engine.dispose()

    command.downgrade(config, "20260803_0004")
    engine = create_engine(POSTGRESQL_URL)
    try:
        database = inspect(engine)
        assert "orchestration_run" not in database.get_table_names(schema="meta")
        assert "orchestration_step_run" not in database.get_table_names(schema="meta")
        assert "pipeline_run" in database.get_table_names(schema="meta")
    finally:
        engine.dispose()
    command.upgrade(config, "head")


@REQUIRES_SAFE_POSTGRESQL
def test_postgresql_orchestration_repository_history_idempotency_and_lock(monkeypatch):
    from alembic import command
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import IntegrityError

    from data_platform.orchestration.contracts import (
        OrchestrationRequest,
        OrchestrationScope,
        OrchestrationStatus,
        StepName,
        utc_now,
    )
    from data_platform.orchestration.repository import (
        PostgresqlOrchestrationRepository,
    )

    config = _config(monkeypatch)
    command.upgrade(config, "head")
    engine = create_engine(POSTGRESQL_URL)
    repository = PostgresqlOrchestrationRepository(engine)
    pipeline_run_id = uuid4()
    started = datetime.now(UTC)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM meta.orchestration_step_run")
            )
            connection.execute(text("DELETE FROM meta.orchestration_run"))
            connection.execute(
                text(
                    """INSERT INTO meta.pipeline_run
                    (pipeline_run_id,pipeline_name,pipeline_version,dataset_version,
                     trigger_type,status,started_at,finished_at)
                    VALUES (:run,'orchestration_fixture','test','fixture','manual',
                            'succeeded',:started,:finished)"""
                ),
                {
                    "run": pipeline_run_id,
                    "started": started,
                    "finished": started + timedelta(seconds=1),
                },
            )

        request = OrchestrationRequest(
            idempotency_key="postgres-history",
            parameters={"password": "never-store", "batch": 7},
        )
        run = repository.create_run(
            uuid4(),
            request,
            request.resolved_idempotency_key(),
            started,
        )
        first = repository.create_step_attempt(
            run.orchestration_run_id,
            StepName.BRONZE,
            1,
            None,
            started,
        )
        repository.finish_step_attempt(
            first.orchestration_step_run_id,
            OrchestrationStatus.FAILED,
            started + timedelta(seconds=1),
            error="password=never-store",
        )
        second = repository.create_step_attempt(
            run.orchestration_run_id,
            StepName.BRONZE,
            2,
            None,
            started + timedelta(seconds=2),
        )
        completed = repository.finish_step_attempt(
            second.orchestration_step_run_id,
            OrchestrationStatus.SUCCEEDED,
            started + timedelta(seconds=3),
            pipeline_run_id=pipeline_run_id,
            metrics={"records_inserted": 4, "token": "never-store"},
        )
        repository.finish_run(
            run.orchestration_run_id,
            OrchestrationStatus.SUCCEEDED,
            started + timedelta(seconds=4),
        )
        persisted = repository.get_run_by_key(request.resolved_idempotency_key())
        attempts = repository.list_step_attempts(run.orchestration_run_id)
        assert persisted.status == OrchestrationStatus.SUCCEEDED
        assert persisted.parameters["password"] == "***"
        assert [item.attempt_number for item in attempts] == [1, 2]
        assert completed.pipeline_run_id == pipeline_run_id
        assert completed.metrics_summary["token"] == "***"
        assert "never-store" not in repr((persisted, attempts))

        anp_request = OrchestrationRequest(
            scope=OrchestrationScope.ANP,
            idempotency_key="postgres-anp-history",
        )
        anp_run = repository.create_run(
            uuid4(),
            anp_request,
            anp_request.resolved_idempotency_key(),
            started,
        )
        anp_step = repository.create_step_attempt(
            anp_run.orchestration_run_id,
            StepName.ANP,
            1,
            None,
            started,
        )
        repository.finish_step_attempt(
            anp_step.orchestration_step_run_id,
            OrchestrationStatus.SUCCEEDED,
            started + timedelta(seconds=1),
            pipeline_run_id=pipeline_run_id,
            metrics={"pipeline_status": "deduplicated"},
        )
        repository.finish_run(
            anp_run.orchestration_run_id,
            OrchestrationStatus.SUCCEEDED,
            started + timedelta(seconds=2),
        )
        persisted_anp = repository.get_run_by_key(
            anp_request.resolved_idempotency_key(),
            flow_name=anp_request.flow_name,
        )
        assert persisted_anp is not None
        assert persisted_anp.flow_name == "sigra_anp_fuel_prices_shadow"
        assert repository.list_step_attempts(
            anp_run.orchestration_run_id
        )[0].step_name == StepName.ANP

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """INSERT INTO meta.orchestration_run
                        (orchestration_run_id,flow_name,flow_version,idempotency_key,
                         trigger_type,start_step,status,started_at,finished_at,
                         heartbeat_at,parameters)
                        VALUES (:run,'sigra_fipe_medallion','orchestration-v1',
                                :key,'manual','bronze','succeeded',
                                :started,:finished,:finished,'{}'::jsonb)"""
                    ),
                    {
                        "run": uuid4(),
                        "key": request.resolved_idempotency_key(),
                        "started": started,
                        "finished": started + timedelta(seconds=1),
                    },
                )

        with repository.acquire_lock("postgres-lock-test") as first_lock:
            assert first_lock.acquired is True
            with repository.acquire_lock("postgres-lock-test") as second_lock:
                assert second_lock.acquired is False
    finally:
        engine.dispose()


@REQUIRES_SAFE_POSTGRESQL
def test_postgresql_orchestration_anp_idempotency_resume_partial_and_isolation(
    monkeypatch,
):
    from alembic import command
    from sqlalchemy import create_engine, text

    from data_platform.orchestration.contracts import (
        OrchestrationRequest,
        OrchestrationScope,
        OrchestrationStatus,
        PipelineBindings,
        StepName,
    )
    from data_platform.orchestration.policies import ExecutionPolicy
    from data_platform.orchestration.repository import (
        PostgresqlOrchestrationRepository,
    )
    from data_platform.orchestration.runner import OrchestrationRunner

    config = _config(monkeypatch)
    command.upgrade(config, "head")
    engine = create_engine(POSTGRESQL_URL)
    repository = PostgresqlOrchestrationRepository(engine)

    def succeeded(_context):
        return {"status": "succeeded", "records_inserted": 1}

    try:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM meta.orchestration_step_run"))
            connection.execute(text("DELETE FROM meta.orchestration_run"))
            anp_datasets_before = connection.execute(
                text("SELECT COUNT(*) FROM gold.anp_fuel_price_dataset")
            ).scalar_one()

        success_bindings = PipelineBindings(
            succeeded,
            succeeded,
            succeeded,
            succeeded,
            lambda _context: {"status": "deduplicated"},
        )
        runner = OrchestrationRunner(
            repository,
            success_bindings,
            policy=ExecutionPolicy(max_attempts=1, backoff_seconds=0),
        )
        request = OrchestrationRequest(
            scope=OrchestrationScope.ANP,
            idempotency_key="postgres-anp-idempotent",
        )
        first = runner.run(request)
        second = runner.run(request)
        assert first.status == OrchestrationStatus.SUCCEEDED
        assert second.reused is True
        assert second.orchestration_run_id == first.orchestration_run_id

        resume_calls = 0

        def fail_then_succeed(_context):
            nonlocal resume_calls
            resume_calls += 1
            return {"status": "failed" if resume_calls == 1 else "succeeded"}

        resume_runner = OrchestrationRunner(
            repository,
            PipelineBindings(
                succeeded,
                succeeded,
                succeeded,
                succeeded,
                fail_then_succeed,
            ),
            policy=ExecutionPolicy(max_attempts=1, backoff_seconds=0),
        )
        resume_request = OrchestrationRequest(
            scope=OrchestrationScope.ANP,
            idempotency_key="postgres-anp-resume",
        )
        failed = resume_runner.run(resume_request)
        resumed = resume_runner.run(
            OrchestrationRequest(
                scope=OrchestrationScope.ANP,
                idempotency_key="postgres-anp-resume",
                resume=True,
            )
        )
        assert failed.status == OrchestrationStatus.FAILED
        assert resumed.status == OrchestrationStatus.SUCCEEDED
        assert resumed.orchestration_run_id == failed.orchestration_run_id
        assert resume_calls == 2

        complete_runner = OrchestrationRunner(
            repository,
            PipelineBindings(
                succeeded,
                succeeded,
                succeeded,
                succeeded,
                lambda _context: {"status": "failed", "errors": ("blocked",)},
            ),
            policy=ExecutionPolicy(max_attempts=1, backoff_seconds=0),
        )
        partial = complete_runner.run(
            OrchestrationRequest(
                scope=OrchestrationScope.COMPLETE,
                idempotency_key="postgres-complete-partial",
            )
        )
        assert partial.status == OrchestrationStatus.PARTIAL
        assert [item.status for item in partial.steps[:-1]] == [
            OrchestrationStatus.SUCCEEDED,
        ] * 4
        assert partial.steps[-1].step_name == StepName.ANP
        assert partial.steps[-1].status == OrchestrationStatus.FAILED

        with repository.acquire_lock("sigra-orchestration:anp") as anp_lock:
            assert anp_lock.acquired is True
            with repository.acquire_lock("sigra-orchestration:pbev") as pbev_lock:
                assert pbev_lock.acquired is True
            with repository.acquire_lock("sigra-orchestration:anp") as duplicate:
                assert duplicate.acquired is False

        with engine.connect() as connection:
            counts = connection.execute(
                text(
                    """SELECT
                        (SELECT COUNT(*) FROM meta.orchestration_run) AS runs,
                        (SELECT COUNT(*) FROM meta.orchestration_step_run) AS steps,
                        (SELECT COUNT(*) FROM meta.orchestration_step_run
                         WHERE step_name='anp_fuel_prices') AS anp_steps,
                        (SELECT COUNT(*) FROM gold.anp_fuel_price_dataset) AS datasets"""
                )
            ).mappings().one()
        assert counts["runs"] == 3
        assert counts["steps"] == 8
        assert counts["anp_steps"] == 4
        assert counts["datasets"] == anp_datasets_before
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM meta.orchestration_step_run"))
            connection.execute(text("DELETE FROM meta.orchestration_run"))
        engine.dispose()
