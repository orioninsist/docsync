from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from crawler.shared.url_normalizer import normalize_url


class VersionSource(StrEnum):
    """Origin of a discovered documentation version."""

    META = "meta"
    SELECTOR = "selector"
    LINK = "link"
    URL_PATH = "url_path"
    TEXT = "text"


@dataclass(frozen=True, slots=True)
class DocumentationVersion:
    """One normalized documentation version discovered on a page."""

    value: str
    source: VersionSource
    url: str | None
    is_current: bool
    confidence: int


@dataclass(frozen=True, slots=True)
class VersionDiscoveryResult:
    """Immutable version-discovery result for one HTML document."""

    current_version: str | None
    versions: tuple[DocumentationVersion, ...]
    reasons: tuple[str, ...]

    @property
    def detected(self) -> bool:
        """Return whether at least one documentation version was discovered."""

        return bool(self.versions)


@dataclass(frozen=True, slots=True)
class _VersionCandidate:
    """Internal normalized candidate before deduplication."""

    value: str
    source: VersionSource
    url: str | None
    is_current: bool
    confidence: int
    position: int


class VersionDiscovery:
    """Discover documentation versions from HTML and URL signals."""

    _VERSION_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"""
        (?<![A-Za-z0-9])
        (
            latest
            |
            stable
            |
            next
            |
            main
            |
            master
            |
            v?\d+
            (?:
                \.\d+
            ){0,3}
            (?:
                [-_](?:alpha|beta|rc|preview|dev|nightly)\d*
            )?
        )
        (?![A-Za-z0-9])
        """,
        flags=re.IGNORECASE | re.VERBOSE,
    )

    _PATH_SEGMENT_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"""
        ^
        (
            latest
            |
            stable
            |
            next
            |
            main
            |
            master
            |
            v?\d+
            (?:
                \.\d+
            ){0,3}
            (?:
                [-_](?:alpha|beta|rc|preview|dev|nightly)\d*
            )?
        )
        $
        """,
        flags=re.IGNORECASE | re.VERBOSE,
    )

    _META_SELECTORS: ClassVar[tuple[str, ...]] = (
        'meta[name="version"]',
        'meta[name="docs-version"]',
        'meta[name="documentation-version"]',
        'meta[property="version"]',
        'meta[property="docs:version"]',
        'meta[property="documentation:version"]',
    )

    _VERSION_REGION_SELECTORS: ClassVar[tuple[str, ...]] = (
        "[data-version]",
        "[data-docs-version]",
        ".version",
        ".versions",
        ".version-selector",
        ".version-switcher",
        ".docs-version",
        ".docs-version-selector",
        ".navbar-version",
        ".menu-version",
        "select[name*='version' i]",
        "[aria-label*='version' i]",
        "[title*='version' i]",
    )

    _CURRENT_MARKERS: ClassVar[tuple[str, ...]] = (
        "active",
        "current",
        "selected",
        "checked",
        "aria-current",
    )

    _CURRENT_CONFIDENCE: ClassVar[int] = 100
    _META_CONFIDENCE: ClassVar[int] = 95
    _SELECTOR_CONFIDENCE: ClassVar[int] = 85
    _LINK_CONFIDENCE: ClassVar[int] = 75
    _URL_CONFIDENCE: ClassVar[int] = 70
    _TEXT_CONFIDENCE: ClassVar[int] = 45

    def discover(self, html: str, source_url: str) -> VersionDiscoveryResult:
        """Return documentation versions discovered from one HTML document."""

        normalized_source_url = normalize_url(source_url) or source_url.strip()

        if not html.strip():
            return VersionDiscoveryResult(
                current_version=self._extract_version_from_url(normalized_source_url),
                versions=self._url_only_versions(normalized_source_url),
                reasons=("empty_html",),
            )

        soup = BeautifulSoup(html, "html.parser")
        candidates: list[_VersionCandidate] = []
        reasons: list[str] = []

        self._collect_meta_candidates(
            soup=soup,
            candidates=candidates,
            reasons=reasons,
        )
        self._collect_selector_candidates(
            soup=soup,
            source_url=normalized_source_url,
            candidates=candidates,
            reasons=reasons,
        )
        self._collect_link_candidates(
            soup=soup,
            source_url=normalized_source_url,
            candidates=candidates,
            reasons=reasons,
        )
        self._collect_url_candidate(
            source_url=normalized_source_url,
            candidates=candidates,
            reasons=reasons,
        )
        self._collect_text_candidates(
            soup=soup,
            candidates=candidates,
            reasons=reasons,
        )

        versions = self._deduplicate_candidates(candidates)
        current_version = self._select_current_version(versions)

        if not versions:
            reasons.append("no_version_signals")

        return VersionDiscoveryResult(
            current_version=current_version,
            versions=versions,
            reasons=tuple(dict.fromkeys(reasons)),
        )

    def _collect_meta_candidates(
        self,
        *,
        soup: BeautifulSoup,
        candidates: list[_VersionCandidate],
        reasons: list[str],
    ) -> None:
        for selector in self._META_SELECTORS:
            for position, tag in enumerate(soup.select(selector)):
                content = tag.get("content")

                if not isinstance(content, str):
                    continue

                version = self._normalize_version(content)

                if version is None:
                    continue

                candidates.append(
                    _VersionCandidate(
                        value=version,
                        source=VersionSource.META,
                        url=None,
                        is_current=True,
                        confidence=self._META_CONFIDENCE,
                        position=position,
                    )
                )
                reasons.append("version_meta")

    def _collect_selector_candidates(
        self,
        *,
        soup: BeautifulSoup,
        source_url: str,
        candidates: list[_VersionCandidate],
        reasons: list[str],
    ) -> None:
        position = 0

        for selector in self._VERSION_REGION_SELECTORS:
            for region in soup.select(selector):
                region_candidates = self._extract_versions_from_region(
                    region=region,
                    source_url=source_url,
                    starting_position=position,
                )
                candidates.extend(region_candidates)
                position += len(region_candidates)

                if region_candidates:
                    reasons.append("version_selector")

    def _extract_versions_from_region(
        self,
        *,
        region: Tag,
        source_url: str,
        starting_position: int,
    ) -> list[_VersionCandidate]:
        discovered: list[_VersionCandidate] = []
        tags = [region, *region.find_all(["a", "option"])]

        for offset, tag in enumerate(tags):
            value = self._version_value_from_tag(tag)

            if value is None:
                continue

            is_current = self._is_current_tag(tag)

            discovered.append(
                _VersionCandidate(
                    value=value,
                    source=VersionSource.SELECTOR,
                    url=self._tag_target_url(tag, source_url),
                    is_current=is_current,
                    confidence=(
                        self._CURRENT_CONFIDENCE
                        if is_current
                        else self._SELECTOR_CONFIDENCE
                    ),
                    position=starting_position + offset,
                )
            )

        return discovered

    def _collect_link_candidates(
        self,
        *,
        soup: BeautifulSoup,
        source_url: str,
        candidates: list[_VersionCandidate],
        reasons: list[str],
    ) -> None:
        for position, anchor in enumerate(soup.find_all("a")):
            href = anchor.get("href")

            if not isinstance(href, str) or not href.strip():
                continue

            absolute_url = normalize_url(urljoin(source_url, href.strip()))

            if absolute_url is None:
                continue

            version = self._extract_version_from_url(absolute_url)

            if version is None:
                continue

            label = self._normalize_version(anchor.get_text(" ", strip=True))

            if label is not None:
                version = label

            is_current = self._is_current_tag(anchor)

            candidates.append(
                _VersionCandidate(
                    value=version,
                    source=VersionSource.LINK,
                    url=absolute_url,
                    is_current=is_current,
                    confidence=(
                        self._CURRENT_CONFIDENCE
                        if is_current
                        else self._LINK_CONFIDENCE
                    ),
                    position=position,
                )
            )
            reasons.append("version_link")

    def _collect_url_candidate(
        self,
        *,
        source_url: str,
        candidates: list[_VersionCandidate],
        reasons: list[str],
    ) -> None:
        version = self._extract_version_from_url(source_url)

        if version is None:
            return

        candidates.append(
            _VersionCandidate(
                value=version,
                source=VersionSource.URL_PATH,
                url=source_url,
                is_current=True,
                confidence=self._URL_CONFIDENCE,
                position=0,
            )
        )
        reasons.append("version_url_path")

    def _collect_text_candidates(
        self,
        *,
        soup: BeautifulSoup,
        candidates: list[_VersionCandidate],
        reasons: list[str],
    ) -> None:
        text_sources = (
            soup.select_one("title"),
            soup.select_one("h1"),
            soup.select_one("[class*='version' i]"),
        )

        for position, tag in enumerate(text_sources):
            if not isinstance(tag, Tag):
                continue

            version = self._normalize_version(tag.get_text(" ", strip=True))

            if version is None:
                continue

            candidates.append(
                _VersionCandidate(
                    value=version,
                    source=VersionSource.TEXT,
                    url=None,
                    is_current=False,
                    confidence=self._TEXT_CONFIDENCE,
                    position=position,
                )
            )
            reasons.append("version_text")

    def _version_value_from_tag(self, tag: Tag) -> str | None:
        for attribute in (
            "data-version",
            "data-docs-version",
            "value",
            "aria-label",
            "title",
        ):
            value = tag.get(attribute)

            if isinstance(value, str):
                normalized = self._normalize_version(value)

                if normalized is not None:
                    return normalized

        return self._normalize_version(tag.get_text(" ", strip=True))

    def _tag_target_url(self, tag: Tag, source_url: str) -> str | None:
        for attribute in ("href", "value", "data-url"):
            value = tag.get(attribute)

            if not isinstance(value, str) or not value.strip():
                continue

            if attribute == "value" and self._normalize_version(value) is not None:
                continue

            return normalize_url(urljoin(source_url, value.strip()))

        return None

    def _is_current_tag(self, tag: Tag) -> bool:
        if tag.has_attr("selected") or tag.has_attr("checked"):
            return True

        aria_current = tag.get("aria-current")

        if isinstance(aria_current, str) and aria_current.casefold() not in {
            "",
            "false",
            "none",
        }:
            return True

        class_values = tag.get("class")

        if isinstance(class_values, list):
            normalized_classes = {
                str(value).strip().casefold() for value in class_values
            }

            if normalized_classes.intersection(self._CURRENT_MARKERS):
                return True

        return False

    def _normalize_version(self, value: str) -> str | None:
        match = self._VERSION_PATTERN.search(" ".join(value.split()))

        if match is None:
            return None

        version = match.group(1).strip().lower().replace("_", "-")

        if version.startswith("v") and version[1:2].isdigit():
            return version

        return version

    def _extract_version_from_url(self, url: str) -> str | None:
        path_segments = [
            segment.strip()
            for segment in urlparse(url).path.split("/")
            if segment.strip()
        ]

        for segment in path_segments:
            match = self._PATH_SEGMENT_PATTERN.fullmatch(segment)

            if match is not None:
                return self._normalize_version(match.group(1))

        return None

    def _deduplicate_candidates(
        self,
        candidates: list[_VersionCandidate],
    ) -> tuple[DocumentationVersion, ...]:
        best_by_value: dict[str, _VersionCandidate] = {}

        for candidate in candidates:
            existing = best_by_value.get(candidate.value)

            if existing is None or self._candidate_rank(
                candidate
            ) > self._candidate_rank(existing):
                best_by_value[candidate.value] = candidate

        ordered = sorted(
            best_by_value.values(),
            key=lambda candidate: (
                not candidate.is_current,
                -candidate.confidence,
                candidate.position,
                candidate.value,
            ),
        )

        return tuple(
            DocumentationVersion(
                value=candidate.value,
                source=candidate.source,
                url=candidate.url,
                is_current=candidate.is_current,
                confidence=candidate.confidence,
            )
            for candidate in ordered
        )

    def _candidate_rank(
        self,
        candidate: _VersionCandidate,
    ) -> tuple[bool, int, bool, int]:
        return (
            candidate.is_current,
            candidate.confidence,
            candidate.url is not None,
            -candidate.position,
        )

    def _select_current_version(
        self,
        versions: tuple[DocumentationVersion, ...],
    ) -> str | None:
        for version in versions:
            if version.is_current:
                return version.value

        if versions:
            return versions[0].value

        return None

    def _url_only_versions(
        self,
        source_url: str,
    ) -> tuple[DocumentationVersion, ...]:
        version = self._extract_version_from_url(source_url)

        if version is None:
            return ()

        return (
            DocumentationVersion(
                value=version,
                source=VersionSource.URL_PATH,
                url=source_url,
                is_current=True,
                confidence=self._URL_CONFIDENCE,
            ),
        )
