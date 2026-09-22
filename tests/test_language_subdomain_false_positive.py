"""Regression tests for false language detection in ordinary subdomains."""

from __future__ import annotations

from docsync.language import detect_explicit_url_language, is_explicitly_non_english_url


def test_arbitrary_language_code_like_subdomain_is_not_a_locale() -> None:
    url = "https://sw.kovidgoyal.net/kitty/"
    assert detect_explicit_url_language(url) is None
    assert is_explicitly_non_english_url(url) is False


def test_other_short_product_subdomains_are_not_languages() -> None:
    for url in (
        "https://go.example.com/docs/",
        "https://id.example.com/docs/",
        "https://io.example.com/docs/",
        "https://it.example.com/docs/",
        "https://no.example.com/docs/",
        "https://se.example.com/docs/",
    ):
        assert detect_explicit_url_language(url) is None
        assert is_explicitly_non_english_url(url) is False


def test_explicit_language_query_is_still_detected() -> None:
    decision = detect_explicit_url_language("https://example.com/docs/?lang=tr")
    assert decision is not None
    assert decision.language_code == "tr"
    assert decision.source == "url-query"


def test_explicit_language_path_is_still_detected() -> None:
    decision = detect_explicit_url_language("https://example.com/tr/docs/")
    assert decision is not None
    assert decision.language_code == "tr"
    assert decision.source == "url-path"


def test_intl_language_path_is_still_detected() -> None:
    decision = detect_explicit_url_language("https://example.com/intl/de/docs/")
    assert decision is not None
    assert decision.language_code == "de"
    assert decision.source == "url-intl-path"
