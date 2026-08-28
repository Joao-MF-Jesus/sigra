from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import importlib
import inspect
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from data_platform.contracts.anp_fuel_prices import AnpPipelineResult
from data_platform.orchestration.cli import build_parser
from data_platform.orchestration.contracts import (
    FLOW_NAME,
    CancellationToken,
    ConcurrentOrchestrationError,
    OrchestrationRequest,
    OrchestrationScope,
    OrchestrationStatus,
    PartialPolicy,
    PermanentStepError,
    PipelineBindings,
    StepName,
    TransientStepError,
    TriggerType,
    utc_now,
)
from data_platform.orchestration.policies import ExecutionPolicy
from data_platform.orchestration.prefect_flow import (
    PrefectScheduleConfig,
    PrefectUnavailableError,
    build_prefect_components,
    prefect_available,
    serve_prefect_flow,
)
from data_platform.orchestration.repository import InMemoryOrchestrationRepository
from data_platform.orchestration.runner import OrchestrationRunner, build_default_bindings


INTEGRATED_REQUEST_ARGS = {
    "integrated_geography_level": "state",
    "integrated_geography_key": "SP",
    "integrated_week_start": date(2026, 8, 3),
}


@dataclass(frozen=True)
class PipelineResult:
    status: str = "succeeded"
    pipeline_run_id: str | None = None
    records_received: int = 3
    records_inserted: int = 2
    records_rejected: int = 0
    published_count: int = 0
    errors: tuple[str, ...] = ()


def result(status="succeeded", *, error=None):
    return PipelineResult(
        status=status,
        pipeline_run_id=str(uuid4()) if status != "skipped" else None,
        errors=(error,) if error else (),
    )


def bindings_for(executors=None, calls=None):
    executors = executors or {}
    calls = calls if calls is not None else []

    def executor(step_name):
        def execute(context):
            calls.append(step_name)
            custom = executors.get(step_name)
            return custom(context) if custom else result()

        return execute

    return PipelineBindings(
        executor(StepName.BRONZE),
        executor(StepName.SILVER),
        executor(StepName.GOLD),
        executor(StepName.PBEV),
        executor(StepName.ANP),
        executor(StepName.INTEGRATED_VEHICLE_COST),
    )


def make_runner(*, executors=None, calls=None, repository=None, policy=None):
    repository = repository or InMemoryOrchestrationRepository()
    runner = OrchestrationRunner(
        repository,
        bindings_for(executors, calls),
        policy=policy
        or ExecutionPolicy(max_attempts=2, backoff_seconds=0, sleep=lambda _: None),
    )
    return runner, repository


def test_complete_success_executes_bronze_silver_gold_in_order():
    calls = []
    runner, repository = make_runner(calls=calls)
    outcome = runner.run(OrchestrationRequest(idempotency_key="ordered"))
    assert calls == [StepName.BRONZE, StepName.SILVER, StepName.GOLD]
    assert outcome.status == OrchestrationStatus.SUCCEEDED
    assert [item.status for item in outcome.steps] == [
        OrchestrationStatus.SUCCEEDED,
        OrchestrationStatus.SUCCEEDED,
        OrchestrationStatus.SUCCEEDED,
    ]
    attempts = repository.list_step_attempts(UUID(outcome.orchestration_run_id))
    assert attempts[1].depends_on_step_run_id == attempts[0].orchestration_step_run_id
    assert attempts[2].depends_on_step_run_id == attempts[1].orchestration_step_run_id


def test_partial_continues_explicitly_and_marks_overall_partial():
    calls = []
    runner, _ = make_runner(
        calls=calls,
        executors={StepName.BRONZE: lambda _context: result("partial")},
    )
    outcome = runner.run(OrchestrationRequest(idempotency_key="partial-continue"))
    assert calls == [StepName.BRONZE, StepName.SILVER, StepName.GOLD]
    assert outcome.status == OrchestrationStatus.PARTIAL


def test_partial_stop_skips_downstream_dependencies():
    calls = []
    runner, _ = make_runner(
        calls=calls,
        executors={StepName.BRONZE: lambda _context: result("partial")},
        policy=ExecutionPolicy(
            max_attempts=1,
            backoff_seconds=0,
            partial_policy=PartialPolicy.STOP,
        ),
    )
    outcome = runner.run(OrchestrationRequest(idempotency_key="partial-stop"))
    assert calls == [StepName.BRONZE]
    assert outcome.status == OrchestrationStatus.PARTIAL
    assert outcome.steps[1].skip_reason == "dependency_bronze_partial"
    assert outcome.steps[2].skip_reason == "dependency_silver_skipped"


def test_partial_fail_policy_fails_the_orchestration():
    runner, _ = make_runner(
        executors={StepName.BRONZE: lambda _context: result("partial")},
        policy=ExecutionPolicy(
            max_attempts=1,
            backoff_seconds=0,
            partial_policy=PartialPolicy.FAIL,
        ),
    )
    outcome = runner.run(OrchestrationRequest(idempotency_key="partial-fail"))
    assert outcome.status == OrchestrationStatus.FAILED


