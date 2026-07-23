"""Isolated document-reading boundary for the local pipeline.

This module owns filesystem document reads and converts expected I/O failures
into immutable result objects. Callers can therefore process each document
independently without allowing one unreadable file to terminate the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable


DEFAULT_ENCODING = "utf-8"
DEFAULT_TEXT_SUFFIXES = (
    ".adoc",
    ".html",
    ".htm",
    ".json",
    ".md",
    ".markdown",
    ".rst",
    ".text",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
)


class DocumentReadFailure(StrEnum):
    """Stable categories for expected document-reading failures."""

    NOT_FOUND = "not_found"
    NOT_A_FILE = "not_a_file"
    PERMISSION_DENIED = "permission_denied"
    DECODING_FAILED = "decoding_failed"
    IO_ERROR = "io_error"


@dataclass(frozen=True, slots=True)
class DocumentReadRequest:
    """Immutable input required to read one local document."""

    path: Path
    encoding: str = DEFAULT_ENCODING

    def __post_init__(self) -> None:
        normalized_path = self.path.expanduser()

        if not self.encoding.strip():
            raise ValueError("encoding must not be empty")

        object.__setattr__(self, "path", normalized_path)


@dataclass(frozen=True, slots=True)
class DocumentReadError:
    """Structured information about an isolated read failure."""

    failure: DocumentReadFailure
    path: Path
    message: str


@dataclass(frozen=True, slots=True)
class DocumentReadResult:
    """Immutable success-or-failure result for one document read."""

    path: Path
    content: str | None = None
    error: DocumentReadError | None = None

    def __post_init__(self) -> None:
        has_content = self.content is not None
        has_error = self.error is not None

        if has_content == has_error:
            raise ValueError(
                "DocumentReadResult must contain exactly one of content or error"
            )

        if self.error is not None and self.error.path != self.path:
            raise ValueError("result path and error path must match")

    @property
    def succeeded(self) -> bool:
        """Return whether the document was read successfully."""

        return self.error is None

    @classmethod
    def success(cls, *, path: Path, content: str) -> DocumentReadResult:
        """Create a successful immutable read result."""

        return cls(path=path, content=content)

    @classmethod
    def failure(
        cls,
        *,
        path: Path,
        failure: DocumentReadFailure,
        message: str,
    ) -> DocumentReadResult:
        """Create an immutable failed read result."""

        return cls(
            path=path,
            error=DocumentReadError(
                failure=failure,
                path=path,
                message=message,
            ),
        )


@runtime_checkable
class DocumentReader(Protocol):
    """Boundary implemented by services capable of reading one document."""

    def supports(self, path: Path) -> bool:
        """Return whether this reader supports the supplied document path."""
        ...

    def read(self, request: DocumentReadRequest) -> DocumentReadResult:
        """Read one document without propagating expected filesystem errors."""
        ...


@dataclass(frozen=True, slots=True)
class TextDocumentReader:
    """Read supported local text documents with isolated failure handling."""

    supported_suffixes: tuple[str, ...] = DEFAULT_TEXT_SUFFIXES

    def __post_init__(self) -> None:
        normalized_suffixes = tuple(
            sorted(
                {
                    _normalize_suffix(suffix)
                    for suffix in self.supported_suffixes
                    if suffix.strip()
                }
            )
        )

        if not normalized_suffixes:
            raise ValueError("supported_suffixes must not be empty")

        object.__setattr__(self, "supported_suffixes", normalized_suffixes)

    def supports(self, path: Path) -> bool:
        """Return whether the path has a supported text-document suffix."""

        return path.suffix.casefold() in self.supported_suffixes

    def read(self, request: DocumentReadRequest) -> DocumentReadResult:
        """Read one text document and return a structured result."""

        path = request.path

        if not path.exists():
            return DocumentReadResult.failure(
                path=path,
                failure=DocumentReadFailure.NOT_FOUND,
                message=f"Document does not exist: {path}",
            )

        if not path.is_file():
            return DocumentReadResult.failure(
                path=path,
                failure=DocumentReadFailure.NOT_A_FILE,
                message=f"Document path is not a regular file: {path}",
            )

        try:
            content = path.read_text(encoding=request.encoding)
        except PermissionError as error:
            return DocumentReadResult.failure(
                path=path,
                failure=DocumentReadFailure.PERMISSION_DENIED,
                message=_error_message(error),
            )
        except UnicodeDecodeError as error:
            return DocumentReadResult.failure(
                path=path,
                failure=DocumentReadFailure.DECODING_FAILED,
                message=_error_message(error),
            )
        except OSError as error:
            return DocumentReadResult.failure(
                path=path,
                failure=DocumentReadFailure.IO_ERROR,
                message=_error_message(error),
            )

        return DocumentReadResult.success(path=path, content=content)


def _normalize_suffix(suffix: str) -> str:
    """Normalize one configured file suffix."""

    normalized = suffix.strip().casefold()

    if normalized.startswith("."):
        return normalized

    return f".{normalized}"


def _error_message(error: BaseException) -> str:
    """Return a deterministic non-empty message for an expected exception."""

    message = str(error).strip()
    return message or error.__class__.__name__
