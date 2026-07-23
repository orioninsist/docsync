"""Immutable domain contracts for the document ingestion pipeline.

This module defines data exchanged between independent ingestion stages.
It performs no filesystem access, document conversion, content cleaning,
token calculation, semantic analysis, routing, persistence, or orchestration.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Final, TypeAlias


MetadataValue: TypeAlias = str | int | float | bool | None
DocumentMetadata: TypeAlias = Mapping[str, MetadataValue]

_EMPTY_METADATA: Final[DocumentMetadata] = MappingProxyType({})


class IngestionModelError(ValueError):
    """Raised when an ingestion domain contract is invalid."""


@dataclass(frozen=True, slots=True)
class DocumentSection:
    """Represent one ordered logical section of an ingestion document."""

    position: int
    content: str
    heading: str | None = None
    level: int | None = None

    def __post_init__(self) -> None:
        if self.position < 1:
            raise IngestionModelError(
                "section position must be greater than zero",
            )

        if not isinstance(self.content, str):
            raise TypeError("section content must be a string")

        normalized_heading = _normalize_optional_text(
            self.heading,
            field_name="section heading",
        )

        if self.level is not None and not 1 <= self.level <= 6:
            raise IngestionModelError(
                "section level must be between 1 and 6",
            )

        if normalized_heading is None and self.level is not None:
            raise IngestionModelError(
                "section level requires a heading",
            )

        object.__setattr__(self, "heading", normalized_heading)


@dataclass(frozen=True, slots=True)
class DocumentStatistics:
    """Contain deterministic measurements produced by ingestion stages."""

    character_count: int
    byte_count: int
    token_count: int | None = None
    section_count: int = 0

    def __post_init__(self) -> None:
        _require_non_negative(
            self.character_count,
            field_name="character_count",
        )
        _require_non_negative(
            self.byte_count,
            field_name="byte_count",
        )
        _require_non_negative(
            self.section_count,
            field_name="section_count",
        )

        if self.token_count is not None:
            _require_non_negative(
                self.token_count,
                field_name="token_count",
            )


@dataclass(frozen=True, slots=True)
class IngestionDocument:
    """Represent one immutable document crossing ingestion stage boundaries."""

    identity: str
    source_path: PurePosixPath
    content: str
    media_type: str
    title: str | None = None
    sections: tuple[DocumentSection, ...] = ()
    metadata: DocumentMetadata = field(
        default_factory=lambda: _EMPTY_METADATA,
    )
    statistics: DocumentStatistics | None = None

    def __post_init__(self) -> None:
        normalized_identity = _require_text(
            self.identity,
            field_name="document identity",
        )
        normalized_path = _normalize_source_path(self.source_path)
        normalized_media_type = _require_text(
            self.media_type,
            field_name="document media_type",
        ).casefold()
        normalized_title = _normalize_optional_text(
            self.title,
            field_name="document title",
        )

        if not isinstance(self.content, str):
            raise TypeError("document content must be a string")

        normalized_sections = _normalize_sections(self.sections)
        immutable_metadata = _normalize_metadata(self.metadata)

        if self.statistics is not None and self.statistics.section_count != len(
            normalized_sections
        ):
            raise IngestionModelError(
                "statistics section_count must match document sections",
            )

        object.__setattr__(self, "identity", normalized_identity)
        object.__setattr__(self, "source_path", normalized_path)
        object.__setattr__(self, "media_type", normalized_media_type)
        object.__setattr__(self, "title", normalized_title)
        object.__setattr__(self, "sections", normalized_sections)
        object.__setattr__(self, "metadata", immutable_metadata)

    @property
    def suffix(self) -> str:
        """Return the normalized source suffix including its leading dot."""

        return self.source_path.suffix.casefold()

    def with_content(
        self,
        content: str,
        *,
        media_type: str | None = None,
        title: str | None = None,
        sections: tuple[DocumentSection, ...] = (),
        statistics: DocumentStatistics | None = None,
    ) -> IngestionDocument:
        """Return a new document after an isolated content transformation."""

        return IngestionDocument(
            identity=self.identity,
            source_path=self.source_path,
            content=content,
            media_type=self.media_type if media_type is None else media_type,
            title=self.title if title is None else title,
            sections=sections,
            metadata=self.metadata,
            statistics=statistics,
        )


def _normalize_source_path(path: PurePosixPath) -> PurePosixPath:
    if not isinstance(path, PurePosixPath):
        raise TypeError("document source_path must be a PurePosixPath")

    if path.is_absolute():
        raise IngestionModelError(
            "document source_path must be relative",
        )

    if not path.parts:
        raise IngestionModelError(
            "document source_path must identify a file",
        )

    if ".." in path.parts:
        raise IngestionModelError(
            "document source_path must not escape its project boundary",
        )

    if path.name in {"", ".", ".."}:
        raise IngestionModelError(
            "document source_path must identify a file",
        )

    return PurePosixPath(path.as_posix())


def _normalize_sections(
    sections: tuple[DocumentSection, ...],
) -> tuple[DocumentSection, ...]:
    if not isinstance(sections, tuple):
        raise TypeError("document sections must be a tuple")

    expected_positions = tuple(range(1, len(sections) + 1))
    actual_positions = tuple(section.position for section in sections)

    if actual_positions != expected_positions:
        raise IngestionModelError(
            "document section positions must be contiguous and ordered",
        )

    return sections


def _normalize_metadata(
    metadata: DocumentMetadata,
) -> DocumentMetadata:
    if not isinstance(metadata, Mapping):
        raise TypeError("document metadata must be a mapping")

    normalized: dict[str, MetadataValue] = {}

    for raw_key, value in metadata.items():
        key = _require_text(
            raw_key,
            field_name="metadata key",
        )

        if key in normalized:
            raise IngestionModelError(
                f"duplicate normalized metadata key: {key}",
            )

        if not isinstance(value, (str, int, float, bool, type(None))):
            raise TypeError(
                "metadata values must be scalar JSON-compatible values",
            )

        normalized[key] = value

    return MappingProxyType(normalized)


def _require_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")

    normalized = value.strip()

    if not normalized:
        raise IngestionModelError(
            f"{field_name} must not be empty",
        )

    return normalized


def _normalize_optional_text(
    value: str | None,
    *,
    field_name: str,
) -> str | None:
    if value is None:
        return None

    return _require_text(value, field_name=field_name)


def _require_non_negative(value: int, *, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")

    if value < 0:
        raise IngestionModelError(
            f"{field_name} must not be negative",
        )