def test_bronze_failure_blocks_silver_and_gold():
    calls = []
    runner, _ = make_runner(
        calls=calls,
        executors={StepName.BRONZE: lambda _context: result("failed", error="bronze")},
    )
    outcome = runner.run(OrchestrationRequest(idempotency_key="bronze-fail"))
    assert calls == [StepName.BRONZE]
    assert outcome.status == OrchestrationStatus.FAILED
    assert [item.status for item in outcome.steps] == [
        OrchestrationStatus.FAILED,
        OrchestrationStatus.SKIPPED,
        OrchestrationStatus.SKIPPED,
    ]


def test_silver_failure_blocks_gold():
    calls = []
    runner, _ = make_runner(
        calls=calls,
        executors={StepName.SILVER: lambda _context: result("rejected")},
    )
    outcome = runner.run(OrchestrationRequest(idempotency_key="silver-fail"))
    assert calls == [StepName.BRONZE, StepName.SILVER]
    assert outcome.steps[-1].skip_reason == "dependency_silver_failed"
    assert outcome.status == OrchestrationStatus.FAILED


def test_gold_failure_does_not_change_prior_successes():
    calls = []
    runner, _ = make_runner(
        calls=calls,
        executors={StepName.GOLD: lambda _context: result("failed")},
    )
    outcome = runner.run(OrchestrationRequest(idempotency_key="gold-fail"))
    assert calls == [StepName.BRONZE, StepName.SILVER, StepName.GOLD]
    assert outcome.status == OrchestrationStatus.FAILED
    assert [item.status for item in outcome.steps[:2]] == [
        OrchestrationStatus.SUCCEEDED,
        OrchestrationStatus.SUCCEEDED,
    ]


def test_transient_failure_retries_with_backoff_and_new_attempt():
    calls = []
    sleeps = []

    def flaky(_context):
        if len(calls) == 1:
            raise TransientStepError("temporary")
        return result()

    runner, repository = make_runner(
        calls=calls,
        executors={StepName.BRONZE: flaky},
        policy=ExecutionPolicy(
            max_attempts=2,
            backoff_seconds=0.25,
            sleep=sleeps.append,
        ),
    )
    outcome = runner.run(OrchestrationRequest(idempotency_key="retry"))
    assert outcome.status == OrchestrationStatus.SUCCEEDED
    assert calls.count(StepName.BRONZE) == 2
    assert sleeps == [0.25]
    attempts = repository.list_step_attempts(UUID(outcome.orchestration_run_id))
    assert [item.attempt_number for item in attempts if item.step_name == StepName.BRONZE] == [1, 2]


def test_permanent_failure_is_not_retried():
    calls = []

    def permanent(_context):
        raise PermanentStepError("invalid contract")

    runner, _ = make_runner(
        calls=calls,
        executors={StepName.BRONZE: permanent},
    )
    outcome = runner.run(OrchestrationRequest(idempotency_key="permanent"))
    assert outcome.status == OrchestrationStatus.FAILED
    assert calls == [StepName.BRONZE]


def test_same_idempotency_key_returns_existing_terminal_result():
    calls = []
    runner, repository = make_runner(calls=calls)
    request = OrchestrationRequest(idempotency_key="same-key")
    first = runner.run(request)
    second = runner.run(request)
    assert second.reused is True
    assert second.orchestration_run_id == first.orchestration_run_id
    assert calls == [StepName.BRONZE, StepName.SILVER, StepName.GOLD]
    assert len(repository._runs) == 1


def test_incompatible_concurrent_run_is_rejected_by_flow_lock():
    repository = InMemoryOrchestrationRepository()
    entered = threading.Event()
    release = threading.Event()

    def blocking(_context):
        entered.set()
        assert release.wait(timeout=5)
        return result()

    first, _ = make_runner(
        repository=repository,
        executors={StepName.BRONZE: blocking},
    )
    second, _ = make_runner(repository=repository)
    thread_result = []
    worker = threading.Thread(
        target=lambda: thread_result.append(
            first.run(OrchestrationRequest(idempotency_key="concurrent-a"))
        )
    )
    worker.start()
    assert entered.wait(timeout=5)
    with pytest.raises(ConcurrentOrchestrationError):
        second.run(OrchestrationRequest(idempotency_key="concurrent-b"))
    release.set()
    worker.join(timeout=5)
    assert thread_result[0].status == OrchestrationStatus.SUCCEEDED


def test_resume_reuses_completed_bronze_and_retries_only_incomplete_steps():
    calls = []
    silver_calls = 0

    def silver(_context):
        nonlocal silver_calls
        silver_calls += 1
        return result("failed") if silver_calls == 1 else result()

    runner, _ = make_runner(
        calls=calls,
        executors={StepName.SILVER: silver},
        policy=ExecutionPolicy(max_attempts=1, backoff_seconds=0),
    )
    request = OrchestrationRequest(idempotency_key="resume")
    first = runner.run(request)
    resumed = runner.run(
        OrchestrationRequest(idempotency_key="resume", resume=True)
    )
    assert first.status == OrchestrationStatus.FAILED
    assert resumed.status == OrchestrationStatus.SUCCEEDED
    assert calls.count(StepName.BRONZE) == 1
    assert calls.count(StepName.SILVER) == 2
    assert calls.count(StepName.GOLD) == 1


