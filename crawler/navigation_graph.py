"""Extract structured documentation navigation relationships from HTML."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar
from urllib.parse import urldefrag, urljoin

from bs4 import BeautifulSoup, Tag

from crawler.shared.url_normalizer import normalize_url
from crawler.shared.url_policy import BLOCKED_LINK_PREFIXES


class NavigationRelation(StrEnum):
    """Supported navigation relationships between documentation pages."""

    SIDEBAR = "sidebar"
    TABLE_OF_CONTENTS = "table_of_contents"
    PREVIOUS = "previous"
    NEXT = "next"
    BREADCRUMB = "breadcrumb"
    NAVIGATION = "navigation"


@dataclass(frozen=True, slots=True)
class NavigationEdge:
    """One directed navigation relationship discovered in an HTML document."""

    source_url: str
    target_url: str
    relation: NavigationRelation
    label: str
    priority: int
    position: int


@dataclass(frozen=True, slots=True)
class NavigationGraph:
    """Immutable navigation graph extracted from one HTML document."""

    source_url: str
    edges: tuple[NavigationEdge, ...]

    @property
    def discovered_urls(self) -> tuple[str, ...]:
        """Return unique target URLs ordered by navigation priority."""

        ordered_edges = sorted(
            self.edges,
            key=lambda edge: (
                -edge.priority,
                edge.position,
                edge.target_url,
            ),
        )
        seen: set[str] = set()
        urls: list[str] = []

        for edge in ordered_edges:
            if edge.target_url in seen:
                continue

            seen.add(edge.target_url)
            urls.append(edge.target_url)

        return tuple(urls)


@dataclass(frozen=True, slots=True)
class _NavigationRegion:
    """Selector configuration for one navigation relationship."""

    relation: NavigationRelation
    selectors: tuple[str, ...]
    priority: int


class NavigationGraphExtractor:
    """Extract sidebar, TOC, pagination, and breadcrumb relationships."""

    _REGIONS: ClassVar[tuple[_NavigationRegion, ...]] = (
        _NavigationRegion(
            relation=NavigationRelation.SIDEBAR,
            selectors=(
                "aside nav",
                "nav.sidebar",
                ".sidebar nav",
                ".sidebar",
                ".docs-sidebar",
                ".doc-sidebar",
                ".theme-doc-sidebar-container",
                ".menu",
                ".md-sidebar",
                ".md-nav",
                ".vp-sidebar",
                ".nextra-sidebar-container",
                ".fd-sidebar",
                ".wy-nav-side",
                ".sphinxsidebar",
                "[data-md-component='navigation']",
                "[data-testid='sidebar']",
            ),
            priority=100,
        ),
        _NavigationRegion(
            relation=NavigationRelation.TABLE_OF_CONTENTS,
            selectors=(
                "nav.toc",
                ".toc",
                ".table-of-contents",
                ".on-this-page",
                ".page-toc",
                ".docs-toc",
                ".theme-doc-toc-desktop",
                ".md-sidebar--secondary",
                ".vp-doc-outline",
                "[data-md-component='toc']",
                "[aria-label='Table of contents']",
                "[aria-label='On this page']",
            ),
            priority=70,
        ),
        _NavigationRegion(
            relation=NavigationRelation.BREADCRUMB,
            selectors=(
                "nav.breadcrumb",
                "nav.breadcrumbs",
                ".breadcrumb",
                ".breadcrumbs",
                "[aria-label='Breadcrumb']",
                "[aria-label='Breadcrumbs']",
            ),
            priority=45,
        ),
        _NavigationRegion(
            relation=NavigationRelation.NAVIGATION,
            selectors=(
                "nav[aria-label='Main']",
                "nav[aria-label='Primary']",
                "nav[role='navigation']",
                "header nav",
                ".navbar",
                ".navbar__inner",
                ".vp-nav",
                ".nextra-nav-container",
                ".fd-nav",
            ),
            priority=30,
        ),
    )

    _PREVIOUS_SELECTORS: ClassVar[tuple[str, ...]] = (
        "a[rel='prev']",
        "a[rel='previous']",
        "a.pagination-prev",
        "a.prev",
        ".pagination-nav__link--prev",
        ".pager-prev a",
        ".previous a",
        "[aria-label='Previous']",
        "[aria-label='Previous page']",
    )

    _NEXT_SELECTORS: ClassVar[tuple[str, ...]] = (
        "a[rel='next']",
        "a.pagination-next",
        "a.next",
        ".pagination-nav__link--next",
        ".pager-next a",
        ".next a",
        "[aria-label='Next']",
        "[aria-label='Next page']",
    )

    _PREVIOUS_PRIORITY: ClassVar[int] = 95
    _NEXT_PRIORITY: ClassVar[int] = 95

    def extract(self, html: str, source_url: str) -> NavigationGraph:
        """Return navigation relationships discovered in an HTML document."""

        normalized_source = normalize_url(source_url)

        if normalized_source is None:
            normalized_source = source_url.strip()

        if not html.strip():
            return NavigationGraph(
                source_url=normalized_source,
                edges=(),
            )

        soup = BeautifulSoup(html, "html.parser")
        edges: list[NavigationEdge] = []
        position = 0

        for region in self._REGIONS:
            for container in self._select_unique_regions(
                soup,
                region.selectors,
            ):
                for anchor in container.select("a[href]"):
                    edge = self._build_edge(
                        anchor=anchor,
                        source_url=normalized_source,
                        relation=region.relation,
                        priority=region.priority,
                        position=position,
                    )

                    if edge is None:
                        continue

                    edges.append(edge)
                    position += 1

        for selector in self._PREVIOUS_SELECTORS:
            for anchor in soup.select(selector):
                edge = self._build_edge(
                    anchor=anchor,
                    source_url=normalized_source,
                    relation=NavigationRelation.PREVIOUS,
                    priority=self._PREVIOUS_PRIORITY,
                    position=position,
                )

                if edge is None:
                    continue

                edges.append(edge)
                position += 1

        for selector in self._NEXT_SELECTORS:
            for anchor in soup.select(selector):
                edge = self._build_edge(
                    anchor=anchor,
                    source_url=normalized_source,
                    relation=NavigationRelation.NEXT,
                    priority=self._NEXT_PRIORITY,
                    position=position,
                )

                if edge is None:
                    continue

                edges.append(edge)
                position += 1

        return NavigationGraph(
            source_url=normalized_source,
            edges=self._deduplicate_edges(edges),
        )

    def _select_unique_regions(
        self,
        soup: BeautifulSoup,
        selectors: tuple[str, ...],
    ) -> tuple[Tag, ...]:
        regions: list[Tag] = []
        seen_ids: set[int] = set()

        for selector in selectors:
            for element in soup.select(selector):
                element_id = id(element)

                if element_id in seen_ids:
                    continue

                seen_ids.add(element_id)
                regions.append(element)

        return tuple(regions)

    def _build_edge(
        self,
        *,
        anchor: Tag,
        source_url: str,
        relation: NavigationRelation,
        priority: int,
        position: int,
    ) -> NavigationEdge | None:
        href = anchor.get("href")

        if not isinstance(href, str):
            return None

        target_url = self._normalize_target_url(
            href=href,
            source_url=source_url,
        )

        if target_url is None or target_url == source_url:
            return None

        return NavigationEdge(
            source_url=source_url,
            target_url=target_url,
            relation=relation,
            label=self._extract_label(anchor),
            priority=priority,
            position=position,
        )

    def _normalize_target_url(
        self,
        *,
        href: str,
        source_url: str,
    ) -> str | None:
        cleaned_href = href.strip()

        if not cleaned_href:
            return None

        if cleaned_href.casefold().startswith(BLOCKED_LINK_PREFIXES):
            return None

        absolute_url = urljoin(source_url, cleaned_href)
        defragmented_url, _fragment = urldefrag(absolute_url)

        return normalize_url(defragmented_url)

    def _extract_label(self, anchor: Tag) -> str:
        text = anchor.get_text(" ", strip=True)

        if text:
            return " ".join(text.split())

        for attribute in ("aria-label", "title"):
            value = anchor.get(attribute)

            if isinstance(value, str) and value.strip():
                return " ".join(value.split())

        return ""

    def _deduplicate_edges(
        self,
        edges: list[NavigationEdge],
    ) -> tuple[NavigationEdge, ...]:
        unique_edges: list[NavigationEdge] = []
        seen: set[tuple[str, NavigationRelation]] = set()

        for edge in sorted(
            edges,
            key=lambda item: (
                -item.priority,
                item.position,
            ),
        ):
            identity = (
                edge.target_url,
                edge.relation,
            )

            if identity in seen:
                continue

            seen.add(identity)
            unique_edges.append(edge)

        return tuple(unique_edges)


__all__ = [
    "NavigationEdge",
    "NavigationGraph",
    "NavigationGraphExtractor",
    "NavigationRelation",
]
