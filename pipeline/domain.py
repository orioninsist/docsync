"""Immutable domain contracts and error hierarchy for the document pipeline.

This module contains only stable data structures and domain-specific error
types. It performs no filesystem access, networking, content transformation,
logging, subprocess execution, or pipeline orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from collections.abc import Mapping
from typing import Final, TypeAlias


MetadataValue: TypeAlias = str | int | float | bool | None
Metadata: TypeAlias = Mapping[str, MetadataValue]

_EMPTY_METADATA: Final[Metadata] = MappingProxyType({})


class PipelineError(Exception):
    """Base class for expected pipeline failures."""


class PipelineConfigurationError(PipelineError):
    """Raised when pipeline configuration is missing or invalid."""


class PipelineBoundaryError(PipelineError):
    """Raised when an operation violates an architectural boundary."""


class SourceInventoryError(PipelineError):
    """Raised when source inventory construction or validation fails."""


class SourceDocumentError(PipelineError):
    """Base class for failures associated with a source document."""


class SourceDocumentNotFoundError(SourceDocumentError):
    """Raised when an expected source document does not exist."""


class SourceDocumentReadError(SourceDocumentError):
    """Raised when a source document cannot be read safely."""


class SourceDocumentValidationError(SourceDocumentError):
    """Raised when a source document violates a domain invariant."""


class FingerprintError(PipelineError):
    """Raised when a content fingerprint cannot be produced or validated."""


class ChangeDetectionError(PipelineError):
    """Raised when document change detection cannot be completed."""


class DocumentTransformationError(PipelineError):
    """Raised when document normalization or transformation fails."""


class DocumentMergeError(PipelineError):
    """Raised when documents cannot be merged safely."""


class OutputWriteError(PipelineError):
    """Raised when pipeline output cannot be written atomically."""


class StatePersistenceError(PipelineError):
    """Raised when persistent pipeline state cannot be loaded or stored."""


class ExternalToolError(PipelineError):
    """Raised when an external command fails or returns invalid output."""


class PipelineStageError(PipelineError):
    """Raised when an isolated pipeline stage fails."""

    def __init__(
        self,
        stage: str,
        message: str,
        *,
        cause: BaseException | None = None,
    ) -> None:
        normalized_stage = stage.strip()
        normalized_message = message.strip()

        if not normalized_stage:
            raise ValueError("stage must not be empty")

        if not normalized_message:
            raise ValueError("message must not be empty")

        self.stage: str = normalized_stage
        self.message: str = normalized_message
        self.cause: BaseException | None = cause

        super().__init__(f"{self.stage}: {self.message}")


class ChangeKind(StrEnum):
    """Classification of a source document compared with persisted state."""

    ADDED = "added"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"
    REMOVED = "removed"


class PipelineStageStatus(StrEnum):
    """Execution status of an independently isolated pipeline stage."""

    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """Immutable identity and location of one source document."""

    source_root: Path
    relative_path: Path
    absolute_path: Path
    metadata: Metadata = field(default_factory=lambda: _EMPTY_METADATA)

    def __post_init__(self) -> None:
        source_root = self.source_root.expanduser()
        relative_path = self.relative_path
        absolute_path = self.absolute_path.expanduser()

        if not relative_path.parts:
            raise SourceDocumentValidationError(
                "relative_path must identify a document",
            )

        if relative_path.is_absolute():
            raise SourceDocumentValidationError(
                "relative_path must be relative",
            )

        if ".." in relative_path.parts:
            raise SourceDocumentValidationError(
                "relative_path must not escape source_root",
            )

        if not absolute_path.is_absolute():
            raise SourceDocumentValidationError(
                "absolute_path must be absolute",
            )

        expected_path = source_root.resolve(strict=False) / relative_path
        normalized_absolute_path = absolute_path.resolve(strict=False)

        if normalized_absolute_path != expected_path.resolve(strict=False):
            raise SourceDocumentValidationError(
                "absolute_path must equal source_root joined with relative_path",
            )

        immutable_metadata = MappingProxyType(dict(self.metadata))

        object.__setattr__(self, "source_root", source_root.resolve(strict=False))
        object.__setattr__(self, "absolute_path", normalized_absolute_path)
        object.__setattr__(self, "metadata", immutable_metadata)

    @property
    def identity(self) -> str:
        """Return the stable POSIX-style document identity."""

        return self.relative_path.as_posix()


@dataclass(frozen=True, slots=True)
class ContentFingerprint:
    """Immutable content fingerprint independent of storage implementation."""

    algorithm: str
    digest: str
    size_bytes: int

    def __post_init__(self) -> None:
        normalized_algorithm = self.algorithm.strip().lower()
        normalized_digest = self.digest.strip().lower()

        if not normalized_algorithm:
            raise FingerprintError("algorithm must not be empty")

        if not normalized_digest:
            raise FingerprintError("digest must not be empty")

        if any(character not in "0123456789abcdef" for character in normalized_digest):
            raise FingerprintError("digest must be lowercase hexadecimal")

        if self.size_bytes < 0:
            raise FingerprintError("size_bytes must not be negative")

        object.__setattr__(self, "algorithm", normalized_algorithm)
        object.__setattr__(self, "digest", normalized_digest)


@dataclass(frozen=True, slots=True)
class DocumentSnapshot:
    """Immutable observed state of one source document."""

    document: SourceDocument
    fingerprint: ContentFingerprint


@dataclass(frozen=True, slots=True)
class DocumentChange:
    """Immutable comparison result for one document identity."""

    identity: str
    kind: ChangeKind
    current: DocumentSnapshot | None = None
    previous: DocumentSnapshot | None = None

    def __post_init__(self) -> None:
        normalized_identity = self.identity.strip()

        if not normalized_identity:
            raise ChangeDetectionError("identity must not be empty")

        if self.kind is ChangeKind.ADDED:
            if self.current is None or self.previous is not None:
                raise ChangeDetectionError(
                    "added changes require current state only",
                )

        elif self.kind is ChangeKind.REMOVED:
            if self.previous is None or self.current is not None:
                raise ChangeDetectionError(
                    "removed changes require previous state only",
                )

        elif self.kind in {ChangeKind.MODIFIED, ChangeKind.UNCHANGED}:
            if self.current is None or self.previous is None:
                raise ChangeDetectionError(
                    f"{self.kind.value} changes require current and previous states",
                )

        object.__setattr__(self, "identity", normalized_identity)


@dataclass(frozen=True, slots=True)
class StageResult:
    """Immutable outcome of one independently executable pipeline stage."""

    stage: str
    status: PipelineStageStatus
    processed_count: int = 0
    message: str = ""

    def __post_init__(self) -> None:
        normalized_stage = self.stage.strip()
        normalized_message = self.message.strip()

        if not normalized_stage:
            raise ValueError("stage must not be empty")

        if self.processed_count < 0:
            raise ValueError("processed_count must not be negative")

        if self.status is PipelineStageStatus.FAILED and not normalized_message:
            raise ValueError("failed stage results require a message")

        object.__setattr__(self, "stage", normalized_stage)
        object.__setattr__(self, "message", normalized_message)
