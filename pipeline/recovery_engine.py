"""Provide deterministic failure isolation and recovery for pipeline stages."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeAlias, TypeVar

from pipeline.domain import (
    PipelineError,
    PipelineStageError,
    PipelineStageStatus,
    StageResult,
)


StageValue = TypeVar("StageValue")

StageOperation: TypeAlias = Callable[[], StageValue]
ProcessedCountResolver: TypeAlias = Callable[[StageValue], int]

_ISOLATED_EXCEPTIONS: tuple[type[Exception], ...] = (Exception,)


class RecoveryDisposition(StrEnum):
    """Describe the final recovery decision for one stage."""

    COMPLETED = "completed"
    RETRIED = "retried"
    FALLBACK = "fallback"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RecoveryPolicy:
    """Control retry and terminal failure behavior."""

    max_attempts: int = 1
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,)
    skip_after_failure: bool = False

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be greater than zero")

        if not self.retryable_exceptions:
            raise ValueError("retryable_exceptions must not be empty")

        invalid_type_exists = any(
            not isinstance(exception_type, type)
            or not issubclass(exception_type, Exception)
            for exception_type in self.retryable_exceptions
        )

        if invalid_type_exists:
            raise TypeError("retryable_exceptions must contain Exception subclasses")


@dataclass(frozen=True, slots=True)
class ExecutionOptions(Generic[StageValue]):
    """Group optional execution and recovery configuration."""

    policy: RecoveryPolicy = RecoveryPolicy()
    fallback: StageOperation[StageValue] | None = None
    processed_count: int = 0
    processed_count_resolver: ProcessedCountResolver[StageValue] | None = None

    def __post_init__(self) -> None:
        _validate_processed_count(self.processed_count)


@dataclass(frozen=True, slots=True)
class StageAttempt:
    """Record one stage or fallback execution attempt."""

    number: int
    succeeded: bool
    message: str = ""
    error_type: str = ""

    def __post_init__(self) -> None:
        normalized_message = self.message.strip()
        normalized_error_type = self.error_type.strip()

        if self.number < 1:
            raise ValueError("attempt number must be greater than zero")

        if self.succeeded and normalized_error_type:
            raise ValueError("successful attempts must not contain an error type")

        if not self.succeeded and not normalized_message:
            raise ValueError("failed attempts require a non-empty message")

        if not self.succeeded and not normalized_error_type:
            raise ValueError("failed attempts require a non-empty error type")

        object.__setattr__(self, "message", normalized_message)
        object.__setattr__(self, "error_type", normalized_error_type)


@dataclass(frozen=True, slots=True)
class StageExecution(Generic[StageValue]):
    """Contain one isolated stage execution outcome."""

    result: StageResult
    disposition: RecoveryDisposition
    attempts: tuple[StageAttempt, ...]
    value: StageValue | None = None
    error: PipelineStageError | None = None

    def __post_init__(self) -> None:
        self._validate_attempts()

        validators: dict[
            PipelineStageStatus,
            Callable[[], None],
        ] = {
            PipelineStageStatus.SUCCEEDED: self._validate_success,
            PipelineStageStatus.SKIPPED: self._validate_skipped,
            PipelineStageStatus.FAILED: self._validate_failure,
        }

        validator = validators.get(self.result.status)

        if validator is not None:
            validator()

    @property
    def succeeded(self) -> bool:
        """Return whether the stage completed successfully."""

        return self.result.status is PipelineStageStatus.SUCCEEDED

    @property
    def skipped(self) -> bool:
        """Return whether the stage was deliberately skipped."""

        return self.result.status is PipelineStageStatus.SKIPPED

    @property
    def failed(self) -> bool:
        """Return whether the stage remained unsuccessful."""

        return self.result.status is PipelineStageStatus.FAILED

    @property
    def recovered(self) -> bool:
        """Return whether retry or fallback recovered the stage."""

        return self.disposition in {
            RecoveryDisposition.RETRIED,
            RecoveryDisposition.FALLBACK,
        }

    def _validate_attempts(self) -> None:
        if not self.attempts:
            raise ValueError("stage execution must contain at least one attempt")

        expected_numbers = tuple(range(1, len(self.attempts) + 1))
        actual_numbers = tuple(attempt.number for attempt in self.attempts)

        if actual_numbers != expected_numbers:
            raise ValueError("stage attempts must use contiguous one-based numbering")

    def _validate_success(self) -> None:
        allowed_dispositions = {
            RecoveryDisposition.COMPLETED,
            RecoveryDisposition.RETRIED,
            RecoveryDisposition.FALLBACK,
        }

        if self.error is not None:
            raise ValueError(
                "successful stage executions must not contain a final error"
            )

        if self.disposition not in allowed_dispositions:
            raise ValueError("successful stage execution has an invalid disposition")

        if not self.attempts[-1].succeeded:
            raise ValueError("successful stage execution must end successfully")

    def _validate_skipped(self) -> None:
        if self.disposition is not RecoveryDisposition.SKIPPED:
            raise ValueError("skipped stage execution requires skipped disposition")

        if self.error is None:
            raise ValueError("skipped stage execution must retain its final error")

        if self.attempts[-1].succeeded:
            raise ValueError("skipped stage execution must end with a failed attempt")

    def _validate_failure(self) -> None:
        if self.disposition is not RecoveryDisposition.FAILED:
            raise ValueError("failed stage execution requires failed disposition")

        if self.error is None:
            raise ValueError("failed stage execution must contain a final error")

        if self.attempts[-1].succeeded:
            raise ValueError("failed stage execution must end with a failed attempt")


@dataclass(frozen=True, slots=True)
class PipelineRecoveryReport:
    """Aggregate isolated stage executions."""

    executions: tuple[StageExecution[object], ...]

    def __post_init__(self) -> None:
        stage_names = tuple(execution.result.stage for execution in self.executions)

        if len(stage_names) != len(set(stage_names)):
            raise ValueError(
                "pipeline recovery report must not contain duplicate stages"
            )

    @property
    def stage_results(self) -> tuple[StageResult, ...]:
        """Return domain results in their execution order."""

        return tuple(execution.result for execution in self.executions)

    @property
    def succeeded_count(self) -> int:
        """Return the successful stage count."""

        return sum(execution.succeeded for execution in self.executions)

    @property
    def recovered_count(self) -> int:
        """Return the recovered stage count."""

        return sum(execution.recovered for execution in self.executions)

    @property
    def skipped_count(self) -> int:
        """Return the skipped stage count."""

        return sum(execution.skipped for execution in self.executions)

    @property
    def failed_count(self) -> int:
        """Return the unrecovered stage count."""

        return sum(execution.failed for execution in self.executions)

    @property
    def processed_count(self) -> int:
        """Return the total processed item count."""

        return sum(execution.result.processed_count for execution in self.executions)

    @property
    def has_failures(self) -> bool:
        """Return whether at least one stage failed."""

        return self.failed_count > 0

    @property
    def completed(self) -> bool:
        """Return whether no stage remains failed."""

        return not self.has_failures

    def execution_for(self, stage: str) -> StageExecution[object] | None:
        """Return an execution by stage name."""

        normalized_stage = _normalize_stage_name(stage)

        return next(
            (
                execution
                for execution in self.executions
                if execution.result.stage == normalized_stage
            ),
            None,
        )


@dataclass(frozen=True, slots=True)
class _SuccessContext(Generic[StageValue]):
    """Contain successful execution construction data."""

    attempts: tuple[StageAttempt, ...]
    disposition: RecoveryDisposition
    options: ExecutionOptions[StageValue]


@dataclass(frozen=True, slots=True)
class _TerminalContext:
    """Contain terminal execution construction data."""

    attempts: tuple[StageAttempt, ...]
    processed_count: int
    skip_after_failure: bool


class RecoveryEngine:
    """Execute independent stages with deterministic recovery behavior."""

    def execute(
        self,
        stage: str,
        operation: StageOperation[StageValue],
        options: ExecutionOptions[StageValue] | None = None,
    ) -> StageExecution[StageValue]:
        """Execute one isolated stage."""

        normalized_stage = _normalize_stage_name(stage)
        resolved_options = options or ExecutionOptions()
        attempts: list[StageAttempt] = []
        last_error: Exception | None = None

        for attempt_number in range(
            1,
            resolved_options.policy.max_attempts + 1,
        ):
            outcome = self._attempt_operation(
                operation,
                attempt_number,
            )
            attempts.append(outcome.attempt)

            if outcome.error is None:
                disposition = _primary_success_disposition(attempt_number)
                context = _SuccessContext(
                    attempts=tuple(attempts),
                    disposition=disposition,
                    options=resolved_options,
                )

                return _successful_execution(
                    normalized_stage,
                    outcome.value,
                    context,
                )

            last_error = outcome.error

            if not _should_retry(
                outcome.error,
                attempt_number,
                resolved_options.policy,
            ):
                break

        required_error = _require_error(last_error)

        if resolved_options.fallback is not None:
            return self._execute_fallback(
                normalized_stage,
                attempts,
                required_error,
                resolved_options,
            )

        terminal_context = _TerminalContext(
            attempts=tuple(attempts),
            processed_count=resolved_options.processed_count,
            skip_after_failure=(resolved_options.policy.skip_after_failure),
        )

        return _terminal_execution(
            normalized_stage,
            required_error,
            terminal_context,
        )

    def skip(
        self,
        stage: str,
        message: str,
    ) -> StageExecution[None]:
        """Create an explicit skipped execution."""

        normalized_stage = _normalize_stage_name(stage)
        normalized_message = _normalize_message(message)
        error = PipelineStageError(
            normalized_stage,
            normalized_message,
        )
        attempt = StageAttempt(
            number=1,
            succeeded=False,
            message=normalized_message,
            error_type=error.__class__.__name__,
        )

        return StageExecution(
            result=StageResult(
                stage=normalized_stage,
                status=PipelineStageStatus.SKIPPED,
                message=normalized_message,
            ),
            disposition=RecoveryDisposition.SKIPPED,
            attempts=(attempt,),
            error=error,
        )

    def report(
        self,
        executions: Iterable[StageExecution[object]],
    ) -> PipelineRecoveryReport:
        """Build an immutable recovery report."""

        return PipelineRecoveryReport(tuple(executions))

    @staticmethod
    def _attempt_operation(
        operation: StageOperation[StageValue],
        attempt_number: int,
    ) -> _AttemptOutcome[StageValue]:
        try:
            value = operation()
        except _ISOLATED_EXCEPTIONS as error:
            return _AttemptOutcome(
                attempt=_failed_attempt(attempt_number, error),
                error=error,
            )

        return _AttemptOutcome(
            attempt=StageAttempt(
                number=attempt_number,
                succeeded=True,
            ),
            value=value,
        )

    def _execute_fallback(
        self,
        stage: str,
        attempts: list[StageAttempt],
        original_error: Exception,
        options: ExecutionOptions[StageValue],
    ) -> StageExecution[StageValue]:
        fallback = _require_fallback(options.fallback)
        outcome = self._attempt_operation(
            fallback,
            len(attempts) + 1,
        )
        attempts.append(outcome.attempt)

        if outcome.error is None:
            context = _SuccessContext(
                attempts=tuple(attempts),
                disposition=RecoveryDisposition.FALLBACK,
                options=options,
            )

            return _successful_execution(
                stage,
                outcome.value,
                context,
            )

        combined_error = PipelineStageError(
            stage,
            _fallback_failure_message(
                original_error,
                outcome.error,
            ),
            cause=outcome.error,
        )
        terminal_context = _TerminalContext(
            attempts=tuple(attempts),
            processed_count=options.processed_count,
            skip_after_failure=options.policy.skip_after_failure,
        )

        return _terminal_execution_from_stage_error(
            stage,
            combined_error,
            terminal_context,
        )


@dataclass(frozen=True, slots=True)
class _AttemptOutcome(Generic[StageValue]):
    """Contain one safely captured operation outcome."""

    attempt: StageAttempt
    value: StageValue | None = None
    error: Exception | None = None

    def __post_init__(self) -> None:
        if self.attempt.succeeded and self.error is not None:
            raise ValueError("successful attempt outcome must not contain an error")

        if not self.attempt.succeeded and self.error is None:
            raise ValueError("failed attempt outcome must contain an error")


def execute_stage(
    stage: str,
    operation: StageOperation[StageValue],
    options: ExecutionOptions[StageValue] | None = None,
) -> StageExecution[StageValue]:
    """Execute one stage through the default recovery engine."""

    return RecoveryEngine().execute(
        stage,
        operation,
        options,
    )


def build_recovery_report(
    executions: Sequence[StageExecution[object]],
) -> PipelineRecoveryReport:
    """Build an immutable recovery report."""

    return PipelineRecoveryReport(tuple(executions))


def _successful_execution(
    stage: str,
    value: StageValue | None,
    context: _SuccessContext[StageValue],
) -> StageExecution[StageValue]:
    processed_count = _resolve_processed_count(
        value,
        context.options,
    )

    return StageExecution(
        result=StageResult(
            stage=stage,
            status=PipelineStageStatus.SUCCEEDED,
            processed_count=processed_count,
            message=_success_message(
                context.disposition,
                len(context.attempts),
            ),
        ),
        disposition=context.disposition,
        attempts=context.attempts,
        value=value,
    )


def _terminal_execution(
    stage: str,
    error: Exception,
    context: _TerminalContext,
) -> StageExecution[StageValue]:
    stage_error = _to_stage_error(stage, error)

    return _terminal_execution_from_stage_error(
        stage,
        stage_error,
        context,
    )


def _terminal_execution_from_stage_error(
    stage: str,
    error: PipelineStageError,
    context: _TerminalContext,
) -> StageExecution[StageValue]:
    if context.skip_after_failure:
        status = PipelineStageStatus.SKIPPED
        disposition = RecoveryDisposition.SKIPPED
    else:
        status = PipelineStageStatus.FAILED
        disposition = RecoveryDisposition.FAILED

    return StageExecution(
        result=StageResult(
            stage=stage,
            status=status,
            processed_count=context.processed_count,
            message=error.message,
        ),
        disposition=disposition,
        attempts=context.attempts,
        error=error,
    )


def _failed_attempt(
    number: int,
    error: Exception,
) -> StageAttempt:
    return StageAttempt(
        number=number,
        succeeded=False,
        message=_exception_message(error),
        error_type=error.__class__.__name__,
    )


def _should_retry(
    error: Exception,
    attempt_number: int,
    policy: RecoveryPolicy,
) -> bool:
    attempts_remain = attempt_number < policy.max_attempts
    exception_is_retryable = isinstance(
        error,
        policy.retryable_exceptions,
    )

    return attempts_remain and exception_is_retryable


def _resolve_processed_count(
    value: StageValue | None,
    options: ExecutionOptions[StageValue],
) -> int:
    resolver = options.processed_count_resolver

    if resolver is None:
        return options.processed_count

    if value is None:
        raise ValueError("processed_count_resolver requires a successful value")

    resolved_count = resolver(value)
    _validate_processed_count(resolved_count)

    return resolved_count


def _validate_processed_count(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("processed_count must be an integer")

    if value < 0:
        raise ValueError("processed_count must not be negative")


def _to_stage_error(
    stage: str,
    error: Exception,
) -> PipelineStageError:
    if isinstance(error, PipelineStageError):
        if error.stage == stage:
            return error

        return PipelineStageError(
            stage,
            error.message,
            cause=error,
        )

    return PipelineStageError(
        stage,
        _exception_message(error),
        cause=error,
    )


def _require_error(error: Exception | None) -> Exception:
    if error is None:
        raise RuntimeError(
            "recovery engine reached a failure path without an exception"
        )

    return error


def _require_fallback(
    fallback: StageOperation[StageValue] | None,
) -> StageOperation[StageValue]:
    if fallback is None:
        raise RuntimeError("fallback execution requested without a fallback operation")

    return fallback


def _exception_message(error: BaseException) -> str:
    if isinstance(error, PipelineStageError):
        return error.message

    message = str(error).strip()

    if message:
        return message

    if isinstance(error, PipelineError):
        return error.__class__.__name__

    return f"Unexpected {error.__class__.__name__}"


def _fallback_failure_message(
    original_error: Exception,
    fallback_error: Exception,
) -> str:
    primary_message = _exception_message(original_error)
    fallback_message = _exception_message(fallback_error)

    return (
        f"Primary operation failed: {primary_message}; "
        f"fallback operation failed: {fallback_message}"
    )


def _primary_success_disposition(
    attempt_number: int,
) -> RecoveryDisposition:
    if attempt_number == 1:
        return RecoveryDisposition.COMPLETED

    return RecoveryDisposition.RETRIED


def _success_message(
    disposition: RecoveryDisposition,
    attempt_count: int,
) -> str:
    if disposition is RecoveryDisposition.RETRIED:
        return f"Stage recovered successfully after {attempt_count} attempts."

    if disposition is RecoveryDisposition.FALLBACK:
        return "Stage recovered successfully through its fallback operation."

    return ""


def _normalize_stage_name(stage: str) -> str:
    normalized_stage = stage.strip()

    if not normalized_stage:
        raise ValueError("stage must not be empty")

    return normalized_stage


def _normalize_message(message: str) -> str:
    normalized_message = message.strip()

    if not normalized_message:
        raise ValueError("message must not be empty")

    return normalized_message


__all__ = [
    "ExecutionOptions",
    "PipelineRecoveryReport",
    "RecoveryDisposition",
    "RecoveryEngine",
    "RecoveryPolicy",
    "StageAttempt",
    "StageExecution",
    "build_recovery_report",
    "execute_stage",
]
