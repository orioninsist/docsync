"""Independent format-conversion boundary for document ingestion.

This module defines immutable conversion contracts, the converter protocol,
suffix-based converter registration, and deterministic converter dispatch.

It performs no filesystem access, document discovery, content cleaning,
normalization, persistence, semantic analysis, merge planning, or pipeline
orchestration.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Final, Protocol, runtime_checkable

_EMPTY_METADATA: Final[Mapping[str, str]] = MappingProxyType({})


class ConversionError(RuntimeError):
    """Base exception for conversion-boundary failures."""


class ConversionContractError(ConversionError, ValueError):
    """Raised when a conversion request or result is invalid."""


class UnsupportedConversionError(ConversionError):
    """Raised when no converter is registered for a source suffix."""


class DuplicateConverterError(ConversionError):
    """Raised when more than one converter claims the same suffix."""


class ConverterExecutionError(ConversionError):
    """Raised when a converter fails while processing a valid request."""


@dataclass(frozen=True, slots=True)
class ConversionRequest:
    """Contain immutable input supplied to one document converter."""

    source_path: PurePosixPath
    content: bytes
    media_type: str | None = None

    def __post_init__(self) -> None:
        normalized_path = _normalize_source_path(self.source_path)
        normalized_media_type = _normalize_optional_text(
            self.media_type,
            field_name="conversion request media_type",
        )

        object.__setattr__(self, "source_path", normalized_path)
        object.__setattr__(self, "media_type", normalized_media_type)

    @property
    def suffix(self) -> str:
        """Return the normalized source suffix including its leading dot."""
        return _normalize_suffix(self.source_path.suffix)


@dataclass(frozen=True, slots=True)
class ConversionResult:
    """Contain immutable text produced by one document converter."""

    content: str
    media_type: str
    title: str | None = None
    metadata: Mapping[str, str] = field(
        default_factory=lambda: _EMPTY_METADATA,
    )

    def __post_init__(self) -> None:
        normalized_media_type = _require_text(
            self.media_type,
            field_name="conversion result media_type",
        ).casefold()
        normalized_title = _normalize_optional_text(
            self.title,
            field_name="conversion result title",
        )
        normalized_metadata = _normalize_metadata(self.metadata)

        object.__setattr__(self, "media_type", normalized_media_type)
        object.__setattr__(self, "title", normalized_title)
        object.__setattr__(self, "metadata", normalized_metadata)


@runtime_checkable
class DocumentConverter(Protocol):
    """Define the plug-in contract implemented by format converters."""

    @property
    def supported_suffixes(self) -> tuple[str, ...]:
        """Return normalized suffixes accepted by this converter."""
        ...

    def convert(self, request: ConversionRequest) -> ConversionResult:
        """Convert one immutable request into one immutable text result."""
        ...


@dataclass(frozen=True, slots=True)
class ConverterRegistry:
    """Resolve document converters deterministically by source suffix."""

    _converters_by_suffix: Mapping[str, DocumentConverter]

    def __post_init__(self) -> None:
        normalized_entries: dict[str, DocumentConverter] = {}

        for raw_suffix, converter in self._converters_by_suffix.items():
            suffix = _normalize_suffix(raw_suffix)
            _validate_converter(converter)

            if suffix in normalized_entries:
                raise DuplicateConverterError(
                    f"duplicate converter registration for suffix: {suffix}",
                )

            normalized_entries[suffix] = converter

        object.__setattr__(
            self,
            "_converters_by_suffix",
            MappingProxyType(normalized_entries),
        )

    @classmethod
    def from_converters(
        cls,
        converters: Iterable[DocumentConverter],
    ) -> ConverterRegistry:
        """Build a registry from independent converter plug-ins."""
        entries: dict[str, DocumentConverter] = {}

        for converter in converters:
            _validate_converter(converter)
            suffixes = _normalize_supported_suffixes(
                converter.supported_suffixes,
            )

            for suffix in suffixes:
                if suffix in entries:
                    raise DuplicateConverterError(
                        f"duplicate converter registration for suffix: {suffix}",
                    )

                entries[suffix] = converter

        return cls(entries)

    @property
    def supported_suffixes(self) -> tuple[str, ...]:
        """Return all registered suffixes in deterministic order."""
        return tuple(sorted(self._converters_by_suffix))

    def supports(self, suffix: str) -> bool:
        """Return whether a converter is registered for the suffix."""
        return _normalize_suffix(suffix) in self._converters_by_suffix

    def resolve(self, suffix: str) -> DocumentConverter:
        """Return the converter registered for the suffix."""
        normalized_suffix = _normalize_suffix(suffix)

        try:
            return self._converters_by_suffix[normalized_suffix]
        except KeyError as error:
            raise UnsupportedConversionError(
                f"no converter registered for suffix: {normalized_suffix}",
            ) from error

    def convert(self, request: ConversionRequest) -> ConversionResult:
        """Resolve and execute the converter for one request."""
        converter = self.resolve(request.suffix)

        try:
            return converter.convert(request)
        except ConversionError:
            raise
        except Exception as error:
            message = (
                f"converter failed for {request.source_path.as_posix()}: "
                f"{type(error).__name__}: {error}"
            )
            raise ConverterExecutionError(message) from error


def convert_document(
    request: ConversionRequest,
    *,
    registry: ConverterRegistry,
) -> ConversionResult:
    """Convert one request through an explicitly supplied registry."""
    return registry.convert(request)


def _validate_converter(converter: object) -> None:
    if not isinstance(converter, DocumentConverter):
        raise TypeError(
            "converter must implement the DocumentConverter protocol",
        )


def _normalize_supported_suffixes(
    suffixes: tuple[str, ...],
) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()

    for raw_suffix in suffixes:
        suffix = _normalize_suffix(raw_suffix)

        if suffix in seen:
            raise ConversionContractError(
                f"converter declares duplicate suffix: {suffix}",
            )

        seen.add(suffix)
        normalized.append(suffix)

    if not normalized:
        raise ConversionContractError(
            "converter must support at least one suffix",
        )

    return tuple(normalized)


def _normalize_source_path(path: PurePosixPath) -> PurePosixPath:
    if path.is_absolute():
        raise ConversionContractError(
            "conversion request source_path must be relative",
        )

    if not path.parts or path.name in {"", ".", ".."}:
        raise ConversionContractError(
            "conversion request source_path must identify a file",
        )

    if ".." in path.parts:
        raise ConversionContractError(
            "conversion request source_path must not escape its boundary",
        )

    normalized = PurePosixPath(path.as_posix())

    if not normalized.suffix:
        raise ConversionContractError(
            "conversion request source_path must have a suffix",
        )

    return normalized


def _normalize_suffix(suffix: str) -> str:
    normalized = _require_text(
        suffix,
        field_name="converter suffix",
    ).casefold()

    if not normalized.startswith("."):
        normalized = f".{normalized}"

    if normalized == ".":
        raise ConversionContractError(
            "converter suffix must contain characters after the dot",
        )

    if "/" in normalized or "\\" in normalized:
        raise ConversionContractError(
            "converter suffix must not contain path separators",
        )

    return normalized


def _normalize_metadata(
    metadata: Mapping[str, str],
) -> Mapping[str, str]:
    normalized: dict[str, str] = {}

    for raw_key, raw_value in metadata.items():
        key = _require_text(
            raw_key,
            field_name="conversion metadata key",
        )
        value = _require_text(
            raw_value,
            field_name=f"conversion metadata value for {key}",
        )

        if key in normalized:
            raise ConversionContractError(
                f"duplicate normalized conversion metadata key: {key}",
            )

        normalized[key] = value

    return MappingProxyType(normalized)


def _require_text(value: str, *, field_name: str) -> str:
    normalized = value.strip()

    if not normalized:
        raise ConversionContractError(
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
