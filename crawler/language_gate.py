"""Compatibility facade for the canonical crawler language detector."""

from __future__ import annotations

from dataclasses import dataclass

from crawler.language import LanguageDetector


@dataclass(frozen=True, slots=True)
class LanguageGateResult:
    """Result returned by the compatibility language gate."""

    allowed: bool
    reason: str


class LanguageGate:
    """Delegate language decisions to the canonical LanguageDetector owner."""

    _detector: LanguageDetector

    def __init__(self, detector: LanguageDetector | None = None) -> None:
        self._detector = detector or LanguageDetector()

    def check_url(self, url: str) -> LanguageGateResult:
        """Accept URLs without inferring content language from their structure."""

        del url

        return LanguageGateResult(
            allowed=True,
            reason="url_language_not_inferred",
        )

    def check_html(self, html: str) -> LanguageGateResult:
        """Delegate downloaded-content language detection to LanguageDetector."""

        allowed = self._detector.is_english(html)

        return LanguageGateResult(
            allowed=allowed,
            reason="english_content" if allowed else "non_english_content",
        )


language_gate = LanguageGate()


def allow_english_url(url: str) -> LanguageGateResult:
    """Return the compatibility URL language decision."""

    return language_gate.check_url(url)


def allow_english_html(html: str) -> LanguageGateResult:
    """Return the canonical downloaded-content language decision."""

    return language_gate.check_html(html)
