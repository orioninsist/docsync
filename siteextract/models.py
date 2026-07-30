"""Immutable domain models for extracted website commerce data."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType


def _empty_attributes() -> Mapping[str, str]:
    return MappingProxyType({})


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    return normalized or None


def _normalize_unique_texts(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized_values: list[str] = []
    seen: set[str] = set()

    for value in values:
        normalized = value.strip()

        if not normalized:
            continue

        comparison_key = normalized.casefold()

        if comparison_key in seen:
            continue

        seen.add(comparison_key)
        normalized_values.append(normalized)

    return tuple(normalized_values)


class PageKind(StrEnum):
    """Supported source page classifications."""

    PRODUCT = "product"
    PRODUCT_LIST = "product_list"
    UNKNOWN = "unknown"


class Availability(StrEnum):
    """Normalized product availability values."""

    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    PREORDER = "preorder"
    LIMITED = "limited"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Money:
    """Represent one normalized monetary value."""

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        normalized_currency = self.currency.strip().upper()

        if not normalized_currency:
            raise ValueError("currency must not be empty")

        if len(normalized_currency) != 3:
            raise ValueError("currency must be a three-letter ISO code")

        object.__setattr__(self, "currency", normalized_currency)


@dataclass(frozen=True, slots=True)
class ProductImage:
    """Represent one product image and its optional metadata."""

    url: str
    alt_text: str | None = None
    width: int | None = None
    height: int | None = None

    def __post_init__(self) -> None:
        normalized_url = self.url.strip()

        if not normalized_url:
            raise ValueError("image URL must not be empty")

        if self.width is not None and self.width < 1:
            raise ValueError("image width must be positive")

        if self.height is not None and self.height < 1:
            raise ValueError("image height must be positive")

        object.__setattr__(self, "url", normalized_url)
        object.__setattr__(self, "alt_text", _normalize_optional_text(self.alt_text))


@dataclass(frozen=True, slots=True)
class ProductVariant:
    """Represent one purchasable product variant."""

    name: str
    value: str
    sku: str | None = None
    price: Money | None = None
    availability: Availability = Availability.UNKNOWN

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()
        normalized_value = self.value.strip()

        if not normalized_name:
            raise ValueError("variant name must not be empty")

        if not normalized_value:
            raise ValueError("variant value must not be empty")

        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "value", normalized_value)
        object.__setattr__(self, "sku", _normalize_optional_text(self.sku))


@dataclass(frozen=True, slots=True)
class Rating:
    """Represent a normalized aggregate product rating."""

    value: Decimal
    scale: Decimal = Decimal("5")
    review_count: int | None = None

    def __post_init__(self) -> None:
        if self.scale <= 0:
            raise ValueError("rating scale must be positive")

        if self.value < 0 or self.value > self.scale:
            raise ValueError("rating value must be within the rating scale")

        if self.review_count is not None and self.review_count < 0:
            raise ValueError("review count must not be negative")


@dataclass(frozen=True, slots=True)
class Product:
    """Represent one normalized product independent of its source website."""

    name: str
    url: str
    description: str | None = None
    price: Money | None = None
    original_price: Money | None = None
    brand: str | None = None
    seller: str | None = None
    category: str | None = None
    sku: str | None = None
    availability: Availability = Availability.UNKNOWN
    rating: Rating | None = None
    images: tuple[ProductImage, ...] = ()
    tags: tuple[str, ...] = ()
    variants: tuple[ProductVariant, ...] = ()
    attributes: Mapping[str, str] = field(default_factory=_empty_attributes)

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()
        normalized_url = self.url.strip()

        if not normalized_name:
            raise ValueError("product name must not be empty")

        if not normalized_url:
            raise ValueError("product URL must not be empty")

        normalized_attributes: dict[str, str] = {
            key.strip(): value.strip()
            for key, value in self.attributes.items()
            if key.strip() and value.strip()
        }

        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "url", normalized_url)
        object.__setattr__(
            self,
            "description",
            _normalize_optional_text(self.description),
        )
        object.__setattr__(self, "brand", _normalize_optional_text(self.brand))
        object.__setattr__(self, "seller", _normalize_optional_text(self.seller))
        object.__setattr__(self, "category", _normalize_optional_text(self.category))
        object.__setattr__(self, "sku", _normalize_optional_text(self.sku))
        object.__setattr__(self, "tags", _normalize_unique_texts(self.tags))
        object.__setattr__(
            self,
            "attributes",
            MappingProxyType(normalized_attributes),
        )


@dataclass(frozen=True, slots=True)
class ProductReference:
    """Represent a product discovered before its detail page is fetched."""

    url: str
    name: str | None = None
    position: int | None = None
    source: str | None = None

    def __post_init__(self) -> None:
        normalized_url = self.url.strip()

        if not normalized_url:
            raise ValueError("product reference URL must not be empty")

        if self.position is not None and self.position < 1:
            raise ValueError("product reference position must be positive")

        object.__setattr__(self, "url", normalized_url)
        object.__setattr__(self, "name", _normalize_optional_text(self.name))
        object.__setattr__(self, "source", _normalize_optional_text(self.source))


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Represent the normalized result produced for one source page."""

    source_url: str
    final_url: str
    page_kind: PageKind
    products: tuple[Product, ...] = ()
    references: tuple[ProductReference, ...] = ()
    platform: str | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        normalized_source_url = self.source_url.strip()
        normalized_final_url = self.final_url.strip()

        if not normalized_source_url:
            raise ValueError("source URL must not be empty")

        if not normalized_final_url:
            raise ValueError("final URL must not be empty")

        object.__setattr__(self, "source_url", normalized_source_url)
        object.__setattr__(self, "final_url", normalized_final_url)
        object.__setattr__(self, "platform", _normalize_optional_text(self.platform))
        object.__setattr__(self, "warnings", _normalize_unique_texts(self.warnings))
