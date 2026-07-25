"""URL intent analysis helpers for crawler discovery decisions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from urllib.parse import parse_qs, urlparse

from crawler.discovery_parts.fetcher import (
    EXTRA_REGION_ALIASES,
    ISO_3166_REGION_CODES,
    MEDIA_SOCIAL_HOSTS,
)


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

    _BLOCKED_QUERY_KEYS: frozenset[str] = frozenset(
        {
            "lang",
            "locale",
            "region",
            "country",
            "market",
            "hl",
            "gl",
        }
    )
    _REGIONAL_PATH_PREFIXES: frozenset[str] = frozenset(
        {
            "ar",
            "br",
            "cn",
            "de",
            "dk",
            "es",
            "fi",
            "fr",
            "it",
            "jp",
            "kr",
            "mx",
            "nl",
            "no",
            "pl",
            "pt",
            "ru",
            "se",
            "tr",
            "uk",
        }
    )

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

        parent_url = source_url or _source_url
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path.lower()

        checks = (
            self._blocked_empty_or_scheme(url, parsed.scheme),
            self._blocked_media_social_host(host),
            self._blocked_regional_host(host),
            self._blocked_regional_path(path),
            self._blocked_regional_query(parsed.query),
            self._blocked_cross_source_region(host, parent_url),
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

    @classmethod
    def _blocked_regional_host(cls, host: str) -> IntentDecision | None:
        labels = [label for label in host.split(".") if label]
        if not labels:
            return IntentDecision(UrlIntent.BLOCK, "missing-host")

        regional_codes = cls._regional_codes()
        if labels[0] in regional_codes:
            return IntentDecision(UrlIntent.BLOCK, "regional-subdomain")
        if labels[-1] in regional_codes:
            return IntentDecision(UrlIntent.BLOCK, "regional-tld")
        return None

    @classmethod
    def _blocked_regional_path(cls, path: str) -> IntentDecision | None:
        parts = [part for part in path.split("/") if part]
        if not parts:
            return None

        first = parts[0].replace("_", "-")
        first_base = first.split("-", maxsplit=1)[0]
        if first in cls._regional_codes() or first_base in cls._REGIONAL_PATH_PREFIXES:
            return IntentDecision(UrlIntent.BLOCK, "regional-path")
        return None

    @classmethod
    def _blocked_regional_query(cls, query: str) -> IntentDecision | None:
        query_values = parse_qs(query, keep_blank_values=False)
        regional_codes = cls._regional_codes()

        for key, values in query_values.items():
            normalized_key = key.lower()
            if normalized_key not in cls._BLOCKED_QUERY_KEYS:
                continue
            for value in values:
                normalized_value = value.lower().replace("_", "-")
                value_base = normalized_value.split("-", maxsplit=1)[0]
                if normalized_value in regional_codes or value_base in regional_codes:
                    return IntentDecision(UrlIntent.BLOCK, "regional-query")
        return None

    @classmethod
    def _blocked_cross_source_region(
        cls,
        host: str,
        source_url: str | None,
    ) -> IntentDecision | None:
        if source_url is None:
            return None

        source_host = urlparse(source_url).netloc.lower()
        if not source_host:
            return None

        source_region = cls._host_region(source_host)
        target_region = cls._host_region(host)
        if source_region and target_region and source_region != target_region:
            return IntentDecision(UrlIntent.BLOCK, "cross-region-host")
        return None

    @classmethod
    def _host_region(cls, host: str) -> str | None:
        labels = [label for label in host.split(".") if label]
        regional_codes = cls._regional_codes()

        if not labels:
            return None
        if labels[0] in regional_codes:
            return labels[0]
        if labels[-1] in regional_codes:
            return labels[-1]
        return None

    @staticmethod
    def _regional_codes() -> frozenset[str]:
        return frozenset(ISO_3166_REGION_CODES) | frozenset(EXTRA_REGION_ALIASES)
