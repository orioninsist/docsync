from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlparse

from bs4 import BeautifulSoup
from lingua import Language, LanguageDetector, LanguageDetectorBuilder

ENGLISH_LANGUAGE_CODES = frozenset(
    {
        "en",
        "en-au",
        "en-ca",
        "en-gb",
        "en-ie",
        "en-in",
        "en-nz",
        "en-us",
        "en-za",
    }
)

NON_ENGLISH_LANGUAGE_CODES = frozenset(
    {
        "ar",
        "bg",
        "bn",
        "ca",
        "cs",
        "da",
        "de",
        "el",
        "es",
        "et",
        "fa",
        "fi",
        "fr",
        "he",
        "hi",
        "hr",
        "hu",
        "id",
        "it",
        "ja",
        "ko",
        "lt",
        "lv",
        "ms",
        "nl",
        "no",
        "pl",
        "pt",
        "pt-br",
        "pt-pt",
        "ro",
        "ru",
        "sk",
        "sl",
        "sr",
        "sv",
        "th",
        "tr",
        "uk",
        "ur",
        "vi",
        "zh",
        "zh-cn",
        "zh-hans",
        "zh-hant",
        "zh-hk",
        "zh-tw",
    }
)

TEXT_TAGS = (
    "title",
    "h1",
    "h2",
    "h3",
    "p",
    "li",
    "blockquote",
    "article",
    "main",
)

MIN_LANGUAGE_TEXT_LENGTH = 80
MAX_LANGUAGE_TEXT_LENGTH = 30_000
MIN_ENGLISH_CONFIDENCE = 0.55

LANGUAGE_QUERY_KEYS = frozenset(
    {
        "hl",
        "lang",
        "language",
        "locale",
    }
)

LANGUAGE_SUBDOMAIN_BASE_HOSTS = frozenset(
    {
        "developers.google.com",
    }
)


@dataclass(frozen=True, slots=True)
class LanguageDecision:
    is_english: bool
    language_code: str | None
    source: str
    confidence: float | None = None


class EnglishPageDetector:
    """Detect whether a downloaded HTML page is English."""

    def __init__(self) -> None:
        self._detector: LanguageDetector = (
            LanguageDetectorBuilder.from_all_spoken_languages()
            .with_preloaded_language_models()
            .build()
        )

    def detect_from_html(
        self,
        *,
        url: str,
        html: str,
        content_language: str | None = None,
    ) -> LanguageDecision:
        header_decision = self._from_language_code(
            value=content_language,
            source="content-language-header",
        )
        if header_decision is not None:
            return header_decision

        soup = BeautifulSoup(html, "html.parser")

        html_tag = soup.find("html")
        if html_tag is not None:
            html_language = html_tag.get("lang")

            html_decision = self._from_language_code(
                value=(str(html_language) if isinstance(html_language, str) else None),
                source="html-lang",
            )
            if html_decision is not None:
                return html_decision

        meta_language = soup.find(
            "meta",
            attrs={
                "http-equiv": re.compile(
                    r"^content-language$",
                    re.IGNORECASE,
                )
            },
        )
        if meta_language is not None:
            meta_content = meta_language.get("content")

            meta_decision = self._from_language_code(
                value=(str(meta_content) if isinstance(meta_content, str) else None),
                source="meta-content-language",
            )
            if meta_decision is not None:
                return meta_decision

        og_locale = soup.find(
            "meta",
            attrs={
                "property": re.compile(
                    r"^og:locale$",
                    re.IGNORECASE,
                )
            },
        )
        if og_locale is not None:
            locale_content = og_locale.get("content")

            locale_decision = self._from_language_code(
                value=(
                    str(locale_content).replace("_", "-")
                    if isinstance(locale_content, str)
                    else None
                ),
                source="og-locale",
            )
            if locale_decision is not None:
                return locale_decision

        url_decision = self.detect_from_url(url)
        if url_decision is not None:
            return url_decision

        visible_text = self._extract_visible_text(soup)

        if len(visible_text) < MIN_LANGUAGE_TEXT_LENGTH:
            return LanguageDecision(
                is_english=False,
                language_code=None,
                source="insufficient-text",
            )

        confidence_values = self._detector.compute_language_confidence_values(
            visible_text
        )

        if not confidence_values:
            return LanguageDecision(
                is_english=False,
                language_code=None,
                source="language-detector-no-result",
            )

        best = confidence_values[0]
        language_code = best.language.iso_code_639_1.name.lower()
        confidence = float(best.value)

        return LanguageDecision(
            is_english=(
                best.language == Language.ENGLISH
                and confidence >= MIN_ENGLISH_CONFIDENCE
            ),
            language_code=language_code,
            source="text-analysis",
            confidence=confidence,
        )

    def detect_from_url(
        self,
        url: str,
    ) -> LanguageDecision | None:
        return detect_explicit_url_language(url)

    @staticmethod
    def is_explicitly_non_english_url(url: str) -> bool:
        return is_explicitly_non_english_url(url)

    @staticmethod
    def _from_language_code(
        *,
        value: str | None,
        source: str,
    ) -> LanguageDecision | None:
        if not value:
            return None

        first_value = value.split(",", maxsplit=1)[0]
        first_value = first_value.split(";", maxsplit=1)[0]
        normalized = first_value.strip().lower().replace("_", "-")

        if not normalized:
            return None

        primary_code = normalized.split("-", maxsplit=1)[0]

        return LanguageDecision(
            is_english=primary_code == "en",
            language_code=normalized,
            source=source,
        )

    @staticmethod
    def _extract_visible_text(
        soup: BeautifulSoup,
    ) -> str:
        for unwanted in soup(
            [
                "script",
                "style",
                "noscript",
                "svg",
                "canvas",
                "template",
                "iframe",
            ]
        ):
            unwanted.decompose()

        selected_text: list[str] = []

        for tag_name in TEXT_TAGS:
            for element in soup.find_all(tag_name):
                value = element.get_text(" ", strip=True)
                if value:
                    selected_text.append(value)

        text = " ".join(selected_text)

        if not text:
            text = soup.get_text(" ", strip=True)

        normalized = re.sub(r"\s+", " ", text).strip()
        return normalized[:MAX_LANGUAGE_TEXT_LENGTH]


