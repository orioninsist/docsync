"""Deterministic semantic-routing rules for ingestion documents.

This module classifies immutable ingestion documents, applies explicit routing
priorities, and optionally discovers semantically related sibling documents.
It performs no filesystem access, conversion, cleaning, token calculation,
persistence, merge planning, or pipeline orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Final

from pipeline.ingestion.config import RoutingConfig
from pipeline.ingestion.model import IngestionDocument
from pipeline.ingestion.semantic_similarity import (
    SemanticComparisonRequest,
    SemanticSimilarityService,
)


_README_FILENAMES: Final[frozenset[str]] = frozenset(
    {
        "readme",
        "readme.md",
        "readme.markdown",
        "readme.rst",
        "readme.txt",
    },
)

_INSTALLATION_TERMS: Final[tuple[str, ...]] = (
    "getting started",
    "installation",
    "installing",
    "setup",
)

_FAQ_TERMS: Final[tuple[str, ...]] = (
    "faq",
    "frequently asked questions",
)

_TROUBLESHOOTING_TERMS: Final[tuple[str, ...]] = (
    "debugging",
    "errors",
    "known issues",
    "troubleshooting",
)


class SemanticRoutingError(ValueError):
    """Raised when a semantic-routing contract is invalid."""


class RoutingCategory(str, Enum):
    """Identify one deterministic ingestion-document route."""

    README = "readme"
    INSTALLATION = "installation"
    FAQ = "faq"
    TROUBLESHOOTING = "troubleshooting"
    GENERAL = "general"


@dataclass(frozen=True, slots=True)
class SemanticRoutingRequest:
    """Describe one routing operation without runtime state."""

    document: IngestionDocument
    candidates: tuple[IngestionDocument, ...] = ()

    def __post_init__(self) -> None:
        """Validate routing input and candidate uniqueness."""

        if not isinstance(self.document, IngestionDocument):
            raise TypeError("document must be an IngestionDocument")

        if not isinstance(self.candidates, tuple):
            raise TypeError("candidates must be a tuple")

        candidate_identities: set[str] = set()

        for candidate in self.candidates:
            if not isinstance(candidate, IngestionDocument):
                raise TypeError(
                    "candidate entries must be IngestionDocument instances",
                )

            if candidate.identity == self.document.identity:
                raise SemanticRoutingError(
                    "candidates must not contain the routed document",
                )

            if candidate.identity in candidate_identities:
                raise SemanticRoutingError(
                    f"duplicate candidate identity: {candidate.identity}",
                )

            candidate_identities.add(candidate.identity)


@dataclass(frozen=True, slots=True)
class SemanticRoutingResult:
    """Contain one deterministic routing decision."""

    document_identity: str
    category: RoutingCategory
    route_key: str
    priority: int
    isolated: bool
    related_document_identities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate routing-result invariants."""

        normalized_identity = _require_text(
            self.document_identity,
            field_name="document_identity",
        )
        normalized_route_key = _require_text(
            self.route_key,
            field_name="route_key",
        )

        if not isinstance(self.category, RoutingCategory):
            raise TypeError("category must be a RoutingCategory")

        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise TypeError("priority must be an integer")

        if self.priority < 1:
            raise SemanticRoutingError(
                "priority must be greater than zero",
            )

        if not isinstance(self.isolated, bool):
            raise TypeError("isolated must be a boolean")

        if not isinstance(self.related_document_identities, tuple):
            raise TypeError(
                "related_document_identities must be a tuple",
            )

        normalized_related = _normalize_related_identities(
            self.related_document_identities,
            document_identity=normalized_identity,
        )

        object.__setattr__(self, "document_identity", normalized_identity)
        object.__setattr__(self, "route_key", normalized_route_key)
        object.__setattr__(
            self,
            "related_document_identities",
            normalized_related,
        )


