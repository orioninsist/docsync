"""Deterministic token and byte budget boundary for ingestion documents.

This module measures immutable ingestion documents and validates their content
against configured byte and token limits. It performs no filesystem access,
document conversion, content cleaning, semantic analysis, routing, merging,
persistence, or orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pipeline.ingestion.config import FileLimitConfig
from pipeline.ingestion.model import DocumentStatistics, IngestionDocument


class TokenBudgetError(ValueError):
    """Raised when document content violates a configured budget."""


class ByteBudgetExceededError(TokenBudgetError):
    """Raised when encoded document content exceeds its byte limit."""


class TokenBudgetExceededError(TokenBudgetError):
    """Raised when document content exceeds its configured token limit."""


class HardTokenCeilingExceededError(TokenBudgetError):
    """Raised when document content exceeds the absolute token ceiling."""


@runtime_checkable
class TokenCounter(Protocol):
    """Count tokens for text using one explicitly selected encoding."""

    def count_tokens(self, content: str, *, encoding_name: str) -> int:
        """Return the non-negative token count for content."""
        ...


@dataclass(frozen=True, slots=True)
class BudgetMeasurement:
    """Contain immutable document measurements and configured limit status."""

    statistics: DocumentStatistics
    max_file_size_bytes: int
    max_file_tokens: int
    hard_token_ceiling: int

    @property
    def fits_byte_budget(self) -> bool:
        """Return whether content fits the configured byte budget."""

        return self.statistics.byte_count <= self.max_file_size_bytes

    @property
    def fits_token_budget(self) -> bool | None:
        """Return token-budget status when a token count is available."""

        if self.statistics.token_count is None:
            return None

        return self.statistics.token_count <= self.max_file_tokens

    @property
    def fits_hard_token_ceiling(self) -> bool | None:
        """Return hard-ceiling status when a token count is available."""

        if self.statistics.token_count is None:
            return None

        return self.statistics.token_count <= self.hard_token_ceiling

    @property
    def is_within_budget(self) -> bool:
        """Return whether all available measurements satisfy their limits."""

        token_budget_status = self.fits_token_budget
        hard_ceiling_status = self.fits_hard_token_ceiling

        return (
            self.fits_byte_budget
            and token_budget_status is not False
            and hard_ceiling_status is not False
        )


@dataclass(frozen=True, slots=True)
class TokenBudgetService:
    """Measure and validate document content without external runtime state."""

    limits: FileLimitConfig
    token_counter: TokenCounter | None = None
    byte_encoding: str = "utf-8"

    def __post_init__(self) -> None:
        if not isinstance(self.limits, FileLimitConfig):
            raise TypeError("limits must be a FileLimitConfig")

        if self.token_counter is not None and not isinstance(
            self.token_counter,
            TokenCounter,
        ):
            raise TypeError("token_counter must implement TokenCounter")

        if not isinstance(self.byte_encoding, str):
            raise TypeError("byte_encoding must be a string")

        normalized_encoding = self.byte_encoding.strip()

        if not normalized_encoding:
            raise TokenBudgetError("byte_encoding must not be empty")

        try:
            "".encode(normalized_encoding)
        except LookupError as error:
            raise TokenBudgetError(
                f"unknown byte encoding: {normalized_encoding}",
            ) from error

        object.__setattr__(self, "byte_encoding", normalized_encoding)

    def measure(self, document: IngestionDocument) -> BudgetMeasurement:
        """Return deterministic measurements for one ingestion document."""

        if not isinstance(document, IngestionDocument):
            raise TypeError("document must be an IngestionDocument")

        encoded_content = document.content.encode(self.byte_encoding)
        token_count = self._count_tokens(document.content)

        statistics = DocumentStatistics(
            character_count=len(document.content),
            byte_count=len(encoded_content),
            token_count=token_count,
            section_count=len(document.sections),
        )

        return BudgetMeasurement(
            statistics=statistics,
            max_file_size_bytes=self.limits.max_file_size_bytes,
            max_file_tokens=self.limits.max_file_tokens,
            hard_token_ceiling=self.limits.hard_token_ceiling,
        )

    def validate(self, document: IngestionDocument) -> DocumentStatistics:
        """Measure document content and raise when a budget is exceeded."""

        measurement = self.measure(document)
        statistics = measurement.statistics

        if not measurement.fits_byte_budget:
            raise ByteBudgetExceededError(
                "document byte count exceeds max_file_size_bytes: "
                f"{statistics.byte_count} > "
                f"{measurement.max_file_size_bytes}",
            )

        if measurement.fits_hard_token_ceiling is False:
            raise HardTokenCeilingExceededError(
                "document token count exceeds hard_token_ceiling: "
                f"{statistics.token_count} > "
                f"{measurement.hard_token_ceiling}",
            )

        if measurement.fits_token_budget is False:
            raise TokenBudgetExceededError(
                "document token count exceeds max_file_tokens: "
                f"{statistics.token_count} > "
                f"{measurement.max_file_tokens}",
            )

        return statistics

    def attach_statistics(
        self,
        document: IngestionDocument,
    ) -> IngestionDocument:
        """Return a new immutable document with validated statistics."""

        statistics = self.validate(document)

        return document.with_content(
            document.content,
            media_type=document.media_type,
            title=document.title,
            sections=document.sections,
            statistics=statistics,
        )

    def _count_tokens(self, content: str) -> int | None:
        if self.token_counter is None:
            return None

        token_count = self.token_counter.count_tokens(
            content,
            encoding_name=self.limits.token_encoding,
        )

        if isinstance(token_count, bool) or not isinstance(token_count, int):
            raise TypeError("token counter result must be an integer")

        if token_count < 0:
            raise TokenBudgetError(
                "token counter result must not be negative",
            )

        return token_count


__all__ = [
    "BudgetMeasurement",
    "ByteBudgetExceededError",
    "HardTokenCeilingExceededError",
    "TokenBudgetError",
    "TokenBudgetExceededError",
    "TokenBudgetService",
    "TokenCounter",
]