def test_recent_running_idempotent_run_is_blocked_and_stale_run_is_recovered():
    repository = InMemoryOrchestrationRepository()
    request = OrchestrationRequest(idempotency_key="stale")
    run = repository.create_run(
        uuid4(),
        request,
        request.resolved_idempotency_key(),
        utc_now(),
    )
    runner, _ = make_runner(
        repository=repository,
        policy=ExecutionPolicy(
            max_attempts=1,
            backoff_seconds=0,
            stale_after=timedelta(seconds=1),
        ),
    )
    with pytest.raises(ConcurrentOrchestrationError):
        runner.run(request)
    running_step = repository.create_step_attempt(
        run.orchestration_run_id,
        StepName.BRONZE,
        1,
        None,
        utc_now(),
    )
    repository.force_heartbeat(run.orchestration_run_id, utc_now() - timedelta(seconds=2))
    recovered = runner.run(request)
    assert recovered.status == OrchestrationStatus.SUCCEEDED
    attempts = repository.list_step_attempts(run.orchestration_run_id)
    assert attempts[0].orchestration_step_run_id == running_step.orchestration_step_run_id
    assert attempts[0].status == OrchestrationStatus.CANCELLED


def test_stale_run_with_different_key_is_cancelled_before_new_run():
    repository = InMemoryOrchestrationRepository()
    previous_request = OrchestrationRequest(idempotency_key="old-key")
    previous = repository.create_run(
        uuid4(),
        previous_request,
        previous_request.resolved_idempotency_key(),
        utc_now() - timedelta(minutes=10),
    )
    repository.force_heartbeat(
        previous.orchestration_run_id,
        utc_now() - timedelta(minutes=10),
    )
    runner, _ = make_runner(
        repository=repository,
        policy=ExecutionPolicy(
            max_attempts=1,
            backoff_seconds=0,
            stale_after=timedelta(minutes=1),
        ),
    )
    outcome = runner.run(OrchestrationRequest(idempotency_key="new-key"))
    assert outcome.status == OrchestrationStatus.SUCCEEDED
    assert repository.get_run(previous.orchestration_run_id).status == (
        OrchestrationStatus.CANCELLED
    )


def test_cooperative_timeout_is_recorded_and_blocks_downstream():
    calls = []

    def times_out(context):
        time.sleep(0.01)
        context.checkpoint()

    runner, _ = make_runner(
        calls=calls,
        executors={StepName.BRONZE: times_out},
        policy=ExecutionPolicy(
            max_attempts=1,
            backoff_seconds=0,
            timeout_seconds={StepName.BRONZE: 0.001},
        ),
    )
    outcome = runner.run(OrchestrationRequest(idempotency_key="timeout"))
    assert outcome.status == OrchestrationStatus.FAILED
    assert "timed out" in (outcome.steps[0].error or "")
    assert calls == [StepName.BRONZE]


def test_cancellation_is_persisted_without_running_downstream():
    token = CancellationToken()

    def cancel(context):
        token.cancel()
        context.checkpoint()

    runner, _ = make_runner(executors={StepName.BRONZE: cancel})
    outcome = runner.run(
        OrchestrationRequest(idempotency_key="cancel"),
        cancellation_token=token,
    )
    assert outcome.status == OrchestrationStatus.CANCELLED
    assert outcome.steps[0].status == OrchestrationStatus.CANCELLED


def test_keyboard_interrupt_is_normalized_as_cancellation():
    def interrupt(_context):
        raise KeyboardInterrupt

    runner, _ = make_runner(executors={StepName.BRONZE: interrupt})
    outcome = runner.run(OrchestrationRequest(idempotency_key="interrupt"))
    assert outcome.status == OrchestrationStatus.CANCELLED
    assert outcome.steps[0].status == OrchestrationStatus.CANCELLED


def test_errors_and_parameters_are_sanitized_before_persistence():
    secret = "synthetic-test-secret"

    def unsafe(_context):
        raise PermanentStepError(
            f"password={secret} "
            "postgresql://synthetic-test-user:synthetic-test-secret@localhost/db_test"
        )

    runner, repository = make_runner(executors={StepName.BRONZE: unsafe})
    outcome = runner.run(
        OrchestrationRequest(
            idempotency_key="sanitize",
            parameters={
                "token": secret,
                "note": f"password={secret}",
                "nested": [{"password": secret}],
            },
        )
    )
    stored = repository.get_run(UUID(outcome.orchestration_run_id))
    serialized = repr((outcome, stored, repository.list_step_attempts(stored.orchestration_run_id)))
    assert secret not in serialized
    assert "alice" not in serialized
    assert stored.idempotency_key != "sanitize"


def test_dry_run_has_no_repository_write_or_pipeline_call():
    calls = []
    runner, repository = make_runner(calls=calls)
    outcome = runner.run(
        OrchestrationRequest(dry_run=True, idempotency_key="dry-run")
    )
    assert outcome.dry_run is True
    assert outcome.status == OrchestrationStatus.SUCCEEDED
    assert calls == []
    assert repository._runs == {}
    assert all(item.status == OrchestrationStatus.SKIPPED for item in outcome.steps)