def _normalized_language_code(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    return normalized.split(",", maxsplit=1)[0].split(";", maxsplit=1)[0]


def _language_decision(
    *,
    language_code: str,
    source: str,
) -> LanguageDecision | None:
    normalized = _normalized_language_code(language_code)

    if normalized in ENGLISH_LANGUAGE_CODES:
        return LanguageDecision(
            is_english=True,
            language_code=normalized,
            source=source,
        )

    if normalized in NON_ENGLISH_LANGUAGE_CODES:
        return LanguageDecision(
            is_english=False,
            language_code=normalized,
            source=source,
        )

    primary_code = normalized.split("-", maxsplit=1)[0]

    if primary_code == "en":
        return LanguageDecision(
            is_english=True,
            language_code=normalized,
            source=source,
        )

    if primary_code in NON_ENGLISH_LANGUAGE_CODES:
        return LanguageDecision(
            is_english=False,
            language_code=normalized,
            source=source,
        )

    return None


def detect_explicit_url_language(
    url: str,
) -> LanguageDecision | None:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    hostname_parts = hostname.split(".")

    if len(hostname_parts) >= 3:
        subdomain = hostname_parts[0]
        base_hostname = ".".join(hostname_parts[1:])

        if base_hostname in LANGUAGE_SUBDOMAIN_BASE_HOSTS:
            subdomain_decision = _language_decision(
                language_code=subdomain,
                source="url-subdomain",
            )
            if subdomain_decision is not None:
                return subdomain_decision

    for key, value in parse_qsl(
        parsed.query,
        keep_blank_values=True,
    ):
        if key.strip().lower() not in LANGUAGE_QUERY_KEYS:
            continue

        query_decision = _language_decision(
            language_code=value,
            source="url-query",
        )
        if query_decision is not None:
            return query_decision

    path_parts = [
        part.lower().replace("_", "-")
        for part in parsed.path.split("/")
        if part.strip()
    ]

    for index, part in enumerate(path_parts[:4]):
        path_decision = _language_decision(
            language_code=part,
            source="url-path",
        )
        if path_decision is not None:
            return path_decision

        if part != "intl":
            continue

        if index + 1 >= len(path_parts):
            continue

        intl_decision = _language_decision(
            language_code=path_parts[index + 1],
            source="url-intl-path",
        )
        if intl_decision is not None:
            return intl_decision

    return None


def is_explicitly_non_english_url(url: str) -> bool:
    decision = detect_explicit_url_language(url)
    return decision is not None and not decision.is_english
