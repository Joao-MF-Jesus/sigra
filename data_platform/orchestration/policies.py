from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
import time
from typing import Callable, Mapping

from data_platform.orchestration.contracts import (
    PartialPolicy,
    PermanentStepError,
    StepName,
    StepTimeoutError,
    TransientStepError,
)


@dataclass(frozen=True)
class ExecutionPolicy:
    max_attempts: int = 2
    backoff_seconds: float = 1.0
    timeout_seconds: Mapping[StepName, float | None] = field(
        default_factory=lambda: {
            StepName.BRONZE: 300.0,
            StepName.SILVER: 300.0,
            StepName.GOLD: 300.0,
            StepName.PBEV: 1800.0,
            StepName.ANP: 600.0,
        }
    )
    partial_policy: PartialPolicy = PartialPolicy.CONTINUE
    stale_after: timedelta = timedelta(minutes=30)
    sleep: Callable[[float], None] = time.sleep

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.backoff_seconds < 0:
            raise ValueError("backoff_seconds cannot be negative")
        if self.stale_after.total_seconds() <= 0:
            raise ValueError("stale_after must be positive")
        for timeout in self.timeout_seconds.values():
            if timeout is not None and timeout <= 0:
                raise ValueError("step timeouts must be positive")

    def timeout_for(self, step_name: StepName) -> float | None:
        return self.timeout_seconds.get(step_name)

    def backoff_for_attempt(self, attempt_number: int) -> float:
        return self.backoff_seconds * (2 ** max(0, attempt_number - 1))


def is_transient_error(error: BaseException) -> bool:
    if isinstance(error, PermanentStepError):
        return False
    if isinstance(error, (TransientStepError, StepTimeoutError, TimeoutError, ConnectionError)):
        return True
    try:
        from sqlalchemy.exc import OperationalError

        if isinstance(error, OperationalError):
            return True
    except ImportError:
        pass
    try:
        import httpx

        if isinstance(error, (httpx.TimeoutException, httpx.TransportError)):
            return True
    except ImportError:
        pass
    return False