@pytest.mark.parametrize(
    "start_at,expected_calls,skip_count",
    [
        (StepName.SILVER, [StepName.SILVER, StepName.GOLD], 1),
        (StepName.GOLD, [StepName.GOLD], 2),
    ],
)
def test_execution_can_start_at_silver_or_gold(start_at, expected_calls, skip_count):
    calls = []
    runner, _ = make_runner(calls=calls)
    outcome = runner.run(
        OrchestrationRequest(start_at=start_at, idempotency_key=f"from-{start_at}")
    )
    assert calls == expected_calls
    assert outcome.status == OrchestrationStatus.SUCCEEDED
    assert sum(item.status == OrchestrationStatus.SKIPPED for item in outcome.steps) == skip_count


def test_prefect_is_optional_and_missing_dependency_has_clear_error(monkeypatch):
    original = importlib.import_module

    def missing(name, *args, **kwargs):
        if name == "prefect":
            raise ImportError("not installed")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", missing)
    runner, _ = make_runner()
    assert prefect_available() is False
    with pytest.raises(PrefectUnavailableError, match="optional"):
        build_prefect_components(runner)


def test_prefect_adapter_runs_locally_without_server(monkeypatch):
    def decorator(**_options):
        return lambda function: function

    fake_prefect = SimpleNamespace(task=decorator, flow=decorator)
    monkeypatch.setattr(importlib, "import_module", lambda name: fake_prefect)
    calls = []
    runner, _ = make_runner(calls=calls)
    components = build_prefect_components(runner)
    outcome = components.flow(OrchestrationRequest(idempotency_key="prefect-local"))
    assert outcome.status == OrchestrationStatus.SUCCEEDED
    assert calls == [StepName.BRONZE, StepName.SILVER, StepName.GOLD]
    assert set(components.tasks) == set(StepName)


def test_prefect_schedule_is_configured_without_starting_real_server(monkeypatch):
    served = {}

    class FakeFlow:
        def __init__(self, function):
            self.function = function

        def __call__(self, *args, **kwargs):
            return self.function(*args, **kwargs)

        def serve(self, **kwargs):
            served.update(kwargs)
            return "configured"

    def flow_decorator(**_options):
        return lambda function: FakeFlow(function)

    def task_decorator(**_options):
        return lambda function: function

    fake_prefect = SimpleNamespace(task=task_decorator, flow=flow_decorator)
    fake_schedules = SimpleNamespace(
        Cron=lambda cron, timezone: {"cron": cron, "timezone": timezone}
    )
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: fake_schedules if name == "prefect.schedules" else fake_prefect,
    )
    runner, _ = make_runner()
    configured = serve_prefect_flow(
        runner,
        PrefectScheduleConfig("0 3 * * *"),
        OrchestrationRequest(idempotency_key="scheduled"),
    )
    assert configured == "configured"
    assert served["name"] == "sigra-fipe-medallion"
    assert served["schedule"] == {
        "cron": "0 3 * * *",
        "timezone": "America/Sao_Paulo",
    }
    assert "request" in served["parameters"]


def test_prefect_scheduled_run_uses_flow_run_id_for_idempotency(monkeypatch):
    def decorator(**_options):
        return lambda function: function

    fake_prefect = SimpleNamespace(
        task=decorator,
        flow=decorator,
        runtime=SimpleNamespace(flow_run=SimpleNamespace(id="scheduled-run-123")),
    )
    monkeypatch.setattr(importlib, "import_module", lambda _name: fake_prefect)
    runner, _ = make_runner()
    outcome = build_prefect_components(runner).flow(
        OrchestrationRequest(trigger_type=TriggerType.SCHEDULED)
    )
    expected = OrchestrationRequest(
        trigger_type=TriggerType.SCHEDULED,
        idempotency_key="prefect-flow-run:scheduled-run-123",
    ).resolved_idempotency_key()
    assert outcome.idempotency_key == expected


def test_orchestration_source_uses_python_functions_not_subprocesses():
    source = inspect.getsource(build_default_bindings)
    assert "run_pipeline(" in source
    assert "run_silver_pipeline(" in source
    assert "run_gold_publication(" in source
    assert "run_integrated_vehicle_cost_pipeline(" in source
    assert "import subprocess" not in source
    assert "subprocess." not in source


def test_migration_declares_postgresql_metadata_and_sqlite_guard():
    migration = (
        Path(__file__).parents[2]
        / "backend"
        / "alembic"
        / "versions"
        / "20260810_0005_data_platform_orchestration.py"
    ).read_text(encoding="utf-8")
    for marker in (
        "meta.orchestration_status",
        "orchestration_run",
        "orchestration_step_run",
        "uq_orchestration_run_idempotency",
        "pipeline_run_id",
        "depends_on_step_run_id",
        "if not _is_postgresql()",
        'down_revision: Union[str, None] = "20260803_0004"',
    ):
        assert marker in migration

    scope_migration = (
        Path(__file__).parents[2]
        / "backend"
        / "alembic"
        / "versions"
        / "20260811_0008_data_platform_orchestration_scopes.py"
    ).read_text(encoding="utf-8")
    for marker in (
        'down_revision: Union[str, None] = "20260811_0007"',
        '"pbev", "anp_fuel_prices"',
        "orchestration scope downgrade blocked",
        "if not _is_postgresql()",
    ):
        assert marker in scope_migration


