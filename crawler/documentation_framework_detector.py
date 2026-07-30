"""Detect documentation frameworks from HTML document signals."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

from bs4 import BeautifulSoup


class DocumentationFramework(StrEnum):
    """Supported documentation framework classifications."""

    UNKNOWN = "unknown"
    DOCUSAURUS = "docusaurus"
    MKDOCS = "mkdocs"
    MATERIAL_FOR_MKDOCS = "material_for_mkdocs"
    VITEPRESS = "vitepress"
    DOCSIFY = "docsify"
    GITBOOK = "gitbook"
    MINTLIFY = "mintlify"
    NEXTRA = "nextra"
    FUMADOCS = "fumadocs"
    SPHINX = "sphinx"
    READTHEDOCS = "readthedocs"


@dataclass(frozen=True, slots=True)
class FrameworkAssessment:
    """Immutable framework assessment for one HTML document."""

    framework: DocumentationFramework
    confidence: int
    reasons: tuple[str, ...]

    @property
    def detected(self) -> bool:
        """Return whether a supported documentation framework was detected."""

        return self.framework is not DocumentationFramework.UNKNOWN


@dataclass(frozen=True, slots=True)
class _FrameworkRule:
    """Detection signals and scoring threshold for one framework."""

    framework: DocumentationFramework
    patterns: tuple[str, ...]
    threshold: int


class DocumentationFrameworkDetector:
    """Classify documentation framework identity using HTML signals."""

    _RULES: ClassVar[tuple[_FrameworkRule, ...]] = (
        _FrameworkRule(
            framework=DocumentationFramework.MATERIAL_FOR_MKDOCS,
            patterns=(
                "data-md-component",
                "md-header",
                "md-main",
                "md-nav",
                "md-content",
                "material for mkdocs",
            ),
            threshold=2,
        ),
        _FrameworkRule(
            framework=DocumentationFramework.DOCUSAURUS,
            patterns=(
                "__docusaurus",
                "docusaurus",
                "navbar__inner",
                "theme-doc-markdown",
                "docsidebarcontainer",
            ),
            threshold=2,
        ),
        _FrameworkRule(
            framework=DocumentationFramework.VITEPRESS,
            patterns=(
                "vitepress",
                "vp-doc",
                "vp-nav",
                "vp-sidebar",
                "__vitepress",
            ),
            threshold=2,
        ),
        _FrameworkRule(
            framework=DocumentationFramework.DOCSIFY,
            patterns=(
                "docsify",
                "window.$docsify",
                "data-app",
                "app-name-link",
            ),
            threshold=2,
        ),
        _FrameworkRule(
            framework=DocumentationFramework.GITBOOK,
            patterns=(
                "gitbook",
                "gitbook.io",
                "gitbook-content",
                "gitbook-root",
            ),
            threshold=2,
        ),
        _FrameworkRule(
            framework=DocumentationFramework.MINTLIFY,
            patterns=(
                "mintlify",
                "mintlify.com",
                "mintlify-content",
                "mintlify-navigation",
            ),
            threshold=2,
        ),
        _FrameworkRule(
            framework=DocumentationFramework.NEXTRA,
            patterns=(
                "nextra",
                "nextra-nav-container",
                "nextra-sidebar-container",
                "nextra-content",
            ),
            threshold=2,
        ),
        _FrameworkRule(
            framework=DocumentationFramework.FUMADOCS,
            patterns=(
                "fumadocs",
                "fumadocs.dev",
                "fd-sidebar",
                "fd-nav",
            ),
            threshold=2,
        ),
        _FrameworkRule(
            framework=DocumentationFramework.READTHEDOCS,
            patterns=(
                "readthedocs",
                "read the docs",
                "readthedocs.io",
                "rtd-search-form",
                "wy-nav-side",
            ),
            threshold=2,
        ),
        _FrameworkRule(
            framework=DocumentationFramework.SPHINX,
            patterns=(
                "sphinx",
                "sphinxsidebar",
                "sphinx-version",
                "documentwrapper",
                "pygments.css",
            ),
            threshold=2,
        ),
        _FrameworkRule(
            framework=DocumentationFramework.MKDOCS,
            patterns=(
                "mkdocs",
                "mkdocs.org",
                "mkdocs-search-query",
                "navbar-fixed-top",
            ),
            threshold=2,
        ),
    )

    _CONFIDENCE_PER_SIGNAL: ClassVar[int] = 25
    _MAX_CONFIDENCE: ClassVar[int] = 100

    def assess(self, html: str) -> FrameworkAssessment:
        """Return documentation framework classification for an HTML document."""

        if not html.strip():
            return FrameworkAssessment(
                framework=DocumentationFramework.UNKNOWN,
                confidence=0,
                reasons=("empty_html",),
            )

        soup = BeautifulSoup(html, "html.parser")
        searchable_document = self._build_searchable_document(soup)

        best_rule: _FrameworkRule | None = None
        best_matches: tuple[str, ...] = ()

        for rule in self._RULES:
            matches = tuple(
                pattern for pattern in rule.patterns if pattern in searchable_document
            )

            if len(matches) < rule.threshold:
                continue

            if len(matches) > len(best_matches):
                best_rule = rule
                best_matches = matches

        if best_rule is None:
            return FrameworkAssessment(
                framework=DocumentationFramework.UNKNOWN,
                confidence=0,
                reasons=("no_framework_signals",),
            )

        confidence = min(
            len(best_matches) * self._CONFIDENCE_PER_SIGNAL,
            self._MAX_CONFIDENCE,
        )

        return FrameworkAssessment(
            framework=best_rule.framework,
            confidence=confidence,
            reasons=best_matches,
        )

    def _build_searchable_document(self, soup: BeautifulSoup) -> str:
        fragments = (
            str(soup).casefold(),
            self._generator_content(soup),
            self._resource_urls(soup),
            self._element_identifiers(soup),
        )
        return "\n".join(fragment for fragment in fragments if fragment)

    def _generator_content(self, soup: BeautifulSoup) -> str:
        generators: list[str] = []

        for meta in soup.find_all("meta"):
            name = meta.get("name")
            content = meta.get("content")

            if (
                isinstance(name, str)
                and name.casefold() == "generator"
                and isinstance(content, str)
            ):
                generators.append(content.casefold())

        return "\n".join(generators)

    def _resource_urls(self, soup: BeautifulSoup) -> str:
        resource_urls: list[str] = []

        for element in soup.find_all(("script", "link")):
            for attribute in ("src", "href"):
                value = element.get(attribute)

                if isinstance(value, str):
                    resource_urls.append(value.casefold())

        return "\n".join(resource_urls)

    def _element_identifiers(self, soup: BeautifulSoup) -> str:
        identifiers: list[str] = []

        for element in soup.find_all(True):
            element_id = element.get("id")

            if isinstance(element_id, str):
                identifiers.append(element_id.casefold())

            classes = element.get("class")

            if isinstance(classes, list):
                identifiers.extend(value.casefold() for value in classes)

            identifiers.extend(
                str(attribute_name).casefold() for attribute_name in element.attrs
            )

        return "\n".join(identifiers)
