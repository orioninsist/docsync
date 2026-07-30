"""Deterministic search-index discovery from documentation HTML."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup


class SearchIndexKind(StrEnum):
    """Supported documentation search-index implementations."""

    ALGOLIA = "algolia"
    DOCSEARCH = "docsearch"
    ELASTICLUNR = "elasticlunr"
    FLEXSEARCH = "flexsearch"
    LUNR = "lunr"
    MKDOCS = "mkdocs"
    PAGEFIND = "pagefind"
    SEARCH_JSON = "search_json"
    STORK = "stork"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SearchIndexCandidate:
    """One normalized search-index candidate."""

    url: str
    kind: SearchIndexKind
    confidence: int
    source: str


@dataclass(frozen=True, slots=True)
class SearchIndexDiscoveryResult:
    """Immutable search-index discovery result."""

    candidates: tuple[SearchIndexCandidate, ...]

    @property
    def primary(self) -> SearchIndexCandidate | None:
        """Return the strongest deterministic candidate."""

        if not self.candidates:
            return None

        return self.candidates[0]


@dataclass(frozen=True, slots=True)
class _IndexPattern:
    pattern: re.Pattern[str]
    kind: SearchIndexKind
    confidence: int


class SearchIndexDiscovery:
    """Discover search-index resources referenced by one HTML document."""

    _URL_ATTRIBUTE_NAMES: ClassVar[tuple[str, ...]] = (
        "href",
        "src",
        "data-index",
        "data-search-index",
        "data-pagefind",
        "data-url",
    )

    _INDEX_PATTERNS: ClassVar[tuple[_IndexPattern, ...]] = (
        _IndexPattern(
            pattern=re.compile(
                r"(?:^|/)(?:mkdocs/)?search_index\.json(?:$|[?#])",
                re.IGNORECASE,
            ),
            kind=SearchIndexKind.MKDOCS,
            confidence=100,
        ),
        _IndexPattern(
            pattern=re.compile(
                r"(?:^|/)pagefind(?:/|$)|pagefind-entry\.json",
                re.IGNORECASE,
            ),
            kind=SearchIndexKind.PAGEFIND,
            confidence=100,
        ),
        _IndexPattern(
            pattern=re.compile(
                r"(?:^|/)(?:search[-_]?index|search)\.json(?:$|[?#])",
                re.IGNORECASE,
            ),
            kind=SearchIndexKind.SEARCH_JSON,
            confidence=95,
        ),
        _IndexPattern(
            pattern=re.compile(
                r"(?:^|/)lunr(?:[-_.][^/?#]+)?\.json(?:$|[?#])",
                re.IGNORECASE,
            ),
            kind=SearchIndexKind.LUNR,
            confidence=90,
        ),
        _IndexPattern(
            pattern=re.compile(
                r"(?:^|/)elasticlunr(?:[-_.][^/?#]+)?\.json(?:$|[?#])",
                re.IGNORECASE,
            ),
            kind=SearchIndexKind.ELASTICLUNR,
            confidence=90,
        ),
        _IndexPattern(
            pattern=re.compile(
                r"(?:^|/)flexsearch(?:[-_.][^/?#]+)?\.json(?:$|[?#])",
                re.IGNORECASE,
            ),
            kind=SearchIndexKind.FLEXSEARCH,
            confidence=85,
        ),
        _IndexPattern(
            pattern=re.compile(
                r"(?:^|/)stork(?:[-_.][^/?#]+)?\.(?:json|st)(?:$|[?#])",
                re.IGNORECASE,
            ),
            kind=SearchIndexKind.STORK,
            confidence=85,
        ),
    )

    _INLINE_URL_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"""(?P<quote>["'])
        (?P<url>
            (?:https?://|/|\./|\.\./)
            [^"'<>\\\s]+
            (?:
                search[-_]?index\.json
                |search\.json
                |pagefind-entry\.json
                |lunr[^/"']*\.json
                |elasticlunr[^/"']*\.json
                |flexsearch[^/"']*\.json
                |stork[^/"']*\.(?:json|st)
            )
            [^"'<>\\\s]*
        )
        (?P=quote)""",
        re.IGNORECASE | re.VERBOSE,
    )

    _ALGOLIA_MARKERS: ClassVar[tuple[str, ...]] = (
        "algoliasearch",
        "algolia-search",
        "algolia_application_id",
        "algolia_app_id",
        "algolia_api_key",
    )

    _DOCSEARCH_MARKERS: ClassVar[tuple[str, ...]] = (
        "docsearch",
        "docsearchcontainer",
        "docsearchbutton",
    )

    def discover(
        self,
        *,
        html: str,
        base_url: str,
    ) -> SearchIndexDiscoveryResult:
        """Discover and rank index candidates from HTML and its base URL."""

        if not html.strip() or not self._is_http_url(base_url):
            return SearchIndexDiscoveryResult(candidates=())

        soup = BeautifulSoup(html, "html.parser")
        candidates: list[SearchIndexCandidate] = []

        candidates.extend(self._discover_element_urls(soup, base_url))
        candidates.extend(self._discover_inline_urls(html, base_url))
        candidates.extend(self._discover_provider_markers(html, base_url))

        return SearchIndexDiscoveryResult(
            candidates=self._deduplicate_and_rank(candidates),
        )

    def _discover_element_urls(
        self,
        soup: BeautifulSoup,
        base_url: str,
    ) -> list[SearchIndexCandidate]:
        candidates: list[SearchIndexCandidate] = []

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
    ) -> list[SearchIndexCandidate]:
        candidates: list[SearchIndexCandidate] = []

        for match in self._INLINE_URL_PATTERN.finditer(html):
            candidate = self._candidate_from_reference(
                reference=match.group("url"),
                base_url=base_url,
                source="inline_script",
            )

            if candidate is not None:
                candidates.append(candidate)

        return candidates

    def _discover_provider_markers(
        self,
        html: str,
        base_url: str,
    ) -> list[SearchIndexCandidate]:
        searchable_html = html.casefold()
        candidates: list[SearchIndexCandidate] = []

        if any(marker in searchable_html for marker in self._DOCSEARCH_MARKERS):
            candidates.append(
                SearchIndexCandidate(
                    url=base_url,
                    kind=SearchIndexKind.DOCSEARCH,
                    confidence=75,
                    source="html_marker",
                )
            )

        if any(marker in searchable_html for marker in self._ALGOLIA_MARKERS):
            candidates.append(
                SearchIndexCandidate(
                    url=base_url,
                    kind=SearchIndexKind.ALGOLIA,
                    confidence=70,
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
    ) -> SearchIndexCandidate | None:
        normalized_reference = reference.strip()

        if not normalized_reference:
            return None

        absolute_url = self._normalize_url(
            urljoin(base_url, normalized_reference),
        )

        if absolute_url is None:
            return None

        for index_pattern in self._INDEX_PATTERNS:
            if index_pattern.pattern.search(absolute_url):
                return SearchIndexCandidate(
                    url=absolute_url,
                    kind=index_pattern.kind,
                    confidence=index_pattern.confidence,
                    source=source,
                )

        return None

    def _deduplicate_and_rank(
        self,
        candidates: list[SearchIndexCandidate],
    ) -> tuple[SearchIndexCandidate, ...]:
        strongest_by_key: dict[
            tuple[str, SearchIndexKind],
            SearchIndexCandidate,
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