@pytest.mark.parametrize(
    "scope,expected_calls",
    [
        (OrchestrationScope.FIPE, [StepName.BRONZE, StepName.SILVER, StepName.GOLD]),
        (OrchestrationScope.PBEV, [StepName.PBEV]),
        (OrchestrationScope.ANP, [StepName.ANP]),
        (
            OrchestrationScope.INTEGRATED_VEHICLE_COST,
            [StepName.INTEGRATED_VEHICLE_COST],
        ),
        (OrchestrationScope.COMPLETE, list(StepName)),
    ],
)
def test_explicit_scope_executes_only_its_declared_pipeline_units(
    scope,
    expected_calls,
):
    calls = []
    runner, _ = make_runner(calls=calls)
    outcome = runner.run(
        OrchestrationRequest(
            scope=scope,
            idempotency_key=f"scope-{scope.value}",
            **(
                INTEGRATED_REQUEST_ARGS
                if scope
                in {
                    OrchestrationScope.INTEGRATED_VEHICLE_COST,
                    OrchestrationScope.COMPLETE,
                }
                else {}
            ),
        )
    )
    assert outcome.status == OrchestrationStatus.SUCCEEDED
    assert outcome.scope == scope
    assert calls == expected_calls
    assert [item.step_name for item in outcome.steps] == expected_calls


def test_anp_deduplicated_is_successful_and_observable():
    bronze_run = uuid4()
    silver_run = uuid4()
    gold_run = uuid4()
    runner, _ = make_runner(
        executors={
            StepName.ANP: lambda _context: AnpPipelineResult(
                status="deduplicated",
                dataset_version="anp-shadow-test",
                pipeline_run_ids=(bronze_run, silver_run, gold_run),
                asset_sha256="a" * 64,
                layout_fingerprint="b" * 64,
                rows_received=42,
                observations_current=40,
                snapshots_published=12,
                issues=0,
            )
        }
    )
    outcome = runner.run(
        OrchestrationRequest(
            scope=OrchestrationScope.ANP,
            idempotency_key="anp-deduplicated",
        )
    )
    assert outcome.status == OrchestrationStatus.SUCCEEDED
    assert outcome.steps[0].status == OrchestrationStatus.SUCCEEDED
    assert outcome.steps[0].pipeline_run_id == str(gold_run)
    assert outcome.steps[0].metrics["pipeline_status"] == "deduplicated"
    assert outcome.steps[0].metrics["pipeline_run_ids"] == [
        str(bronze_run),
        str(silver_run),
        str(gold_run),
    ]
    assert outcome.steps[0].metrics["rows_received"] == 42


def test_complete_anp_failure_is_partial_and_preserves_completed_branches():
    calls = []
    runner, _ = make_runner(
        calls=calls,
        executors={
            StepName.ANP: lambda _context: result("failed", error="anp blocked")
        },
    )
    outcome = runner.run(
        OrchestrationRequest(
            scope=OrchestrationScope.COMPLETE,
            idempotency_key="complete-anp-failure",
            **INTEGRATED_REQUEST_ARGS,
        )
    )
    assert calls == list(StepName)[:-1]
    assert outcome.status == OrchestrationStatus.PARTIAL
    assert [item.status for item in outcome.steps[:-2]] == [
        OrchestrationStatus.SUCCEEDED,
    ] * 4
    assert outcome.steps[-2].status == OrchestrationStatus.FAILED
    assert outcome.steps[-1].status == OrchestrationStatus.SKIPPED
    assert outcome.steps[-1].skip_reason == "dependency_anp_fuel_prices_failed"


def test_complete_pbev_failure_does_not_block_anp():
    calls = []
    runner, _ = make_runner(
        calls=calls,
        executors={
            StepName.PBEV: lambda _context: result("failed", error="pbev blocked")
        },
    )
    outcome = runner.run(
        OrchestrationRequest(
            scope=OrchestrationScope.COMPLETE,
            idempotency_key="complete-pbev-failure",
            **INTEGRATED_REQUEST_ARGS,
        )
    )
    assert calls == list(StepName)[:-1]
    assert outcome.status == OrchestrationStatus.PARTIAL
    assert outcome.steps[-2].step_name == StepName.ANP
    assert outcome.steps[-2].status == OrchestrationStatus.SUCCEEDED
    assert outcome.steps[-1].step_name == StepName.INTEGRATED_VEHICLE_COST
    assert outcome.steps[-1].status == OrchestrationStatus.SKIPPED


