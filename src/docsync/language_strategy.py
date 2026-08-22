"""Requested language acceptance strategy for crawl decisions."""

from __future__ import annotations

from dataclasses import dataclass

from docsync.language import (
    LanguageDecision,
    detect_explicit_url_language,
)

SUPPORTED_LANGUAGES = frozenset(
    {
        "en",
        "tr",
    }
)


@dataclass(frozen=True, slots=True)
class LanguageStrategy:
    """Decide whether a detected language matches the requested language."""

    requested_language: str

    def __post_init__(self) -> None:
        normalized = self.requested_language.strip().lower()

        if normalized not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Unsupported requested language: {self.requested_language}"
            )

        object.__setattr__(
            self,
            "requested_language",
            normalized,
        )

    def accepts(
        self,
        decision: LanguageDecision,
    ) -> bool:
        """Return whether a language decision matches the requested language."""

        if decision.language_code is None:
            return False

        return (
            decision.language_code.split(
                "-",
                maxsplit=1,
            )[0]
            == self.requested_language
        )

    def should_skip_url(
        self,
        url: str,
    ) -> bool:
        """Return whether a URL has a definite different language signal."""

        decision = detect_explicit_url_language(url)

        if decision is None:
            return False

        if decision.language_code is None:
            return False

        detected_language = decision.language_code.split(
            "-",
            maxsplit=1,
        )[0]

        return detected_language != self.requested_language
