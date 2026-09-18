"""Behavioral coverage for shared discovery URL policy."""

from __future__ import annotations

from docsync.crawler import build_scope_pattern, filter_discovered_urls


def test_shared_discovery_policy_filters_and_normalizes_candidates() -> None:
    base_url = "https://example.com/docs/"
    scope_pattern = build_scope_pattern(base_url)

    urls = [
        base_url,
        "https://example.com/docs/guide",
        "https://example.com/docs/guide#section",
        "https://example.com/docs/manual.pdf",
        "https://example.com/outside",
        "https://other.example/docs/guide",
        "mailto:docs@example.com",
        "https://example.com/docs/fr/guide",
    ]

    assert filter_discovered_urls(
        urls=urls,
        base_url=base_url,
        scope_pattern=scope_pattern,
        should_skip_url=lambda url: "/fr/" in url,
    ) == ["https://example.com/docs/guide"]


def test_shared_discovery_policy_deduplicates_normalized_urls() -> None:
    base_url = "https://example.com/docs/"
    scope_pattern = build_scope_pattern(base_url)

    assert filter_discovered_urls(
        urls=[
            "https://example.com/docs/guide#one",
            "https://example.com/docs/guide#two",
            "https://example.com/docs/guide",
        ],
        base_url=base_url,
        scope_pattern=scope_pattern,
        should_skip_url=lambda _url: False,
    ) == ["https://example.com/docs/guide"]