def test_complete_runs_integrated_only_after_all_required_sources():
    calls = []
    runner, _ = make_runner(calls=calls)
    outcome = runner.run(
        OrchestrationRequest(
            scope=OrchestrationScope.COMPLETE,
            idempotency_key="complete-integrated-order",
            **INTEGRATED_REQUEST_ARGS,
        )
    )
    assert outcome.status == OrchestrationStatus.SUCCEEDED
    assert calls == list(StepName)
    assert calls[-4:] == [
        StepName.GOLD,
        StepName.PBEV,
        StepName.ANP,
        StepName.INTEGRATED_VEHICLE_COST,
    ]


def test_integrated_failure_after_sources_marks_complete_run_partial():
    calls = []
    runner, _ = make_runner(
        calls=calls,
        executors={
            StepName.INTEGRATED_VEHICLE_COST: lambda _context: result(
                "failed", error="integrated blocked"
            )
        },
    )
    outcome = runner.run(
        OrchestrationRequest(
            scope=OrchestrationScope.COMPLETE,
            idempotency_key="complete-integrated-failure",
            **INTEGRATED_REQUEST_ARGS,
        )
    )
    assert calls == list(StepName)
    assert outcome.status == OrchestrationStatus.PARTIAL
    assert outcome.steps[-1].status == OrchestrationStatus.FAILED


def test_resume_retries_only_incomplete_integrated_unit():
    calls = []
    attempts = 0

    def integrated(_context):
        nonlocal attempts
        attempts += 1
        return result("failed" if attempts == 1 else "succeeded")

    runner, _ = make_runner(
        calls=calls,
        executors={StepName.INTEGRATED_VEHICLE_COST: integrated},
    )
    request = OrchestrationRequest(
        scope=OrchestrationScope.INTEGRATED_VEHICLE_COST,
        idempotency_key="resume-integrated",
        **INTEGRATED_REQUEST_ARGS,
    )
    assert runner.run(request).status == OrchestrationStatus.FAILED
    resumed = runner.run(
        OrchestrationRequest(
            scope=OrchestrationScope.INTEGRATED_VEHICLE_COST,
            idempotency_key="resume-integrated",
            resume=True,
            **INTEGRATED_REQUEST_ARGS,
        )
    )
    assert resumed.status == OrchestrationStatus.SUCCEEDED
    assert calls == [
        StepName.INTEGRATED_VEHICLE_COST,
        StepName.INTEGRATED_VEHICLE_COST,
    ]


def test_integrated_retries_only_transient_exceptions():
    calls = []
    attempts = 0

    def transient(_context):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TransientStepError("temporary integrated source contention")
        return result("succeeded")

    runner, _ = make_runner(
        calls=calls,
        executors={StepName.INTEGRATED_VEHICLE_COST: transient},
    )
    outcome = runner.run(
        OrchestrationRequest(
            scope=OrchestrationScope.INTEGRATED_VEHICLE_COST,
            idempotency_key="integrated-transient-retry",
            **INTEGRATED_REQUEST_ARGS,
        )
    )
    assert outcome.status == OrchestrationStatus.SUCCEEDED
    assert calls == [
        StepName.INTEGRATED_VEHICLE_COST,
        StepName.INTEGRATED_VEHICLE_COST,
    ]


def test_complete_resume_reuses_sources_and_repeats_only_partial_integrated_unit():
    calls = []
    attempts = 0

    def integrated(_context):
        nonlocal attempts
        attempts += 1
        return result("partial" if attempts == 1 else "succeeded")

    runner, _ = make_runner(
        calls=calls,
        executors={StepName.INTEGRATED_VEHICLE_COST: integrated},
    )
    request = OrchestrationRequest(
        scope=OrchestrationScope.COMPLETE,
        idempotency_key="complete-resume-integrated",
        **INTEGRATED_REQUEST_ARGS,
    )
    assert runner.run(request).status == OrchestrationStatus.PARTIAL
    resumed = runner.run(
        OrchestrationRequest(
            scope=OrchestrationScope.COMPLETE,
            idempotency_key="complete-resume-integrated",
            resume=True,
            **INTEGRATED_REQUEST_ARGS,
        )
    )
    assert resumed.status == OrchestrationStatus.SUCCEEDED
    assert calls[:-1] == list(StepName)
    assert calls[-1] == StepName.INTEGRATED_VEHICLE_COST


def test_integrated_lock_is_independent_and_dry_run_is_pure():
    repository = InMemoryOrchestrationRepository()
    calls = []
    runner, _ = make_runner(repository=repository, calls=calls)
    with repository.acquire_lock("sigra-orchestration:fipe") as fipe_lock:
        assert fipe_lock.acquired is True
        live = runner.run(
            OrchestrationRequest(
                scope=OrchestrationScope.INTEGRATED_VEHICLE_COST,
                idempotency_key="integrated-independent-lock",
                **INTEGRATED_REQUEST_ARGS,
            )
        )
    assert live.status == OrchestrationStatus.SUCCEEDED
    calls.clear()
    request = OrchestrationRequest(
        scope=OrchestrationScope.INTEGRATED_VEHICLE_COST,
        dry_run=True,
        idempotency_key="integrated-dry-run",
    )
    outcome = runner.run(request)
    assert outcome.dry_run is True
    assert calls == []
    assert repository.get_run_by_key(
        request.resolved_idempotency_key(),
        flow_name=request.flow_name,
    ) is None


