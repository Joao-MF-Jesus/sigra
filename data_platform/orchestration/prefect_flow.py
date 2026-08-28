from __future__ import annotations

from dataclasses import dataclass, replace
import importlib
from typing import Any, Callable, Mapping

from data_platform.orchestration.contracts import (
    OrchestrationCancelled,
    OrchestrationRequest,
    OrchestrationResult,
    StepExecutionContext,
    StepName,
    StepTimeoutError,
    TriggerType,
)
from data_platform.orchestration.policies import ExecutionPolicy
from data_platform.orchestration.runner import OrchestrationRunner


class PrefectUnavailableError(RuntimeError):
    """Prefect e opcional e nao esta disponivel neste ambiente."""


@dataclass(frozen=True)
class PrefectComponents:
    flow: Callable[..., OrchestrationResult]
    tasks: Mapping[StepName, Callable[..., Any]]


@dataclass(frozen=True)
class PrefectScheduleConfig:
    cron: str
    timezone: str = "America/Sao_Paulo"
    deployment_name: str = "sigra-fipe-medallion"

    def __post_init__(self) -> None:
        if not self.cron.strip():
            raise ValueError("Prefect cron cannot be empty")
        if not self.timezone.strip():
            raise ValueError("Prefect timezone cannot be empty")
        if not self.deployment_name.strip():
            raise ValueError("Prefect deployment name cannot be empty")


def _prefect_module():
    try:
        return importlib.import_module("prefect")
    except ImportError:
        raise PrefectUnavailableError(
            "Prefect is not installed; install the optional orchestration dependency"
        ) from None


def prefect_available() -> bool:
    try:
        _prefect_module()
    except PrefectUnavailableError:
        return False
    return True


def build_prefect_components(
    runner: OrchestrationRunner,
    *,
    policy: ExecutionPolicy | None = None,
) -> PrefectComponents:
    """Cria flow/tasks locais sem importar Prefect no nucleo da orquestracao."""
    prefect = _prefect_module()
    resolved_policy = policy or runner.policy

    def task_for(step_name: StepName):
        timeout = resolved_policy.timeout_for(step_name)

        @prefect.task(
            name=f"SIGRA {step_name.value.title()}",
            retries=0,
            timeout_seconds=timeout,
            persist_result=False,
        )
        def execute(executor, context: StepExecutionContext):
            return executor(context)

        return execute

    tasks = {step_name: task_for(step_name) for step_name in StepName}

    def dispatch(step_name, executor, context):
        try:
            return tasks[step_name](executor, context)
        except Exception as exc:
            if "cancel" in type(exc).__name__.casefold():
                raise OrchestrationCancelled(
                    f"{step_name.value} Prefect task was cancelled"
                ) from None
            if "timeout" in type(exc).__name__.casefold():
                raise StepTimeoutError(f"{step_name.value} Prefect task timed out") from None
            raise

    def runtime_request(request: OrchestrationRequest) -> OrchestrationRequest:
        if request.trigger_type != TriggerType.SCHEDULED or request.idempotency_key:
            return request
        runtime = getattr(prefect, "runtime", None)
        flow_run = getattr(runtime, "flow_run", None)
        flow_run_id = getattr(flow_run, "id", None)
        if flow_run_id:
            return replace(
                request,
                idempotency_key=f"prefect-flow-run:{flow_run_id}",
            )
        return request

    @prefect.flow(name="SIGRA Medallion Pipelines", log_prints=False)
    def orchestration_flow(request: OrchestrationRequest | None = None):
        resolved = runtime_request(request or OrchestrationRequest())
        return runner.run(resolved, dispatcher=dispatch)

    return PrefectComponents(flow=orchestration_flow, tasks=tasks)


def run_prefect_flow(
    runner: OrchestrationRunner,
    request: OrchestrationRequest | None = None,
) -> OrchestrationResult:
    return build_prefect_components(runner).flow(request or OrchestrationRequest())


def serve_prefect_flow(
    runner: OrchestrationRunner,
    schedule: PrefectScheduleConfig,
    request: OrchestrationRequest | None = None,
) -> Any:
    """Inicia um deployment local somente quando solicitado pelo operador."""
    components = build_prefect_components(runner)
    try:
        schedules = importlib.import_module("prefect.schedules")
        cron_schedule = schedules.Cron(
            schedule.cron,
            timezone=schedule.timezone,
        )
    except (ImportError, AttributeError, TypeError) as exc:
        raise PrefectUnavailableError(
            "Installed Prefect does not expose the required Cron schedule API"
        ) from None
    serve = getattr(components.flow, "serve", None)
    if not callable(serve):
        raise PrefectUnavailableError(
            "Installed Prefect does not expose local flow.serve scheduling"
        )
    return serve(
        name=schedule.deployment_name,
        schedule=cron_schedule,
        parameters={"request": request or OrchestrationRequest()},
    )
