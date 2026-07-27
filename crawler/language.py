"""Detect whether crawled HTML content is English enough to keep."""

from __future__ import annotations

import re
from typing import ClassVar

from bs4 import BeautifulSoup
from bs4.element import Tag

from crawler.shared.language_policy import is_english_language_value


class LanguageDetector:  # pylint: disable=too-few-public-methods
    """Rule-based English language detector for crawler pre-filtering."""

    ENGLISH_STOPWORDS: ClassVar[set[str]] = {
        "the",
        "and",
        "you",
        "your",
        "for",
        "with",
        "from",
        "this",
        "that",
        "are",
        "can",
        "how",
        "what",
        "when",
        "where",
        "learn",
        "create",
        "video",
        "channel",
        "account",
        "help",
        "support",
        "settings",
        "manage",
        "use",
        "using",
        "page",
        "content",
        "policy",
        "privacy",
        "terms",
        "search",
        "make",
        "get",
        "set",
        "new",
        "more",
        "about",
        "not",
        "all",
        "or",
        "if",
        "to",
        "in",
        "on",
        "of",
        "is",
        "it",
        "as",
        "be",
        "by",
        "a",
        "an",
        "at",
        "we",
        "our",
        "they",
        "their",
        "will",
        "may",
        "should",
        "before",
        "after",
        "overview",
        "guide",
        "documentation",
        "reference",
        "example",
        "examples",
        "install",
        "configure",
        "build",
        "run",
        "delete",
        "edit",
        "update",
    }

    NON_ENGLISH_STOPWORDS: ClassVar[set[str]] = {
        "ve",
        "veya",
        "bir",
        "bu",
        "şu",
        "için",
        "ile",
        "nasıl",
        "nedir",
        "olan",
        "olarak",
        "daha",
        "değil",
        "giriş",
        "hesap",
        "ayarlar",
        "kullan",
        "kullanım",
        "hakkında",
        "yardım",
        "destek",
        "und",
        "oder",
        "der",
        "die",
        "das",
        "ein",
        "eine",
        "für",
        "mit",
        "nicht",
        "ist",
        "sind",
        "wie",
        "was",
        "konto",
        "einstellungen",
        "hilfe",
        "unterstützung",
        "et",
        "ou",
        "le",
        "la",
        "les",
        "des",
        "un",
        "une",
        "pour",
        "avec",
        "pas",
        "est",
        "sont",
        "comment",
        "quoi",
        "compte",
        "paramètres",
        "aide",
        "assistance",
        "y",
        "o",
        "el",
        "los",
        "las",
        "una",
        "para",
        "con",
        "no",
        "es",
        "son",
        "cómo",
        "qué",
        "cuenta",
        "configuración",
        "ayuda",
        "soporte",
        "e",
        "os",
        "as",
        "um",
        "uma",
        "com",
        "não",
        "como",
        "que",
        "conta",
        "configurações",
        "suporte",
        "en",
        "of",
        "de",
        "het",
        "een",
        "voor",
        "met",
        "niet",
        "zijn",
        "hoe",
        "wat",
        "instellingen",
        "hulp",
        "ondersteuning",
    }

    NON_ENGLISH_CHARACTER_MARKERS: ClassVar[set[str]] = {
        "ç",
        "ğ",
        "ı",
        "İ",
        "ö",
        "ş",
        "ü",
        "ß",
        "ñ",
        "¿",
        "¡",
        "ã",
        "õ",
    }

    META_LANGUAGE_SELECTORS: ClassVar[tuple[str, ...]] = (
        'meta[property="og:locale"]',
        'meta[name="locale"]',
        'meta[http-equiv="content-language"]',
        'meta[name="language"]',
    )

    MIN_TEXT_LENGTH: ClassVar[int] = 80
    MIN_WORD_COUNT: ClassVar[int] = 20
    MIN_LATIN_RATIO: ClassVar[float] = 0.75
    MIN_ENGLISH_STOPWORD_RATIO: ClassVar[float] = 0.035
    MAX_NON_ENGLISH_STOPWORD_RATIO: ClassVar[float] = 0.025
    MAX_NON_ENGLISH_MARKER_RATIO: ClassVar[float] = 0.02

    def is_english(
        self,
        html: str,
        url: str | None = None,
    ) -> bool:
        """Return True when the downloaded HTML content looks English."""
        del url

        soup = BeautifulSoup(html, "html.parser")

        if self._page_declares_non_english(soup):
            return False

        text = soup.get_text(" ", strip=True)

        if not self._looks_english(text):
            return False

        if self._has_strong_non_english_signal(text):
            return False

        return True

    def _html_lang_is_english(self, soup: BeautifulSoup) -> bool:
        """Return True when the root html lang attribute is English."""
        html_tag = soup.find("html")

        if not isinstance(html_tag, Tag):
            return False

        return is_english_language_value(str(html_tag.get("lang", "")))

    def _meta_locale_is_english(self, soup: BeautifulSoup) -> bool:
        """Return True when language-related meta tags declare English."""
        for selector in self.META_LANGUAGE_SELECTORS:
            tag = soup.select_one(selector)

            if not isinstance(tag, Tag):
                continue

            if is_english_language_value(str(tag.get("content", ""))):
                return True

        return False

    def _page_declares_non_english(self, soup: BeautifulSoup) -> bool:
        """Return True when page-level declarations reject English."""
        html_tag = soup.find("html")

        if isinstance(html_tag, Tag):
            lang = str(html_tag.get("lang", "")).strip()

            if lang and not is_english_language_value(lang):
                return True

        for selector in self.META_LANGUAGE_SELECTORS:
            tag = soup.select_one(selector)

            if not isinstance(tag, Tag):
                continue

            content = str(tag.get("content", "")).strip()

            if content and not is_english_language_value(content):
                return True

        return False

    def _looks_english(self, text: str) -> bool:
        """Return True when text passes baseline English heuristics."""
        cleaned_text = " ".join(text.split())

        if len(cleaned_text) < self.MIN_TEXT_LENGTH:
            return False

        latin_ratio = self._latin_character_ratio(cleaned_text)

        if latin_ratio < self.MIN_LATIN_RATIO:
            return False

        words = self._words(cleaned_text)

        if len(words) < self.MIN_WORD_COUNT:
            return False

        english_hits = sum(1 for word in words if word in self.ENGLISH_STOPWORDS)
        english_ratio = english_hits / len(words)

        return english_ratio >= self.MIN_ENGLISH_STOPWORD_RATIO

    def _has_strong_non_english_signal(self, text: str) -> bool:
        """Return True when markers and stopwords strongly indicate non-English."""
        cleaned_text = " ".join(text.split())

        if not cleaned_text:
            return True

        words = self._words(cleaned_text)

        if not words:
            return True

        marker_ratio = self._non_english_marker_ratio(cleaned_text)

        if marker_ratio > self.MAX_NON_ENGLISH_MARKER_RATIO:
            return True

        non_english_hits = sum(
            1 for word in words if word in self.NON_ENGLISH_STOPWORDS
        )
        non_english_ratio = non_english_hits / len(words)

        if non_english_ratio > self.MAX_NON_ENGLISH_STOPWORD_RATIO:
            english_hits = sum(1 for word in words if word in self.ENGLISH_STOPWORDS)
            return non_english_hits >= english_hits

        return False

    def _words(self, text: str) -> list[str]:
        """Extract lower-cased word tokens from text."""
        return re.findall(r"[a-zA-ZÀ-ÿ]{2,}", text.lower())

    def _latin_character_ratio(self, text: str) -> float:
        """Return the ratio of Latin letters among alphabetic characters."""
        letters = [char for char in text if char.isalpha()]

        if not letters:
            return 0.0

        latin_letters = [
            char
            for char in letters
            if (
                "a" <= char.lower() <= "z"
                or char
                in ("ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖØÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñòóôõöøùúûüýþÿ")
            )
        ]

        return len(latin_letters) / len(letters)

    def _non_english_marker_ratio(self, text: str) -> float:
        """Return ratio of strong non-English marker letters in text."""
        letters = [char for char in text if char.isalpha()]

        if not letters:
            return 0.0

        marker_count = sum(
            1 for char in letters if char in self.NON_ENGLISH_CHARACTER_MARKERS
        )

        return marker_count / len(letters)
