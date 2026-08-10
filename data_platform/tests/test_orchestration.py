from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import importlib
import inspect
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from data_platform.orchestration.contracts import (
    FLOW_NAME,
    CancellationToken,
    ConcurrentOrchestrationError,
    OrchestrationRequest,
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
    secret = "never-store-this"

    def unsafe(_context):
        raise PermanentStepError(
            f"password={secret} postgresql://alice:{secret}@localhost/db_test"
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
