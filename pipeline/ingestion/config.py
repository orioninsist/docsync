"""Immutable configuration contract for document ingestion processing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


DEFAULT_MAX_FILE_SIZE_BYTES: Final[int] = 500 * 1024
DEFAULT_MAX_FILE_TOKENS: Final[int] = 100_000
DEFAULT_GPT_HARD_CEILING_TOKENS: Final[int] = 2_000_000
DEFAULT_TOKEN_ENCODING: Final[str] = "cl100k_base"
DEFAULT_SIMILARITY_THRESHOLD: Final[float] = 0.80

DEFAULT_SUPPORTED_TEXT_SUFFIXES: Final[tuple[str, ...]] = (
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

DEFAULT_CONVERTIBLE_TABULAR_SUFFIXES: Final[tuple[str, ...]] = (
    ".csv",
    ".xlsx",
)

DEFAULT_EXCLUDED_SUFFIXES: Final[tuple[str, ...]] = (".gdoc",)


class IngestionConfigurationError(ValueError):
    """Raised when ingestion configuration violates its contract."""


def _require_positive_integer(value: int, *, field_name: str) -> None:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be an integer")

    if value < 1:
        raise IngestionConfigurationError(
            f"{field_name} must be greater than zero",
        )


def _normalize_suffixes(
    suffixes: tuple[str, ...],
    *,
    field_name: str,
) -> tuple[str, ...]:
    """Return unique, deterministic lowercase suffixes."""

    normalized: set[str] = set()

    for suffix in suffixes:
        candidate = suffix.strip().casefold()

        if not candidate:
            raise IngestionConfigurationError(
                f"{field_name} must not contain empty suffixes",
            )

        if not candidate.startswith("."):
            candidate = f".{candidate}"

        if candidate == ".":
            raise IngestionConfigurationError(
                f"{field_name} entries must contain characters after the dot",
            )

        if "/" in candidate or "\\" in candidate:
            raise IngestionConfigurationError(
                f"{field_name} entries must not contain path separators",
            )

        normalized.add(candidate)

    if not normalized:
        raise IngestionConfigurationError(
            f"{field_name} must contain at least one suffix",
        )

    return tuple(sorted(normalized))


@dataclass(frozen=True, slots=True)
class FileLimitConfig:
    """Define defensive size and token limits for one generated document."""

    max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES
    max_file_tokens: int = DEFAULT_MAX_FILE_TOKENS
    hard_token_ceiling: int = DEFAULT_GPT_HARD_CEILING_TOKENS
    token_encoding: str = DEFAULT_TOKEN_ENCODING

    def __post_init__(self) -> None:
        """Validate file-limit invariants."""

        _require_positive_integer(
            self.max_file_size_bytes,
            field_name="max_file_size_bytes",
        )
        _require_positive_integer(
            self.max_file_tokens,
            field_name="max_file_tokens",
        )
        _require_positive_integer(
            self.hard_token_ceiling,
            field_name="hard_token_ceiling",
        )

        if self.hard_token_ceiling < self.max_file_tokens:
            raise IngestionConfigurationError(
                "hard_token_ceiling must not be lower than max_file_tokens",
            )

        normalized_encoding = self.token_encoding.strip()

        if not normalized_encoding:
            raise IngestionConfigurationError(
                "token_encoding must not be empty",
            )

        object.__setattr__(self, "token_encoding", normalized_encoding)


@dataclass(frozen=True, slots=True)
class RoutingConfig:
    """Define deterministic semantic-routing behavior."""

    readme_first: bool = True
    isolate_installation: bool = True
    isolate_faq_and_troubleshooting: bool = True
    prefer_sibling_documents: bool = True
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD

    def __post_init__(self) -> None:
        """Validate semantic-routing invariants."""

        if isinstance(self.similarity_threshold, bool):
            raise TypeError("similarity_threshold must be a number")

        if not 0.0 <= self.similarity_threshold <= 1.0:
            raise IngestionConfigurationError(
                "similarity_threshold must be between 0.0 and 1.0",
            )

        object.__setattr__(
            self,
            "similarity_threshold",
            float(self.similarity_threshold),
        )


@dataclass(frozen=True, slots=True)
class TransformationConfig:
    """Define deterministic document-conversion and cleaning behavior."""

    convert_tabular_files: bool = True
    flatten_json: bool = True
    annotate_image_references: bool = True
    strip_html_comments: bool = True
    strip_historical_changelogs: bool = True
    strip_commented_code: bool = True
    consolidate_duplicate_headers: bool = True
    collapse_redundant_bullet_levels: bool = True
    ensure_single_blank_line: bool = True
    include_table_of_contents: bool = True


@dataclass(frozen=True, slots=True)
class FileFormatConfig:
    """Define supported, convertible, and excluded document suffixes."""

    supported_text_suffixes: tuple[str, ...] = DEFAULT_SUPPORTED_TEXT_SUFFIXES
    convertible_tabular_suffixes: tuple[str, ...] = DEFAULT_CONVERTIBLE_TABULAR_SUFFIXES
    excluded_suffixes: tuple[str, ...] = DEFAULT_EXCLUDED_SUFFIXES

    def __post_init__(self) -> None:
        """Normalize and validate configured suffix collections."""

        supported = _normalize_suffixes(
            self.supported_text_suffixes,
            field_name="supported_text_suffixes",
        )
        convertible = _normalize_suffixes(
            self.convertible_tabular_suffixes,
            field_name="convertible_tabular_suffixes",
        )
        excluded = _normalize_suffixes(
            self.excluded_suffixes,
            field_name="excluded_suffixes",
        )

        supported_set = set(supported)
        convertible_set = set(convertible)
        excluded_set = set(excluded)

        if supported_set & convertible_set:
            raise IngestionConfigurationError(
                "supported and convertible suffixes must not overlap",
            )

        if supported_set & excluded_set:
            raise IngestionConfigurationError(
                "supported and excluded suffixes must not overlap",
            )

        if convertible_set & excluded_set:
            raise IngestionConfigurationError(
                "convertible and excluded suffixes must not overlap",
            )

        object.__setattr__(self, "supported_text_suffixes", supported)
        object.__setattr__(self, "convertible_tabular_suffixes", convertible)
        object.__setattr__(self, "excluded_suffixes", excluded)


@dataclass(frozen=True, slots=True)
class IngestionConfig:
    """Contain all user-controlled ingestion behavior in one immutable object."""

    limits: FileLimitConfig = FileLimitConfig()
    routing: RoutingConfig = RoutingConfig()
    transformation: TransformationConfig = TransformationConfig()
    formats: FileFormatConfig = FileFormatConfig()


DEFAULT_INGESTION_CONFIG: Final[IngestionConfig] = IngestionConfig()


__all__ = [
    "DEFAULT_CONVERTIBLE_TABULAR_SUFFIXES",
    "DEFAULT_EXCLUDED_SUFFIXES",
    "DEFAULT_GPT_HARD_CEILING_TOKENS",
    "DEFAULT_INGESTION_CONFIG",
    "DEFAULT_MAX_FILE_SIZE_BYTES",
    "DEFAULT_MAX_FILE_TOKENS",
    "DEFAULT_SIMILARITY_THRESHOLD",
    "DEFAULT_SUPPORTED_TEXT_SUFFIXES",
    "DEFAULT_TOKEN_ENCODING",
    "FileFormatConfig",
    "FileLimitConfig",
    "IngestionConfig",
    "IngestionConfigurationError",
    "RoutingConfig",
    "TransformationConfig",
]
