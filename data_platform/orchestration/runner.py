from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime
from decimal import Decimal
import time
from typing import Any, Callable, Mapping, Sequence
from uuid import UUID, uuid4

from data_platform.common.config import DataPlatformSettings
from data_platform.common.database import create_platform_engine
from data_platform.common.logging import sanitize
from data_platform.contracts.fipe import FipeTarget
from data_platform.ingestion.fipe.client import FipeHttpClient
from data_platform.ingestion.fipe.loader import BronzeLoader
from data_platform.ingestion.fipe.pipeline import run_pipeline
from data_platform.ingestion.fipe.targets import legacy_car_targets
from data_platform.orchestration.contracts import (
    FLOW_NAME,
    STEP_ORDER,
    TERMINAL_STATUSES,
    CancellationToken,
    ConcurrentOrchestrationError,
    OrchestrationCancelled,
    OrchestrationRequest,
    OrchestrationResult,
    OrchestrationStatus,
    PartialPolicy,
    PipelineBindings,
    StepDispatcher,
    StepExecutionContext,
    StepName,
    StepResult,
    StoredRun,
    StoredStepRun,
    sanitize_mapping,
    utc_now,
)
from data_platform.orchestration.policies import ExecutionPolicy, is_transient_error
from data_platform.orchestration.repository import (
    OrchestrationRepository,
    latest_step_attempts,
)
from data_platform.publication.loader import GoldLoader
from data_platform.publication.pipeline import run_gold_publication
from data_platform.transformation.loader import SilverLoader
from data_platform.transformation.pipeline import run_silver_pipeline


_METRIC_FIELDS = frozenset(
    {
        "dataset_version",
        "records_received",
        "records_validated",
        "records_inserted",
        "records_deduplicated",
        "records_rejected",
        "issues_inserted",
        "issues_recorded",
        "expected_count",
        "published_count",
        "blocked_count",
        "coverage_percentage",
        "fingerprint",
        "freshness_status",
    }
)


def _direct_dispatch(
    _step_name: StepName,
    executor: Callable[[StepExecutionContext], Any],
    context: StepExecutionContext,
) -> Any:
    return executor(context)


