"""Language detection and English-only filtering helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from crawler.shared.language_policy import (
    LANGUAGE_QUERY_KEYS as SHARED_LANGUAGE_QUERY_KEYS,
    NORMALIZED_ENGLISH_QUERY_VALUES,
)


@dataclass(frozen=True)
class LanguageGateResult:
    """Result returned by the language gate."""

    allowed: bool
    reason: str


class LanguageGate:
    """Validate URLs and HTML content for English-language crawling."""

    LANGUAGE_QUERY_KEYS = SHARED_LANGUAGE_QUERY_KEYS
    ENGLISH_VALUES = NORMALIZED_ENGLISH_QUERY_VALUES

    ISO_LANGUAGE_CODES = {
        "aa",
        "ab",
        "ae",
        "af",
        "ak",
        "am",
        "an",
        "ar",
        "as",
        "av",
        "ay",
        "az",
        "ba",
        "be",
        "bg",
        "bh",
        "bi",
        "bm",
        "bn",
        "bo",
        "br",
        "bs",
        "ca",
        "ce",
        "ch",
        "co",
        "cr",
        "cs",
        "cu",
        "cv",
        "cy",
        "da",
        "de",
        "dv",
        "dz",
        "ee",
        "el",
        "eo",
        "es",
        "et",
        "eu",
        "fa",
        "ff",
        "fi",
        "fj",
        "fo",
        "fr",
        "fy",
        "ga",
        "gd",
        "gl",
        "gn",
        "gu",
        "gv",
        "ha",
        "he",
        "hi",
        "ho",
        "hr",
        "ht",
        "hu",
        "hy",
        "hz",
        "ia",
        "id",
        "ie",
        "ig",
        "ii",
        "ik",
        "io",
        "is",
        "it",
        "iu",
        "ja",
        "jv",
        "ka",
        "kg",
        "ki",
        "kj",
        "kk",
        "kl",
        "km",
        "kn",
        "ko",
        "kr",
        "ks",
        "ku",
        "kv",
        "kw",
        "ky",
        "la",
        "lb",
        "lg",
        "li",
        "ln",
        "lo",
        "lt",
        "lu",
        "lv",
        "mg",
        "mh",
        "mi",
        "mk",
        "ml",
        "mn",
        "mr",
        "ms",
        "mt",
        "my",
        "na",
        "nb",
        "nd",
        "ne",
        "ng",
        "nl",
        "nn",
        "no",
        "nr",
        "nv",
        "ny",
        "oc",
        "oj",
        "om",
        "or",
        "os",
        "pa",
        "pi",
        "pl",
        "ps",
        "pt",
        "qu",
        "rm",
        "rn",
        "ro",
        "ru",
        "rw",
        "sa",
        "sc",
        "sd",
        "se",
        "sg",
        "si",
        "sk",
        "sl",
        "sm",
        "sn",
        "so",
        "sq",
        "sr",
        "ss",
        "st",
        "su",
        "sv",
        "sw",
        "ta",
        "te",
        "tg",
        "th",
        "ti",
        "tk",
        "tl",
        "tn",
        "to",
        "tr",
        "ts",
        "tt",
        "tw",
        "ty",
        "ug",
        "uk",
        "ur",
        "uz",
        "ve",
        "vi",
        "vo",
        "wa",
        "wo",
        "xh",
        "yi",
        "yo",
        "za",
        "zh",
        "zu",
    }

    SAFE_HOST_PREFIXES = {
        "www",
        "docs",
        "doc",
        "developer",
        "developers",
        "help",
        "support",
        "learn",
        "blog",
        "api",
        "cloud",
        "business",
    }

    def check_url(self, url: str) -> LanguageGateResult:
        """Return whether the URL explicitly declares a supported language."""
        parsed = urlparse(url)
        host = parsed.netloc.lower().removeprefix("www.")
        path = parsed.path or "/"

        host_reason = self._blocked_host_reason(host)
        if host_reason:
            return LanguageGateResult(False, host_reason)

        path_reason = self._blocked_path_reason(path)
        if path_reason:
            return LanguageGateResult(False, path_reason)

        query_reason = self._blocked_query_reason(parsed.query)
        if query_reason:
            return LanguageGateResult(False, query_reason)

        return LanguageGateResult(True, "english_or_neutral_url")

    def check_html(self, html: str) -> LanguageGateResult:
        """Return whether HTML content is identified as English."""
        soup = BeautifulSoup(html or "", "html.parser")

        html_tag = soup.find("html")
        if isinstance(html_tag, Tag):
            lang = self._norm(str(html_tag.get("lang", "")))
            if lang and not self._is_english(lang):
                return LanguageGateResult(False, f"html_lang_non_english:{lang}")

        for selector in (
            'meta[property="og:locale"]',
            'meta[name="locale"]',
            'meta[http-equiv="content-language"]',
            'meta[name="language"]',
        ):
            tag = soup.select_one(selector)
            if not isinstance(tag, Tag):
                continue

            value = self._norm(str(tag.get("content", "")))
            if value and not self._is_english(value):
                return LanguageGateResult(False, f"html_meta_non_english:{value}")

        return LanguageGateResult(True, "html_english_or_neutral")

    def _blocked_host_reason(self, host: str) -> str | None:
        labels = [x for x in host.split(".") if x]
        if not labels:
            return None

        first = self._norm(labels[0])
        if first in self.SAFE_HOST_PREFIXES:
            return None

        parts = [p for p in re.split(r"[-_]", first) if p]
        for part in parts:
            if part in self.ISO_LANGUAGE_CODES and part != "en":
                return f"iso_block_host_label:{part}"

        return None

    def _blocked_path_reason(self, path: str) -> str | None:
        for segment in path.strip("/").split("/"):
            value = self._norm(segment)
            if not value:
                continue

            if self._is_english(value):
                return None

            parts = [p for p in re.split(r"[-_]", value) if p]
            if parts and parts[0] in self.ISO_LANGUAGE_CODES and parts[0] != "en":
                return f"iso_block_path_segment:{value}"

        return None

    def _blocked_query_reason(self, query: str) -> str | None:
        for key, value in parse_qsl(query, keep_blank_values=False):
            if key.lower().strip() not in self.LANGUAGE_QUERY_KEYS:
                continue

            normalized = self._norm(value)
            if normalized and not self._is_english(normalized):
                return f"iso_block_query:{key}={normalized}"

        return None

    def _is_english(self, value: str) -> bool:
        normalized = self._norm(value)
        return (
            normalized == "en"
            or normalized.startswith("en-")
            or normalized in self.ENGLISH_VALUES
        )

    def _norm(self, value: str) -> str:
        return value.strip().lower().replace("_", "-")


language_gate = LanguageGate()


def allow_english_url(url: str) -> LanguageGateResult:
    """Return the URL language-gate result for a candidate URL."""
    return language_gate.check_url(url)


def allow_english_html(html: str) -> LanguageGateResult:
    """Return the HTML language-gate result for downloaded content."""
    return language_gate.check_html(html)