@dataclass(frozen=True, slots=True)
class SemanticRoutingService:
    """Apply deterministic routing and optional semantic sibling discovery."""

    similarity_service: SemanticSimilarityService
    routing: RoutingConfig

    def __post_init__(self) -> None:
        """Validate injected routing dependencies."""

        if not isinstance(
            self.similarity_service,
            SemanticSimilarityService,
        ):
            raise TypeError(
                "similarity_service must be a SemanticSimilarityService",
            )

        if not isinstance(self.routing, RoutingConfig):
            raise TypeError("routing must be a RoutingConfig")

    def route(
        self,
        request: SemanticRoutingRequest,
    ) -> SemanticRoutingResult:
        """Classify a document and discover related sibling documents."""

        if not isinstance(request, SemanticRoutingRequest):
            raise TypeError(
                "request must be a SemanticRoutingRequest",
            )

        category = classify_document(request.document)
        related_identities = self._find_related_siblings(request)

        return SemanticRoutingResult(
            document_identity=request.document.identity,
            category=category,
            route_key=category.value,
            priority=_resolve_priority(category, self.routing),
            isolated=_resolve_isolation(category, self.routing),
            related_document_identities=related_identities,
        )

    def _find_related_siblings(
        self,
        request: SemanticRoutingRequest,
    ) -> tuple[str, ...]:
        if not self.routing.prefer_sibling_documents:
            return ()

        source_parent = request.document.source_path.parent
        related: list[str] = []

        for candidate in sorted(
            request.candidates,
            key=lambda item: item.identity,
        ):
            if candidate.source_path.parent != source_parent:
                continue

            comparison = self.similarity_service.compare(
                SemanticComparisonRequest(
                    left_content=request.document.content,
                    right_content=candidate.content,
                ),
            )

            if comparison.is_similar:
                related.append(candidate.identity)

        return tuple(related)


def classify_document(document: IngestionDocument) -> RoutingCategory:
    """Return a deterministic category from immutable document content."""

    if not isinstance(document, IngestionDocument):
        raise TypeError("document must be an IngestionDocument")

    normalized_filename = document.source_path.name.casefold()

    if normalized_filename in _README_FILENAMES:
        return RoutingCategory.README

    searchable_text = _build_searchable_text(document)

    if _contains_term(searchable_text, _INSTALLATION_TERMS):
        return RoutingCategory.INSTALLATION

    if _contains_term(searchable_text, _FAQ_TERMS):
        return RoutingCategory.FAQ

    if _contains_term(searchable_text, _TROUBLESHOOTING_TERMS):
        return RoutingCategory.TROUBLESHOOTING

    return RoutingCategory.GENERAL


def _build_searchable_text(document: IngestionDocument) -> str:
    title = document.title or ""
    path_text = _path_without_suffix(document.source_path)
    section_headings = " ".join(
        section.heading for section in document.sections if section.heading is not None
    )
    content_prefix = document.content[:4_000]

    return " ".join(
        (
            title,
            path_text,
            section_headings,
            content_prefix,
        ),
    ).casefold()


def _path_without_suffix(path: PurePosixPath) -> str:
    return " ".join(
        part.replace("_", " ").replace("-", " ") for part in path.with_suffix("").parts
    )


def _contains_term(
    searchable_text: str,
    terms: tuple[str, ...],
) -> bool:
    return any(term in searchable_text for term in terms)


def _resolve_priority(
    category: RoutingCategory,
    routing: RoutingConfig,
) -> int:
    if category is RoutingCategory.README:
        return 1 if routing.readme_first else 5

    priority_by_category = {
        RoutingCategory.INSTALLATION: 2,
        RoutingCategory.FAQ: 3,
        RoutingCategory.TROUBLESHOOTING: 4,
        RoutingCategory.GENERAL: 5,
    }

    return priority_by_category[category]


def _resolve_isolation(
    category: RoutingCategory,
    routing: RoutingConfig,
) -> bool:
    if category is RoutingCategory.INSTALLATION:
        return routing.isolate_installation

    if category in {
        RoutingCategory.FAQ,
        RoutingCategory.TROUBLESHOOTING,
    }:
        return routing.isolate_faq_and_troubleshooting

    return False


def _normalize_related_identities(
    identities: tuple[str, ...],
    *,
    document_identity: str,
) -> tuple[str, ...]:
    normalized: set[str] = set()

    for identity in identities:
        candidate = _require_text(
            identity,
            field_name="related document identity",
        )

        if candidate == document_identity:
            raise SemanticRoutingError(
                "a document must not be related to itself",
            )

        normalized.add(candidate)

    return tuple(sorted(normalized))


def _require_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")

    normalized = value.strip()

    if not normalized:
        raise SemanticRoutingError(
            f"{field_name} must not be empty",
        )

    return normalized


__all__ = [
    "RoutingCategory",
    "SemanticRoutingError",
    "SemanticRoutingRequest",
    "SemanticRoutingResult",
    "SemanticRoutingService",
    "classify_document",
]