def test_resume_anp_retries_only_the_incomplete_pipeline_unit():
    calls = []
    attempts = 0

    def anp(_context):
        nonlocal attempts
        attempts += 1
        return result("failed") if attempts == 1 else result()

    runner, _ = make_runner(
        calls=calls,
        executors={StepName.ANP: anp},
        policy=ExecutionPolicy(max_attempts=1, backoff_seconds=0),
    )
    request = OrchestrationRequest(
        scope=OrchestrationScope.ANP,
        idempotency_key="resume-anp",
    )
    first = runner.run(request)
    resumed = runner.run(
        OrchestrationRequest(
            scope=OrchestrationScope.ANP,
            idempotency_key="resume-anp",
            resume=True,
        )
    )
    assert first.status == OrchestrationStatus.FAILED
    assert resumed.status == OrchestrationStatus.SUCCEEDED
    assert calls == [StepName.ANP, StepName.ANP]


def test_anp_transient_failure_retries_but_permanent_failure_does_not():
    transient_calls = 0

    def transient(_context):
        nonlocal transient_calls
        transient_calls += 1
        if transient_calls == 1:
            raise TransientStepError("temporary ANP transport error")
        return result()

    transient_runner, _ = make_runner(
        executors={StepName.ANP: transient},
    )
    transient_outcome = transient_runner.run(
        OrchestrationRequest(
            scope=OrchestrationScope.ANP,
            idempotency_key="anp-transient",
        )
    )
    assert transient_outcome.status == OrchestrationStatus.SUCCEEDED
    assert transient_calls == 2

    permanent_calls = 0

    def permanent(_context):
        nonlocal permanent_calls
        permanent_calls += 1
        raise PermanentStepError("invalid ANP contract")

    permanent_runner, _ = make_runner(
        executors={StepName.ANP: permanent},
    )
    permanent_outcome = permanent_runner.run(
        OrchestrationRequest(
            scope=OrchestrationScope.ANP,
            idempotency_key="anp-permanent",
        )
    )
    assert permanent_outcome.status == OrchestrationStatus.FAILED
    assert permanent_calls == 1


def test_anp_and_pbev_orchestration_locks_are_isolated():
    repository = InMemoryOrchestrationRepository()
    pbev_runner, _ = make_runner(repository=repository)
    anp_runner, _ = make_runner(repository=repository)
    with repository.acquire_lock("sigra-orchestration:anp") as lock:
        assert lock.acquired is True
        pbev = pbev_runner.run(
            OrchestrationRequest(
                scope=OrchestrationScope.PBEV,
                idempotency_key="isolated-pbev",
            )
        )
        assert pbev.status == OrchestrationStatus.SUCCEEDED
        with pytest.raises(ConcurrentOrchestrationError):
            anp_runner.run(
                OrchestrationRequest(
                    scope=OrchestrationScope.ANP,
                    idempotency_key="blocked-anp",
                )
            )


def test_anp_dry_run_does_not_acquire_lock_or_execute_pipeline():
    calls = []

    class NoLockRepository(InMemoryOrchestrationRepository):
        def acquire_lock(self, _lock_name):
            raise AssertionError("dry-run must not acquire an orchestration lock")

    runner, repository = make_runner(
        repository=NoLockRepository(),
        calls=calls,
    )
    outcome = runner.run(
        OrchestrationRequest(
            scope=OrchestrationScope.ANP,
            dry_run=True,
            idempotency_key="anp-dry-run",
        )
    )
    assert outcome.status == OrchestrationStatus.SUCCEEDED
    assert outcome.dry_run is True
    assert calls == []
    assert repository._runs == {}
    assert outcome.steps[0].metrics == {
        "planned": True,
        "publication_mode": "shadow",
    }


def test_anp_timeout_is_persisted_without_retry_when_attempt_limit_is_one():
    calls = []

    def timeout(context):
        time.sleep(0.01)
        context.checkpoint()

    runner, _ = make_runner(
        calls=calls,
        executors={StepName.ANP: timeout},
        policy=ExecutionPolicy(
            max_attempts=1,
            backoff_seconds=0,
            timeout_seconds={StepName.ANP: 0.001},
        ),
    )
    outcome = runner.run(
        OrchestrationRequest(
            scope=OrchestrationScope.ANP,
            idempotency_key="anp-timeout",
        )
    )
    assert outcome.status == OrchestrationStatus.FAILED
    assert calls == [StepName.ANP]
    assert "timed out" in (outcome.steps[0].error or "")


