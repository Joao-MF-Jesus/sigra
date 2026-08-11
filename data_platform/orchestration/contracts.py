from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import json
import threading
import time
from typing import Any, Callable, Mapping, Protocol
from uuid import UUID

from data_platform.common.logging import sanitize


FLOW_NAME = "sigra_fipe_medallion"
FLOW_VERSION = "orchestration-v2"


class OrchestrationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class StepName(StrEnum):
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"
    PBEV = "pbev"
    ANP = "anp_fuel_prices"


class OrchestrationScope(StrEnum):
    FIPE = "fipe"
    PBEV = "pbev"
    ANP = "anp"
    COMPLETE = "complete"


class TriggerType(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    RETRY = "retry"
    BACKFILL = "backfill"


class PartialPolicy(StrEnum):
    CONTINUE = "continue"
    STOP = "stop"
    FAIL = "fail"


FIPE_STEP_ORDER = (StepName.BRONZE, StepName.SILVER, StepName.GOLD)
STEP_ORDER = (*FIPE_STEP_ORDER, StepName.PBEV, StepName.ANP)
FLOW_NAMES = {
    OrchestrationScope.FIPE: FLOW_NAME,
    OrchestrationScope.PBEV: "sigra_pbev_shadow",
    OrchestrationScope.ANP: "sigra_anp_fuel_prices_shadow",
    OrchestrationScope.COMPLETE: "sigra_medallion_complete",
}


def scope_for_flow_name(flow_name: str) -> OrchestrationScope:
    return next(
        (scope for scope, name in FLOW_NAMES.items() if name == flow_name),
        OrchestrationScope.FIPE,
    )


TERMINAL_STATUSES = frozenset(
    {
        OrchestrationStatus.SUCCEEDED,
        OrchestrationStatus.PARTIAL,
        OrchestrationStatus.FAILED,
        OrchestrationStatus.SKIPPED,
        OrchestrationStatus.CANCELLED,
    }
)


_SENSITIVE_KEYS = frozenset(
    {
        "payload",
        "body",
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "url",
        "database_url",
        "connection_url",
    }
)


def sanitize_mapping(
    values: Mapping[str, Any] | None,
    *,
    limit: int = 160,
) -> dict[str, Any]:
    """Mantem somente metadados pequenos e seguros para persistencia/logs."""
    def safe_value(value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, Mapping):
            return sanitize_mapping(value, limit=limit)
        if isinstance(value, (list, tuple)):
            return [safe_value(item) for item in value[:50]]
        return sanitize(value, limit=limit)

    safe: dict[str, Any] = {}
    for raw_key, value in (values or {}).items():
        key = str(raw_key)[:80]
        if key.casefold() in _SENSITIVE_KEYS:
            safe[key] = "***"
        else:
            safe[key] = safe_value(value)
    return safe


@dataclass(frozen=True)
class OrchestrationRequest:
    start_at: StepName = StepName.BRONZE
    dry_run: bool = False
    trigger_type: TriggerType = TriggerType.MANUAL
    source_reference: str | None = None
    git_commit: str | None = None
    idempotency_key: str | None = None
    resume: bool = False
    parameters: Mapping[str, Any] = field(default_factory=dict)
    scope: OrchestrationScope = OrchestrationScope.FIPE
    pbev_asset_directory: str | None = None
    anp_source_reference: str | None = None

    def __post_init__(self) -> None:
        if self.start_at not in FIPE_STEP_ORDER:
            raise ValueError("start_at is restricted to FIPE Bronze, Silver or Gold")

    @property
    def flow_name(self) -> str:
        return FLOW_NAMES[self.scope]

    @property
    def steps(self) -> tuple[StepName, ...]:
        if self.scope == OrchestrationScope.FIPE:
            return FIPE_STEP_ORDER
        if self.scope == OrchestrationScope.PBEV:
            return (StepName.PBEV,)
        if self.scope == OrchestrationScope.ANP:
            return (StepName.ANP,)
        return STEP_ORDER

    @property
    def first_step(self) -> StepName:
        return self.start_at if self.scope in {
            OrchestrationScope.FIPE,
            OrchestrationScope.COMPLETE,
        } else self.steps[0]

    @property
    def lock_names(self) -> tuple[str, ...]:
        resources = {
            OrchestrationScope.FIPE: ("fipe",),
            OrchestrationScope.PBEV: ("pbev",),
            OrchestrationScope.ANP: ("anp",),
            OrchestrationScope.COMPLETE: ("fipe", "pbev", "anp"),
        }[self.scope]
        return tuple(f"sigra-orchestration:{item}" for item in resources)

    @property
    def safe_parameters(self) -> dict[str, Any]:
        return sanitize_mapping(
            {
                **self.parameters,
                "scope": self.scope.value,
                "start_at": self.start_at.value,
                "dry_run": self.dry_run,
                "source_reference": self.source_reference,
                "anp_source_reference": self.anp_source_reference,
                "pbev_asset_configured": bool(self.pbev_asset_directory),
                "git_commit": self.git_commit,
            }
        )

    def resolved_idempotency_key(self) -> str:
        if self.idempotency_key:
            return hashlib.sha256(str(self.idempotency_key).encode("utf-8")).hexdigest()
        encoded = json.dumps(
            {
                "flow": self.flow_name,
                "version": FLOW_VERSION,
                "trigger": self.trigger_type.value,
                "parameters": self.safe_parameters,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class StoredRun:
    orchestration_run_id: UUID
    flow_name: str
    flow_version: str
    idempotency_key: str
    trigger_type: TriggerType
    start_step: StepName
    status: OrchestrationStatus
    started_at: datetime
    finished_at: datetime | None
    heartbeat_at: datetime
    parameters: Mapping[str, Any]
    error_summary: str | None = None


@dataclass(frozen=True)
class StoredStepRun:
    orchestration_step_run_id: int
    orchestration_run_id: UUID
    step_name: StepName
    attempt_number: int
    status: OrchestrationStatus
    pipeline_run_id: UUID | None
    depends_on_step_run_id: int | None
    started_at: datetime
    finished_at: datetime | None
    metrics_summary: Mapping[str, Any]
    error_summary: str | None = None


@dataclass(frozen=True)
class StepResult:
    step_name: StepName
    status: OrchestrationStatus
    attempt_number: int
    pipeline_run_id: str | None = None
    metrics: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    skip_reason: str | None = None
    duration_seconds: float = 0.0


@dataclass(frozen=True)
class OrchestrationResult:
    orchestration_run_id: str
    status: OrchestrationStatus
    steps: tuple[StepResult, ...]
    started_at: datetime
    finished_at: datetime
    idempotency_key: str
    dry_run: bool = False
    reused: bool = False
    error: str | None = None
    scope: OrchestrationScope = OrchestrationScope.FIPE

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, default=str)


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise OrchestrationCancelled("orchestration cancelled")


@dataclass(frozen=True)
class StepExecutionContext:
    request: OrchestrationRequest
    step_name: StepName
    attempt_number: int
    cancellation_token: CancellationToken
    deadline_monotonic: float | None
    heartbeat: Callable[[], None] | None = None

    @property
    def remaining_seconds(self) -> float | None:
        if self.deadline_monotonic is None:
            return None
        return max(0.0, self.deadline_monotonic - time.perf_counter())

    def checkpoint(self) -> None:
        self.cancellation_token.raise_if_cancelled()
        if self.deadline_monotonic is not None and time.perf_counter() >= self.deadline_monotonic:
            raise StepTimeoutError(f"{self.step_name.value} step timed out")
        if self.heartbeat is not None:
            self.heartbeat()


StepExecutor = Callable[[StepExecutionContext], Any]
StepDispatcher = Callable[[StepName, StepExecutor, StepExecutionContext], Any]


@dataclass(frozen=True)
class PipelineBindings:
    bronze: StepExecutor
    silver: StepExecutor
    gold: StepExecutor
    pbev: StepExecutor | None = None
    anp: StepExecutor | None = None

    def for_step(self, step_name: StepName) -> StepExecutor:
        executor = {
            StepName.BRONZE: self.bronze,
            StepName.SILVER: self.silver,
            StepName.GOLD: self.gold,
            StepName.PBEV: self.pbev,
            StepName.ANP: self.anp,
        }[step_name]
        if executor is None:
            raise PermanentStepError(
                f"no pipeline binding configured for {step_name.value}"
            )
        return executor


class OrchestrationError(RuntimeError):
    """Falha segura da camada de orquestracao."""


class ConcurrentOrchestrationError(OrchestrationError):
    """Um fluxo incompativel ja esta em execucao."""


class TransientStepError(OrchestrationError):
    """Falha que pode ser repetida conforme a politica configurada."""


class PermanentStepError(OrchestrationError):
    """Falha definitiva que nao deve ser repetida automaticamente."""


class StepTimeoutError(TransientStepError):
    """O prazo cooperativo da etapa expirou."""


class OrchestrationCancelled(OrchestrationError):
    """A execucao foi cancelada entre checkpoints seguros."""


class RunLock(Protocol):
    acquired: bool

    def __enter__(self) -> "RunLock": ...

    def __exit__(self, *_args: object) -> None: ...


def utc_now() -> datetime:
    return datetime.now(UTC)
