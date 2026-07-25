"""Semantic similarity boundary for ingestion content.

This module defines immutable comparison contracts, an injectable embedding
boundary, and deterministic cosine-similarity calculation. It performs no
filesystem access, document conversion, content cleaning, token calculation,
routing, persistence, merge planning, or pipeline orchestration.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import fsum, isfinite, sqrt
from typing import Protocol, TypeAlias

from pipeline.ingestion.config import RoutingConfig


EmbeddingVector: TypeAlias = tuple[float, ...]


class SemanticSimilarityError(ValueError):
    """Base error raised for invalid semantic-similarity operations."""


class EmptyEmbeddingError(SemanticSimilarityError):
    """Raised when an embedding vector contains no dimensions."""


class EmbeddingDimensionError(SemanticSimilarityError):
    """Raised when compared embedding vectors have different dimensions."""


class ZeroMagnitudeEmbeddingError(SemanticSimilarityError):
    """Raised when cosine similarity is undefined for a zero vector."""


class TextEmbedder(Protocol):
    """Produce one numeric embedding vector for supplied text."""

    def embed(self, content: str) -> Sequence[float]:
        """Return an embedding vector for content."""
        ...


@dataclass(frozen=True, slots=True)
class SemanticComparisonRequest:
    """Describe one semantic comparison without runtime dependencies."""

    left_content: str
    right_content: str

    def __post_init__(self) -> None:
        """Validate and normalize comparison content."""

        normalized_left = self.left_content.strip()
        normalized_right = self.right_content.strip()

        if not normalized_left:
            raise SemanticSimilarityError("left_content must not be empty")

        if not normalized_right:
            raise SemanticSimilarityError("right_content must not be empty")

        object.__setattr__(self, "left_content", normalized_left)
        object.__setattr__(self, "right_content", normalized_right)


@dataclass(frozen=True, slots=True)
class SemanticComparisonResult:
    """Contain the deterministic outcome of one semantic comparison."""

    similarity: float
    threshold: float

    def __post_init__(self) -> None:
        """Validate similarity result invariants."""

        normalized_similarity = _validate_unit_interval(
            self.similarity,
            field_name="similarity",
        )
        normalized_threshold = _validate_unit_interval(
            self.threshold,
            field_name="threshold",
        )

        object.__setattr__(self, "similarity", normalized_similarity)
        object.__setattr__(self, "threshold", normalized_threshold)

    @property
    def is_similar(self) -> bool:
        """Return whether similarity satisfies the configured threshold."""

        return self.similarity >= self.threshold


@dataclass(frozen=True, slots=True)
class SemanticSimilarityService:
    """Compare text through an injected embedding implementation."""

    embedder: TextEmbedder
    routing: RoutingConfig

    def compare(
        self,
        request: SemanticComparisonRequest,
    ) -> SemanticComparisonResult:
        """Embed request content and return its cosine similarity."""

        left_embedding = normalize_embedding(
            self.embedder.embed(request.left_content),
            field_name="left_embedding",
        )
        right_embedding = normalize_embedding(
            self.embedder.embed(request.right_content),
            field_name="right_embedding",
        )

        similarity = cosine_similarity(
            left_embedding,
            right_embedding,
        )

        return SemanticComparisonResult(
            similarity=similarity,
            threshold=self.routing.similarity_threshold,
        )


def normalize_embedding(
    embedding: object,
    *,
    field_name: str = "embedding",
) -> EmbeddingVector:
    """Return an immutable, finite floating-point embedding vector."""

    if isinstance(embedding, (str, bytes, bytearray)):
        raise TypeError(f"{field_name} must be a numeric sequence")

    if not isinstance(embedding, Sequence):
        raise TypeError(f"{field_name} must be a sequence")

    normalized_values: list[float] = []

    for index, value in enumerate(embedding):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(
                f"{field_name}[{index}] must be a number",
            )

        normalized_value = float(value)

        if not isfinite(normalized_value):
            raise SemanticSimilarityError(
                f"{field_name}[{index}] must be finite",
            )

        normalized_values.append(normalized_value)

    if not normalized_values:
        raise EmptyEmbeddingError(f"{field_name} must not be empty")

    return tuple(normalized_values)


def cosine_similarity(
    left_embedding: Sequence[float],
    right_embedding: Sequence[float],
) -> float:
    """Return deterministic cosine similarity normalized to ``0.0..1.0``.

    Raw cosine similarity ranges from ``-1.0`` to ``1.0``. The returned value
    is transformed into the unit interval so it can be compared directly with
    ``RoutingConfig.similarity_threshold``.
    """

    left = normalize_embedding(
        left_embedding,
        field_name="left_embedding",
    )
    right = normalize_embedding(
        right_embedding,
        field_name="right_embedding",
    )

    if len(left) != len(right):
        raise EmbeddingDimensionError(
            f"embedding dimensions must match: {len(left)} != {len(right)}",
        )

    dot_product = fsum(
        left_value * right_value
        for left_value, right_value in zip(left, right, strict=True)
    )
    left_magnitude = sqrt(
        fsum(value * value for value in left),
    )
    right_magnitude = sqrt(
        fsum(value * value for value in right),
    )

    if left_magnitude == 0.0:
        raise ZeroMagnitudeEmbeddingError(
            "left_embedding must not be a zero vector",
        )

    if right_magnitude == 0.0:
        raise ZeroMagnitudeEmbeddingError(
            "right_embedding must not be a zero vector",
        )

    raw_similarity = dot_product / (left_magnitude * right_magnitude)
    bounded_similarity = max(-1.0, min(1.0, raw_similarity))
    normalized_similarity = (bounded_similarity + 1.0) / 2.0

    return max(0.0, min(1.0, normalized_similarity))


def _validate_unit_interval(
    value: object,
    *,
    field_name: str,
) -> float:
    """Validate and normalize one finite number in the unit interval."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number")

    normalized_value = float(value)

    if not isfinite(normalized_value):
        raise SemanticSimilarityError(
            f"{field_name} must be finite",
        )

    if not 0.0 <= normalized_value <= 1.0:
        raise SemanticSimilarityError(
            f"{field_name} must be between 0.0 and 1.0",
        )

    return normalized_value


__all__ = [
    "EmbeddingDimensionError",
    "EmbeddingVector",
    "EmptyEmbeddingError",
    "SemanticComparisonRequest",
    "SemanticComparisonResult",
    "SemanticSimilarityError",
    "SemanticSimilarityService",
    "TextEmbedder",
    "ZeroMagnitudeEmbeddingError",
    "cosine_similarity",
    "normalize_embedding",
]
