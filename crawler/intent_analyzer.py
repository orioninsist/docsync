"""URL intent analysis helpers for crawler discovery decisions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse

from crawler.discovery_parts.fetcher import MEDIA_SOCIAL_HOSTS


class UrlIntent(str, Enum):
    """Supported crawler URL intent classes."""

    KEEP = "keep"
    BLOCK = "block"


@dataclass(frozen=True)
class IntentDecision:
    """Final decision for a candidate URL."""

    intent: UrlIntent
    reason: str
    priority: int = 0

    @property
    def allowed(self) -> bool:
        """Return True when the candidate should stay in discovery."""

        return self.intent is UrlIntent.KEEP


class IntentAnalyzer:
    """Analyze candidate URLs before queue insertion."""

    def evaluate_url(
        self,
        url: str,
        source_url: str | None = None,
        _source_url: str | None = None,
    ) -> IntentDecision:
        """Return a crawler decision for a URL.

        Both ``source_url`` and ``_source_url`` are accepted intentionally.
        Older callers used the public keyword while a previous refactor exposed
        the private spelling. Keeping both names preserves compatibility.
        """

        del source_url, _source_url

        parsed = urlparse(url)
        host = parsed.netloc.lower()

        checks = (
            self._blocked_empty_or_scheme(url, parsed.scheme),
            self._blocked_media_social_host(host),
        )

        for decision in checks:
            if decision is not None:
                return decision

        return IntentDecision(UrlIntent.KEEP, "accepted")

    def is_allowed(self, url: str, source_url: str | None = None) -> bool:
        """Return a boolean compatibility wrapper around ``evaluate_url``."""

        return self.evaluate_url(url, source_url=source_url).allowed

    @staticmethod
    def _blocked_empty_or_scheme(url: str, scheme: str) -> IntentDecision | None:
        if not url.strip():
            return IntentDecision(UrlIntent.BLOCK, "empty-url")

        if scheme not in {"http", "https"}:
            return IntentDecision(UrlIntent.BLOCK, "unsupported-scheme")

        return None

    @staticmethod
    def _blocked_media_social_host(host: str) -> IntentDecision | None:
        if host in MEDIA_SOCIAL_HOSTS or any(
            host.endswith(f".{blocked}") for blocked in MEDIA_SOCIAL_HOSTS
        ):
            return IntentDecision(UrlIntent.BLOCK, "media-or-social-host")

        return None
