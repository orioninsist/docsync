"""Regression tests for the permanent English-only URL policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from docsync.crawler import build_scope_pattern, filter_discovered_urls
from docsync.language import detect_explicit_url_language
from docsync.language_strategy import LanguageStrategy

ROOT = Path(__file__).resolve().parents[1]
CRAWLER_PATH = ROOT / "src/docsync/crawler.py"


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
    strategy = LanguageStrategy("en")

    assert strategy.should_skip_url(url) is True


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
    strategy = LanguageStrategy("en")

    assert strategy.should_skip_url(url) is False


def test_url_language_decision_records_query_source() -> None:
    decision = detect_explicit_url_language("https://developers.google.com/docs?hl=ja")

    assert decision is not None
    assert decision.is_english is False
    assert decision.language_code == "ja"
    assert decision.source == "url-query"


def test_discovery_policy_rejects_explicit_non_english_urls() -> None:
    strategy = LanguageStrategy("en")
    scope_pattern = build_scope_pattern("https://developers.google.com")

    assert filter_discovered_urls(
        urls=[
            "https://developers.google.com/docs/english",
            "https://developers.google.com/docs/german?hl=de",
            "https://developers.google.com/intl/ja/docs/japanese",
            "https://developers.google.com/fr/docs/french",
        ],
        base_url="https://developers.google.com",
        scope_pattern=scope_pattern,
        should_skip_url=strategy.should_skip_url,
    ) == ["https://developers.google.com/docs/english"]


def test_adaptive_renderers_use_the_same_filtered_url_list() -> None:
    source = CRAWLER_PATH.read_text(encoding="utf-8")

    assert "await context.extract_links(" in source
    assert "await context.enqueue_links(" in source
    assert "await queue_context.add_requests(" not in source
    assert "fallback_context" not in source
    assert "should_skip_url=language_strategy.should_skip_url" in source