def _safe_metric(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    return sanitize(value, limit=160)


def _result_metrics(result: Any) -> dict[str, Any]:
    if is_dataclass(result):
        names = {item.name for item in fields(result)}
        raw = {name: getattr(result, name) for name in names if name in _METRIC_FIELDS}
    elif isinstance(result, Mapping):
        raw = {key: result[key] for key in result if key in _METRIC_FIELDS}
    else:
        raw = {}
    return {str(key): _safe_metric(value) for key, value in raw.items()}


def _result_error(result: Any) -> str | None:
    errors = getattr(result, "errors", ())
    if not errors and isinstance(result, Mapping):
        errors = result.get("errors", ())
    if isinstance(errors, str):
        errors = (errors,)
    safe = [sanitize(item) for item in errors or ()]
    return "; ".join(safe) or None


def _pipeline_run_uuid(result: Any) -> UUID | None:
    raw = getattr(result, "pipeline_run_id", None)
    if raw is None and isinstance(result, Mapping):
        raw = result.get("pipeline_run_id")
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except ValueError:
        return None


def _normalize_pipeline_result(
    step_name: StepName,
    attempt_number: int,
    result: Any,
    duration_seconds: float,
) -> StepResult:
    raw_status = getattr(result, "status", None)
    if raw_status is None and isinstance(result, Mapping):
        raw_status = result.get("status")
    status_value = str(raw_status or "failed").casefold()
    status = {
        "succeeded": OrchestrationStatus.SUCCEEDED,
        "deduplicated": OrchestrationStatus.SUCCEEDED,
        "partial": OrchestrationStatus.PARTIAL,
        "failed": OrchestrationStatus.FAILED,
        "rejected": OrchestrationStatus.FAILED,
        "skipped": OrchestrationStatus.SKIPPED,
        "cancelled": OrchestrationStatus.CANCELLED,
    }.get(status_value, OrchestrationStatus.FAILED)
    pipeline_run_id = _pipeline_run_uuid(result)
    return StepResult(
        step_name=step_name,
        status=status,
        attempt_number=attempt_number,
        pipeline_run_id=str(pipeline_run_id) if pipeline_run_id else None,
        metrics={**_result_metrics(result), "duration_seconds": duration_seconds},
        error=(
            _result_error(result)
            or (f"unexpected pipeline status: {sanitize(raw_status)}" if status_value not in {
                "succeeded", "deduplicated", "partial", "failed", "rejected", "skipped", "cancelled"
            } else None)
        ),
        duration_seconds=duration_seconds,
    )


def _stored_step_result(step: StoredStepRun) -> StepResult:
    duration = (
        max(0.0, (step.finished_at - step.started_at).total_seconds())
        if step.finished_at is not None
        else 0.0
    )
    return StepResult(
        step_name=step.step_name,
        status=step.status,
        attempt_number=step.attempt_number,
        pipeline_run_id=str(step.pipeline_run_id) if step.pipeline_run_id else None,
        metrics=dict(step.metrics_summary),
        error=step.error_summary,
        skip_reason=(
            str(step.metrics_summary.get("skip_reason"))
            if step.metrics_summary.get("skip_reason")
            else None
        ),
        duration_seconds=duration,
    )


def _result_from_repository(
    run: StoredRun,
    attempts: tuple[StoredStepRun, ...],
    *,
    reused: bool,
) -> OrchestrationResult:
    latest = latest_step_attempts(attempts)
    steps = tuple(_stored_step_result(latest[name]) for name in STEP_ORDER if name in latest)
    finished = run.finished_at or run.heartbeat_at
    return OrchestrationResult(
        orchestration_run_id=str(run.orchestration_run_id),
        status=run.status,
        steps=steps,
        started_at=run.started_at,
        finished_at=finished,
        idempotency_key=run.idempotency_key,
        reused=reused,
        error=run.error_summary,
    )


class OrchestrationRunner:
    def __init__(
        self,
        repository: OrchestrationRepository,
        bindings: PipelineBindings,
        *,
        policy: ExecutionPolicy | None = None,
        now: Callable[[], datetime] = utc_now,
        monotonic: Callable[[], float] = time.perf_counter,
        new_run_id: Callable[[], UUID] = uuid4,
    ):
        self.repository = repository
        self.bindings = bindings
        self.policy = policy or ExecutionPolicy()
        self._now = now
        self._monotonic = monotonic
        self._new_run_id = new_run_id

    def run(
        self,
        request: OrchestrationRequest | None = None,
        *,
        cancellation_token: CancellationToken | None = None,
        dispatcher: StepDispatcher | None = None,
    ) -> OrchestrationResult:
        request = request or OrchestrationRequest()
        token = cancellation_token or CancellationToken()
        dispatch = dispatcher or _direct_dispatch
        idempotency_key = request.resolved_idempotency_key()
        if request.dry_run:
            return self._dry_run(request, idempotency_key)

        with self.repository.acquire_lock(f"{FLOW_NAME}:exclusive") as run_lock:
            if not run_lock.acquired:
                raise ConcurrentOrchestrationError(
                    "an incompatible orchestration run is already active"
                )
            return self._run_locked(request, token, dispatch, idempotency_key)

    def _dry_run(
        self,
        request: OrchestrationRequest,
        idempotency_key: str,
    ) -> OrchestrationResult:
        now = self._now()
        start_index = STEP_ORDER.index(request.start_at)
        steps = tuple(
            StepResult(
                step_name=step,
                status=OrchestrationStatus.SKIPPED,
                attempt_number=0,
                metrics={"planned": index >= start_index},
                skip_reason=(
                    f"start_from_{request.start_at.value}"
                    if index < start_index
                    else "dry_run"
                ),
            )
            for index, step in enumerate(STEP_ORDER)
        )
        return OrchestrationResult(
            orchestration_run_id=str(self._new_run_id()),
            status=OrchestrationStatus.SUCCEEDED,
            steps=steps,
            started_at=now,
            finished_at=now,
            idempotency_key=idempotency_key,
            dry_run=True,
        )

    def _run_locked(
        self,
        request: OrchestrationRequest,
        token: CancellationToken,
        dispatch: StepDispatcher,
        idempotency_key: str,
    ) -> OrchestrationResult:
        now = self._now()
        active = self.repository.get_active_run()
        if active is not None and active.idempotency_key != idempotency_key:
            if now - active.heartbeat_at < self.policy.stale_after:
                raise ConcurrentOrchestrationError(
                    "another orchestration run is still active"
                )
            self._cancel_stale_attempts(active, now)
            self.repository.finish_run(
                active.orchestration_run_id,
                OrchestrationStatus.CANCELLED,
                now,
                "stale orchestration run superseded",
            )
        run = self.repository.get_run_by_key(idempotency_key)
        if run is not None:
            if run.status in TERMINAL_STATUSES and not request.resume:
                return _result_from_repository(
                    run,
                    self.repository.list_step_attempts(run.orchestration_run_id),
                    reused=True,
                )
            is_stale = now - run.heartbeat_at >= self.policy.stale_after
            if run.status == OrchestrationStatus.RUNNING and not is_stale:
                raise ConcurrentOrchestrationError(
                    "the idempotent orchestration run is still active"
                )
            if run.status == OrchestrationStatus.RUNNING and is_stale:
                self._cancel_stale_attempts(run, now)
            run = self.repository.reopen_run(run.orchestration_run_id, now)
        else:
            run = self.repository.create_run(
                self._new_run_id(),
                request,
                idempotency_key,
                now,
            )

        try:
            self._execute_steps(run, request, token, dispatch)
        except OrchestrationCancelled as exc:
            self.repository.finish_run(
                run.orchestration_run_id,
                OrchestrationStatus.CANCELLED,
                self._now(),
                sanitize(exc),
            )
        except KeyboardInterrupt:
            self.repository.finish_run(
                run.orchestration_run_id,
                OrchestrationStatus.CANCELLED,
                self._now(),
                "orchestration interrupted",
            )
        except Exception as exc:
            self.repository.finish_run(
                run.orchestration_run_id,
                OrchestrationStatus.FAILED,
                self._now(),
                sanitize(exc),
            )

        refreshed = self.repository.get_run(run.orchestration_run_id)
        assert refreshed is not None
        return _result_from_repository(
            refreshed,
            self.repository.list_step_attempts(run.orchestration_run_id),
            reused=False,
        )

    def _cancel_stale_attempts(self, run: StoredRun, now: datetime) -> None:
        for attempt in self.repository.list_step_attempts(
            run.orchestration_run_id
        ):
            if attempt.status == OrchestrationStatus.RUNNING:
                self.repository.finish_step_attempt(
                    attempt.orchestration_step_run_id,
                    OrchestrationStatus.CANCELLED,
                    now,
                    error="stale running attempt recovered",
                )

    def _execute_steps(
        self,
        run: StoredRun,
        request: OrchestrationRequest,
        token: CancellationToken,
        dispatch: StepDispatcher,
    ) -> None:
        run_id = run.orchestration_run_id
        attempts = self.repository.list_step_attempts(run_id)
        latest = latest_step_attempts(attempts)
        start_index = STEP_ORDER.index(request.start_at)
        dependency: StoredStepRun | None = None
        step_results: dict[StepName, StepResult] = {}

        for index, step_name in enumerate(STEP_ORDER):
            token.raise_if_cancelled()
            previous = latest.get(step_name)
            if index < start_index:
                if previous is None:
                    previous = self._record_skip(
                        run_id,
                        step_name,
                        dependency,
                        f"start_from_{request.start_at.value}",
                        1,
                    )
                dependency = previous
                step_results[step_name] = _stored_step_result(previous)
                continue

            if previous is not None and previous.status in {
                OrchestrationStatus.SUCCEEDED,
                OrchestrationStatus.PARTIAL,
            }:
                dependency = previous
                step_results[step_name] = _stored_step_result(previous)
                continue

            dependency_result = step_results.get(STEP_ORDER[index - 1]) if index else None
            dependency_block = self._dependency_block_reason(
                dependency_result,
                request,
                index,
            )
            if dependency_block:
                attempt_number = (
                    max(
                        (item.attempt_number for item in attempts if item.step_name == step_name),
                        default=0,
                    )
                    + 1
                )
                previous = self._record_skip(
                    run_id,
                    step_name,
                    dependency,
                    dependency_block,
                    attempt_number,
                )
                dependency = previous
                step_results[step_name] = _stored_step_result(previous)
                continue

            existing_attempts = [item for item in attempts if item.step_name == step_name]
            initial_attempt = max(
                (item.attempt_number for item in existing_attempts),
                default=0,
            )
            result, completed = self._execute_step_with_retries(
                run_id,
                step_name,
                dependency,
                request,
                token,
                dispatch,
                initial_attempt,
            )
            dependency = completed
            step_results[step_name] = result
            self.repository.heartbeat(run_id, self._now())

        final_status = self._final_status(step_results, request)
        error = "; ".join(
            result.error for result in step_results.values() if result.error
        ) or None
        self.repository.finish_run(run_id, final_status, self._now(), error)

    def _dependency_block_reason(
        self,
        dependency: StepResult | None,
        request: OrchestrationRequest,
        index: int,
    ) -> str | None:
        if dependency is None:
            return None
        if dependency.skip_reason and dependency.skip_reason.startswith("start_from_"):
            return None
        if dependency.status in {
            OrchestrationStatus.FAILED,
            OrchestrationStatus.CANCELLED,
            OrchestrationStatus.SKIPPED,
        }:
            return f"dependency_{dependency.step_name.value}_{dependency.status.value}"
        if dependency.status == OrchestrationStatus.PARTIAL:
            if self.policy.partial_policy == PartialPolicy.CONTINUE:
                return None
            return f"dependency_{dependency.step_name.value}_partial"
        return None

    def _execute_step_with_retries(
        self,
        run_id: UUID,
        step_name: StepName,
        dependency: StoredStepRun | None,
        request: OrchestrationRequest,
        token: CancellationToken,
        dispatch: StepDispatcher,
        initial_attempt: int,
    ) -> tuple[StepResult, StoredStepRun]:
        last_result: StepResult | None = None
        last_step: StoredStepRun | None = None
        for offset in range(1, self.policy.max_attempts + 1):
            token.raise_if_cancelled()
            attempt_number = initial_attempt + offset
            started_at = self._now()
            step_run = self.repository.create_step_attempt(
                run_id,
                step_name,
                attempt_number,
                dependency.orchestration_step_run_id if dependency else None,
                started_at,
            )
            started_monotonic = self._monotonic()
            timeout = self.policy.timeout_for(step_name)
            context = StepExecutionContext(
                request=request,
                step_name=step_name,
                attempt_number=attempt_number,
                cancellation_token=token,
                deadline_monotonic=(
                    started_monotonic + timeout if timeout is not None else None
                ),
            )
            try:
                context.checkpoint()
                raw_result = dispatch(
                    step_name,
                    self.bindings.for_step(step_name),
                    context,
                )
                duration = max(0.0, self._monotonic() - started_monotonic)
                result = _normalize_pipeline_result(
                    step_name,
                    attempt_number,
                    raw_result,
                    duration,
                )
                completed = self.repository.finish_step_attempt(
                    step_run.orchestration_step_run_id,
                    result.status,
                    self._now(),
                    pipeline_run_id=(
                        UUID(result.pipeline_run_id) if result.pipeline_run_id else None
                    ),
                    metrics=result.metrics,
                    error=result.error,
                )
                return result, completed
            except OrchestrationCancelled:
                completed = self.repository.finish_step_attempt(
                    step_run.orchestration_step_run_id,
                    OrchestrationStatus.CANCELLED,
                    self._now(),
                    error="orchestration cancelled",
                )
                raise
            except KeyboardInterrupt:
                self.repository.finish_step_attempt(
                    step_run.orchestration_step_run_id,
                    OrchestrationStatus.CANCELLED,
                    self._now(),
                    error="orchestration interrupted",
                )
                raise OrchestrationCancelled("orchestration interrupted") from None
            except Exception as exc:
                duration = max(0.0, self._monotonic() - started_monotonic)
                safe_error = sanitize(exc)
                completed = self.repository.finish_step_attempt(
                    step_run.orchestration_step_run_id,
                    OrchestrationStatus.FAILED,
                    self._now(),
                    metrics={"duration_seconds": duration},
                    error=safe_error,
                )
                last_step = completed
                last_result = _stored_step_result(completed)
                if not is_transient_error(exc) or offset >= self.policy.max_attempts:
                    return last_result, completed
                self.policy.sleep(self.policy.backoff_for_attempt(offset))
        assert last_result is not None and last_step is not None
        return last_result, last_step

    def _record_skip(
        self,
        run_id: UUID,
        step_name: StepName,
        dependency: StoredStepRun | None,
        reason: str,
        attempt_number: int,
    ) -> StoredStepRun:
        now = self._now()
        step = self.repository.create_step_attempt(
            run_id,
            step_name,
            attempt_number,
            dependency.orchestration_step_run_id if dependency else None,
            now,
        )
        return self.repository.finish_step_attempt(
            step.orchestration_step_run_id,
            OrchestrationStatus.SKIPPED,
            self._now(),
            metrics={"skip_reason": reason},
            error=reason,
        )

    def _final_status(
        self,
        results: Mapping[StepName, StepResult],
        request: OrchestrationRequest,
    ) -> OrchestrationStatus:
        considered = [
            result
            for step_name, result in results.items()
            if STEP_ORDER.index(step_name) >= STEP_ORDER.index(request.start_at)
        ]
        if any(item.status == OrchestrationStatus.CANCELLED for item in considered):
            return OrchestrationStatus.CANCELLED
        if any(item.status == OrchestrationStatus.FAILED for item in considered):
            return OrchestrationStatus.FAILED
        if (
            self.policy.partial_policy == PartialPolicy.FAIL
            and any(item.status == OrchestrationStatus.PARTIAL for item in considered)
        ):
            return OrchestrationStatus.FAILED
        if any(
            item.status in {OrchestrationStatus.PARTIAL, OrchestrationStatus.SKIPPED}
            for item in considered
        ):
            return OrchestrationStatus.PARTIAL
        return OrchestrationStatus.SUCCEEDED


def build_default_bindings(
    settings: DataPlatformSettings,
    *,
    targets: Sequence[FipeTarget] | None = None,
) -> PipelineBindings:
    """Liga o runner diretamente aos pipelines existentes, sem subprocessos."""

    def bronze(context: StepExecutionContext):
        context.checkpoint()
        resolved_targets = list(targets) if targets is not None else legacy_car_targets()
        if not resolved_targets:
            raise ValueError("no FIPE targets were configured")
        engine = create_platform_engine(settings.database_url)
        try:
            with FipeHttpClient(
                settings.fipe_api_url,
                settings.timeout_seconds,
            ) as client:
                return run_pipeline(
                    resolved_targets,
                    client,
                    BronzeLoader(engine),
                    trigger_type=(
                        "retry"
                        if context.attempt_number > 1
                        else context.request.trigger_type.value
                    ),
                    source_reference=context.request.source_reference,
                    git_commit=context.request.git_commit,
                )
        finally:
            engine.dispose()

    def silver(context: StepExecutionContext):
        context.checkpoint()
        engine = create_platform_engine(settings.database_url)
        try:
            return run_silver_pipeline(
                SilverLoader(engine),
                trigger_type=(
                    "retry"
                    if context.attempt_number > 1
                    else context.request.trigger_type.value
                ),
                source_reference=context.request.source_reference,
                git_commit=context.request.git_commit,
            )
        finally:
            engine.dispose()

    def gold(context: StepExecutionContext):
        context.checkpoint()
        engine = create_platform_engine(settings.database_url)
        try:
            return run_gold_publication(
                GoldLoader(engine),
                trigger_type=(
                    "retry"
                    if context.attempt_number > 1
                    else context.request.trigger_type.value
                ),
                source_reference=context.request.source_reference,
                git_commit=context.request.git_commit,
            )
        finally:
            engine.dispose()

    return PipelineBindings(bronze=bronze, silver=silver, gold=gold)
