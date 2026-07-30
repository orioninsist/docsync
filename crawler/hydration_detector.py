"""Detect client-side hydration requirements in HTML documents."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

from bs4 import BeautifulSoup


class HydrationStatus(StrEnum):
    """Classification of a document's hydration requirements."""

    STATIC = "static"
    HYDRATION_LIKELY = "hydration_likely"
    HYDRATION_REQUIRED = "hydration_required"


@dataclass(frozen=True, slots=True)
class HydrationAssessment:
    """Immutable hydration assessment for one HTML document."""

    status: HydrationStatus
    reasons: tuple[str, ...]

    @property
    def requires_browser_rendering(self) -> bool:
        """Return whether browser rendering is required."""

        return self.status is HydrationStatus.HYDRATION_REQUIRED


class HydrationDetector:
    """Classify HTML documents using framework and content signals."""

    _REQUIRED_TEXT_PATTERNS: ClassVar[tuple[str, ...]] = (
        "enable javascript",
        "javascript is required",
        "please enable javascript",
        "requires javascript",
        "you need to enable javascript",
        "this app works best with javascript",
    )

    _FRAMEWORK_STATE_IDS: ClassVar[tuple[str, ...]] = (
        "__NEXT_DATA__",
        "__NUXT_DATA__",
        "__NUXT__",
        "__remixContext",
        "__gatsby",
    )

    _ROOT_SELECTORS: ClassVar[tuple[str, ...]] = (
        "#__next",
        "#__nuxt",
        "#root",
        "#app",
        "[data-reactroot]",
        "[data-react-root]",
        "[data-server-rendered]",
    )

    _MIN_VISIBLE_TEXT_LENGTH: ClassVar[int] = 120
    _MIN_SCRIPT_COUNT: ClassVar[int] = 3

    def assess(self, html: str) -> HydrationAssessment:
        """Return hydration classification for an HTML document."""

        if not html.strip():
            return HydrationAssessment(
                status=HydrationStatus.HYDRATION_REQUIRED,
                reasons=("empty_html",),
            )

        soup = BeautifulSoup(html, "html.parser")
        reasons: list[str] = []

        visible_text = self._visible_text(soup)
        normalized_text = visible_text.casefold()
        script_count = len(soup.find_all("script"))

        if self._contains_required_message(normalized_text):
            reasons.append("javascript_required_message")

        if self._contains_framework_state(soup):
            reasons.append("framework_state_payload")

        if self._contains_application_root(soup):
            reasons.append("application_root")

        if script_count >= self._MIN_SCRIPT_COUNT:
            reasons.append("script_heavy_document")

        if len(visible_text) < self._MIN_VISIBLE_TEXT_LENGTH:
            reasons.append("low_visible_text")

        return HydrationAssessment(
            status=self._classify(reasons),
            reasons=tuple(reasons),
        )

    def _contains_required_message(self, normalized_text: str) -> bool:
        return any(
            pattern in normalized_text for pattern in self._REQUIRED_TEXT_PATTERNS
        )

    def _contains_framework_state(self, soup: BeautifulSoup) -> bool:
        return any(
            soup.find(id=state_id) is not None for state_id in self._FRAMEWORK_STATE_IDS
        )

    def _contains_application_root(self, soup: BeautifulSoup) -> bool:
        return any(
            soup.select_one(selector) is not None for selector in self._ROOT_SELECTORS
        )

    @staticmethod
    def _visible_text(soup: BeautifulSoup) -> str:
        for element in soup(["script", "style", "noscript", "template"]):
            element.decompose()

        return " ".join(soup.stripped_strings)

    @staticmethod
    def _classify(reasons: list[str]) -> HydrationStatus:
        reason_set = set(reasons)

        if "javascript_required_message" in reason_set:
            return HydrationStatus.HYDRATION_REQUIRED

        required_signals = {
            "framework_state_payload",
            "application_root",
            "low_visible_text",
        }
        if required_signals.issubset(reason_set):
            return HydrationStatus.HYDRATION_REQUIRED

        likely_signals = {
            "framework_state_payload",
            "application_root",
        }
        if reason_set.intersection(likely_signals):
            return HydrationStatus.HYDRATION_LIKELY

        return HydrationStatus.STATIC
