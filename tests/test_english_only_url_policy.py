"""Regression tests for requested-language URL policy."""

from __future__ import annotations

import pytest

from docsync.language import LanguagePolicy, detect_explicit_url_language


@pytest.mark.parametrize(
    "url",
    [
        "https://developers.google.com/?hl=de",
        "https://developers.google.com/docs?hl=fr",
        "https://developers.google.com/docs?locale=ja",
        "https://developers.google.com/docs?lang=tr",
        "https://developers.google.com/intl/ko/docs",
        "https://developers.google.com/fr/docs",
        "https://ja.developers.google.com/docs",
    ],
)
def test_explicit_non_english_google_urls_are_rejected(url: str) -> None:
    assert LanguagePolicy("en").should_skip_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://developers.google.com/",
        "https://developers.google.com/docs",
        "https://developers.google.com/docs?hl=en",
        "https://developers.google.com/intl/en/docs",
        "https://en.developers.google.com/docs",
    ],
)
def test_english_google_urls_are_allowed(url: str) -> None:
    assert LanguagePolicy("en").should_skip_url(url) is False


def test_url_language_decision_records_query_source() -> None:
    decision = detect_explicit_url_language("https://developers.google.com/docs?hl=ja")
    assert decision is not None
    assert decision.is_english is False
    assert decision.language_code == "ja"
    assert decision.source == "url-query"