def test_anp_checkpoint_updates_heartbeat_and_observes_cancellation():
    class HeartbeatRepository(InMemoryOrchestrationRepository):
        def __init__(self):
            super().__init__()
            self.heartbeat_calls = 0

        def heartbeat(self, run_id, now):
            self.heartbeat_calls += 1
            super().heartbeat(run_id, now)

    repository = HeartbeatRepository()

    def checkpoints(context):
        context.checkpoint()
        context.checkpoint()
        return result()

    runner, _ = make_runner(
        repository=repository,
        executors={StepName.ANP: checkpoints},
    )
    succeeded = runner.run(
        OrchestrationRequest(
            scope=OrchestrationScope.ANP,
            idempotency_key="anp-heartbeat",
        )
    )
    assert succeeded.status == OrchestrationStatus.SUCCEEDED
    assert repository.heartbeat_calls >= 3

    token = CancellationToken()

    def cancel(context):
        token.cancel()
        context.checkpoint()

    cancelled_runner, _ = make_runner(executors={StepName.ANP: cancel})
    cancelled = cancelled_runner.run(
        OrchestrationRequest(
            scope=OrchestrationScope.ANP,
            idempotency_key="anp-cancelled",
        ),
        cancellation_token=token,
    )
    assert cancelled.status == OrchestrationStatus.CANCELLED
    assert cancelled.steps[0].status == OrchestrationStatus.CANCELLED


def test_prefect_adapter_dispatches_anp_without_replicating_runner_logic(monkeypatch):
    def decorator(**_options):
        return lambda function: function

    fake_prefect = SimpleNamespace(task=decorator, flow=decorator)
    monkeypatch.setattr(importlib, "import_module", lambda _name: fake_prefect)
    calls = []
    runner, _ = make_runner(calls=calls)
    outcome = build_prefect_components(runner).flow(
        OrchestrationRequest(
            scope=OrchestrationScope.ANP,
            idempotency_key="prefect-anp",
        )
    )
    assert outcome.status == OrchestrationStatus.SUCCEEDED
    assert calls == [StepName.ANP]


def test_cli_keeps_legacy_fipe_default_and_exposes_explicit_scopes():
    parser = build_parser()
    legacy = parser.parse_args(["run", "--dry-run"])
    anp = parser.parse_args(["run", "--scope", "anp", "--dry-run"])
    complete = parser.parse_args(
        ["run", "--scope", "complete", "--from-step", "silver", "--dry-run"]
    )
    integrated = parser.parse_args(
        [
            "run",
            "--scope",
            "integrated_vehicle_cost",
            "--integrated-geography-level",
            "state",
            "--integrated-geography-key",
            "SP",
            "--integrated-week-start",
            "2026-08-03",
            "--dry-run",
        ]
    )
    assert legacy.scope == "fipe"
    assert legacy.from_step == "bronze"
    assert anp.scope == "anp"
    assert complete.scope == "complete"
    assert complete.from_step == "silver"
    assert integrated.scope == "integrated_vehicle_cost"
    assert str(integrated.integrated_week_start) == "2026-08-03"


def test_prefect_weekly_anp_schedule_is_configurable_without_real_deploy(monkeypatch):
    served = {}

    class FakeFlow:
        def __init__(self, function):
            self.function = function

        def __call__(self, *args, **kwargs):
            return self.function(*args, **kwargs)

        def serve(self, **kwargs):
            served.update(kwargs)
            return "configured"

    def flow_decorator(**_options):
        return lambda function: FakeFlow(function)

    fake_prefect = SimpleNamespace(
        task=lambda **_options: lambda function: function,
        flow=flow_decorator,
    )
    fake_schedules = SimpleNamespace(
        Cron=lambda cron, timezone: {"cron": cron, "timezone": timezone}
    )
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: fake_schedules if name == "prefect.schedules" else fake_prefect,
    )
    runner, _ = make_runner()
    configured = serve_prefect_flow(
        runner,
        PrefectScheduleConfig(
            "0 3 * * 1",
            timezone="America/Sao_Paulo",
            deployment_name="sigra-anp-weekly",
        ),
        OrchestrationRequest(
            scope=OrchestrationScope.ANP,
            trigger_type=TriggerType.SCHEDULED,
        ),
    )
    assert configured == "configured"
    assert served["name"] == "sigra-anp-weekly"
    assert served["schedule"] == {
        "cron": "0 3 * * 1",
        "timezone": "America/Sao_Paulo",
    }
    assert served["parameters"]["request"].scope == OrchestrationScope.ANP


def test_scope_metadata_redacts_credentials_and_does_not_persist_asset_path():
    runner, repository = make_runner()
    outcome = runner.run(
        OrchestrationRequest(
            scope=OrchestrationScope.ANP,
            idempotency_key="safe-anp-metadata",
            pbev_asset_directory=r"C:\\private\\operator\\pbev",
            parameters={
                "password": "never-store",
                "url": "sensitive-test-marker",
            },
        )
    )
    stored = repository.get_run(UUID(outcome.orchestration_run_id))
    serialized = repr(stored)
    assert stored.flow_name == "sigra_anp_fuel_prices_shadow"
    assert stored.parameters["scope"] == "anp"
    assert stored.parameters["pbev_asset_configured"] is True
    assert "never-store" not in serialized
    assert "private" not in serialized


def test_orchestration_source_integrates_pbev_and_anp_without_subprocesses():
    source = inspect.getsource(build_default_bindings)
    assert "run_pbev_pipeline(" in source
    assert "run_anp_pipeline(" in source
    assert "import subprocess" not in source
    assert "subprocess." not in source
