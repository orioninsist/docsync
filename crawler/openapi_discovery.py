"""Deterministic OpenAPI and Swagger discovery from documentation HTML."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup


class OpenApiKind(StrEnum):
    """Supported API specification and documentation kinds."""

    OPENAPI_JSON = "openapi_json"
    OPENAPI_YAML = "openapi_yaml"
    SWAGGER_JSON = "swagger_json"
    SWAGGER_YAML = "swagger_yaml"
    API_DOCS = "api_docs"
    SWAGGER_UI = "swagger_ui"
    REDOC = "redoc"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class OpenApiCandidate:
    """One normalized OpenAPI or Swagger candidate."""

    url: str
    kind: OpenApiKind
    confidence: int
    source: str


@dataclass(frozen=True, slots=True)
class OpenApiDiscoveryResult:
    """Immutable OpenAPI discovery result."""

    candidates: tuple[OpenApiCandidate, ...]

    @property
    def primary(self) -> OpenApiCandidate | None:
        """Return the strongest deterministic candidate."""

        return self.candidates[0] if self.candidates else None


@dataclass(frozen=True, slots=True)
class _OpenApiPattern:
    pattern: re.Pattern[str]
    kind: OpenApiKind
    confidence: int


class OpenApiDiscovery:
    """Discover OpenAPI, Swagger, Swagger UI, and ReDoc resources."""

    _URL_ATTRIBUTE_NAMES: ClassVar[tuple[str, ...]] = (
        "href",
        "src",
        "data-url",
        "data-spec-url",
        "data-openapi",
        "data-swagger",
    )

    _SPEC_PATTERNS: ClassVar[tuple[_OpenApiPattern, ...]] = (
        _OpenApiPattern(
            pattern=re.compile(
                r"(?:^|/)openapi\.json(?:$|[?#])",
                re.IGNORECASE,
            ),
            kind=OpenApiKind.OPENAPI_JSON,
            confidence=100,
        ),
        _OpenApiPattern(
            pattern=re.compile(
                r"(?:^|/)openapi\.(?:yaml|yml)(?:$|[?#])",
                re.IGNORECASE,
            ),
            kind=OpenApiKind.OPENAPI_YAML,
            confidence=100,
        ),
        _OpenApiPattern(
            pattern=re.compile(
                r"(?:^|/)swagger\.json(?:$|[?#])",
                re.IGNORECASE,
            ),
            kind=OpenApiKind.SWAGGER_JSON,
            confidence=100,
        ),
        _OpenApiPattern(
            pattern=re.compile(
                r"(?:^|/)swagger\.(?:yaml|yml)(?:$|[?#])",
                re.IGNORECASE,
            ),
            kind=OpenApiKind.SWAGGER_YAML,
            confidence=100,
        ),
        _OpenApiPattern(
            pattern=re.compile(
                r"(?:^|/)(?:v[23]/)?api-docs(?:$|[/?#])",
                re.IGNORECASE,
            ),
            kind=OpenApiKind.API_DOCS,
            confidence=95,
        ),
        _OpenApiPattern(
            pattern=re.compile(
                r"(?:^|/)(?:swagger-ui|swagger)(?:/|$|[?#])",
                re.IGNORECASE,
            ),
            kind=OpenApiKind.SWAGGER_UI,
            confidence=80,
        ),
        _OpenApiPattern(
            pattern=re.compile(
                r"(?:^|/)redoc(?:/|$|[?#])",
                re.IGNORECASE,
            ),
            kind=OpenApiKind.REDOC,
            confidence=80,
        ),
    )

    _INLINE_URL_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"""(?P<quote>["'])
        (?P<url>
            (?:https?://|/|\./|\.\./)
            [^"'<>\\\s]*
            (?:
                openapi\.(?:json|yaml|yml)
                |swagger\.(?:json|yaml|yml)
                |(?:v[23]/)?api-docs
                |swagger-ui
                |redoc
            )
            [^"'<>\\\s]*
        )
        (?P=quote)""",
        re.IGNORECASE | re.VERBOSE,
    )

    _SWAGGER_UI_MARKERS: ClassVar[tuple[str, ...]] = (
        "swagger-ui",
        "swaggerui",
        "swagger-ui-bundle",
        "swaggerinitializer",
    )

    _REDOC_MARKERS: ClassVar[tuple[str, ...]] = (
        "<redoc",
        "redoc.init",
        "redoc.standalone",
        "redoc-container",
    )

    def discover(
        self,
        *,
        html: str,
        base_url: str,
    ) -> OpenApiDiscoveryResult:
        """Discover and rank API specification candidates."""

        if not html.strip() or not self._is_http_url(base_url):
            return OpenApiDiscoveryResult(candidates=())

        soup = BeautifulSoup(html, "html.parser")
        candidates: list[OpenApiCandidate] = []

        candidates.extend(self._discover_element_urls(soup, base_url))
        candidates.extend(self._discover_inline_urls(html, base_url))
        candidates.extend(self._discover_documentation_markers(html, base_url))

        return OpenApiDiscoveryResult(
            candidates=self._deduplicate_and_rank(candidates),
        )

    def _discover_element_urls(
        self,
        soup: BeautifulSoup,
        base_url: str,
    ) -> list[OpenApiCandidate]:
        candidates: list[OpenApiCandidate] = []

        for element in soup.find_all(True):
            for attribute_name in self._URL_ATTRIBUTE_NAMES:
                value = element.get(attribute_name)

                if not isinstance(value, str):
                    continue

                candidate = self._candidate_from_reference(
                    reference=value,
                    base_url=base_url,
                    source=f"{element.name}[{attribute_name}]",
                )

                if candidate is not None:
                    candidates.append(candidate)

        return candidates

    def _discover_inline_urls(
        self,
        html: str,
        base_url: str,
    ) -> list[OpenApiCandidate]:
        candidates: list[OpenApiCandidate] = []

        for match in self._INLINE_URL_PATTERN.finditer(html):
            candidate = self._candidate_from_reference(
                reference=match.group("url"),
                base_url=base_url,
                source="inline_script",
            )

            if candidate is not None:
                candidates.append(candidate)

        return candidates

    def _discover_documentation_markers(
        self,
        html: str,
        base_url: str,
    ) -> list[OpenApiCandidate]:
        searchable_html = html.casefold()
        candidates: list[OpenApiCandidate] = []

        if any(marker in searchable_html for marker in self._SWAGGER_UI_MARKERS):
            candidates.append(
                OpenApiCandidate(
                    url=base_url,
                    kind=OpenApiKind.SWAGGER_UI,
                    confidence=65,
                    source="html_marker",
                )
            )

        if any(marker in searchable_html for marker in self._REDOC_MARKERS):
            candidates.append(
                OpenApiCandidate(
                    url=base_url,
                    kind=OpenApiKind.REDOC,
                    confidence=65,
                    source="html_marker",
                )
            )

        return candidates

    def _candidate_from_reference(
        self,
        *,
        reference: str,
        base_url: str,
        source: str,
    ) -> OpenApiCandidate | None:
        normalized_reference = reference.strip()

        if not normalized_reference:
            return None

        absolute_url = self._normalize_url(
            urljoin(base_url, normalized_reference),
        )

        if absolute_url is None:
            return None

        for spec_pattern in self._SPEC_PATTERNS:
            if spec_pattern.pattern.search(absolute_url):
                return OpenApiCandidate(
                    url=absolute_url,
                    kind=spec_pattern.kind,
                    confidence=spec_pattern.confidence,
                    source=source,
                )

        return None

    def _deduplicate_and_rank(
        self,
        candidates: list[OpenApiCandidate],
    ) -> tuple[OpenApiCandidate, ...]:
        strongest_by_key: dict[
            tuple[str, OpenApiKind],
            OpenApiCandidate,
        ] = {}

        for candidate in candidates:
            key = (candidate.url, candidate.kind)
            existing = strongest_by_key.get(key)

            if existing is None or candidate.confidence > existing.confidence:
                strongest_by_key[key] = candidate

        return tuple(
            sorted(
                strongest_by_key.values(),
                key=lambda candidate: (
                    -candidate.confidence,
                    candidate.kind.value,
                    candidate.url,
                    candidate.source,
                ),
            )
        )

    def _normalize_url(self, url: str) -> str | None:
        parsed_url = urlsplit(url)

        if parsed_url.scheme.casefold() not in {"http", "https"}:
            return None

        if not parsed_url.netloc:
            return None

        return urlunsplit(
            (
                parsed_url.scheme.casefold(),
                parsed_url.netloc.casefold(),
                parsed_url.path,
                parsed_url.query,
                "",
            )
        )

    def _is_http_url(self, url: str) -> bool:
        parsed_url = urlsplit(url)

        return parsed_url.scheme.casefold() in {"http", "https"} and bool(
            parsed_url.netloc
        )
