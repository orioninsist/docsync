"""Pure document content normalization and validation boundary."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, TypeAlias

UnicodeNormalizationForm: TypeAlias = Literal["NFC", "NFD", "NFKC", "NFKD"]

_DEFAULT_MAX_CHARACTERS = 10_000_000
_DEFAULT_MAX_LINE_LENGTH = 100_000
_DEFAULT_TAB_WIDTH = 4
_NEWLINE_PATTERN = re.compile(r"\r\n?|\n")
_TRAILING_WHITESPACE_PATTERN = re.compile(r"[ \t]+$")
_BLANK_LINE_PATTERN = re.compile(r"\n{3,}")


class ValidationCode(StrEnum):
    """Stable validation failure identifiers."""

    EMPTY_CONTENT = "empty_content"
    NULL_CHARACTER = "null_character"
    CONTENT_TOO_LARGE = "content_too_large"
    LINE_TOO_LONG = "line_too_long"


@dataclass(frozen=True, slots=True)
class NormalizationPolicy:
    """Immutable rules controlling normalization and validation."""

    unicode_form: UnicodeNormalizationForm = "NFC"
    tab_width: int = _DEFAULT_TAB_WIDTH
    max_characters: int = _DEFAULT_MAX_CHARACTERS
    max_line_length: int = _DEFAULT_MAX_LINE_LENGTH
    collapse_excess_blank_lines: bool = True
    require_non_empty_content: bool = True
    ensure_terminal_newline: bool = True

    def __post_init__(self) -> None:
        """Validate policy configuration."""

        if self.tab_width < 1:
            raise ValueError("tab_width must be greater than zero")

        if self.max_characters < 1:
            raise ValueError("max_characters must be greater than zero")

        if self.max_line_length < 1:
            raise ValueError("max_line_length must be greater than zero")


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Immutable validation issue produced for one document."""

    code: ValidationCode
    message: str
    line_number: int | None = None

    def __post_init__(self) -> None:
        """Validate issue invariants."""

        if not self.message.strip():
            raise ValueError("Validation issue message must not be empty")

        if self.line_number is not None and self.line_number < 1:
            raise ValueError("line_number must be greater than zero")


@dataclass(frozen=True, slots=True)
class NormalizedDocument:
    """Normalized document content and its validation result."""

    content: str
    issues: tuple[ValidationIssue, ...]

    @property
    def is_valid(self) -> bool:
        """Return whether validation completed without issues."""

        return not self.issues


class DocumentNormalizer:
    """Normalize and validate text without filesystem side effects."""

    def __init__(self, policy: NormalizationPolicy | None = None) -> None:
        """Initialize the normalizer with immutable policy rules."""

        self._policy = policy or NormalizationPolicy()

    @property
    def policy(self) -> NormalizationPolicy:
        """Return the active normalization policy."""

        return self._policy

    def normalize(self, content: str) -> NormalizedDocument:
        """Normalize content deterministically and return validation issues."""

        normalized = self._normalize_content(content)
        issues = self._validate_content(normalized)

        return NormalizedDocument(
            content=normalized,
            issues=issues,
        )

    def _normalize_content(self, content: str) -> str:
        """Apply deterministic, idempotent text normalization."""

        normalized = unicodedata.normalize(
            self._policy.unicode_form,
            content,
        )
        normalized = self._normalize_newlines(normalized)
        normalized = normalized.expandtabs(self._policy.tab_width)
        normalized = self._remove_trailing_whitespace(normalized)

        if self._policy.collapse_excess_blank_lines:
            normalized = _BLANK_LINE_PATTERN.sub("\n\n", normalized)

        normalized = normalized.strip("\n")

        if normalized and self._policy.ensure_terminal_newline:
            normalized = f"{normalized}\n"

        return normalized

    def _validate_content(self, content: str) -> tuple[ValidationIssue, ...]:
        """Return all deterministic validation issues for normalized content."""

        issues: list[ValidationIssue] = []

        if "\x00" in content:
            issues.append(
                ValidationIssue(
                    code=ValidationCode.NULL_CHARACTER,
                    message="Document content contains a null character",
                )
            )

        if self._policy.require_non_empty_content and not content.strip():
            issues.append(
                ValidationIssue(
                    code=ValidationCode.EMPTY_CONTENT,
                    message="Document content is empty after normalization",
                )
            )

        if len(content) > self._policy.max_characters:
            issues.append(
                ValidationIssue(
                    code=ValidationCode.CONTENT_TOO_LARGE,
                    message=(
                        "Document content exceeds the configured character "
                        f"limit of {self._policy.max_characters}"
                    ),
                )
            )

        issues.extend(self._find_long_lines(content))

        return tuple(issues)

    def _find_long_lines(self, content: str) -> tuple[ValidationIssue, ...]:
        """Return validation issues for lines exceeding the configured limit."""

        issues: list[ValidationIssue] = []

        for line_number, line in enumerate(content.splitlines(), start=1):
            if len(line) <= self._policy.max_line_length:
                continue

            issues.append(
                ValidationIssue(
                    code=ValidationCode.LINE_TOO_LONG,
                    message=(
                        "Line exceeds the configured length limit of "
                        f"{self._policy.max_line_length} characters"
                    ),
                    line_number=line_number,
                )
            )

        return tuple(issues)

    @staticmethod
    def _normalize_newlines(content: str) -> str:
        """Convert all supported line endings to Unix newlines."""

        return _NEWLINE_PATTERN.sub("\n", content)

    @staticmethod
    def _remove_trailing_whitespace(content: str) -> str:
        """Remove trailing horizontal whitespace from every line."""

        return "\n".join(
            _TRAILING_WHITESPACE_PATTERN.sub("", line) for line in content.split("\n")
        )


def normalize_document(
    content: str,
    *,
    policy: NormalizationPolicy | None = None,
) -> NormalizedDocument:
    """Normalize and validate one document using the supplied policy."""

    return DocumentNormalizer(policy).normalize(content)
