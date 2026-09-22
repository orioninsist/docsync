"""Behavioral coverage for DocsSync discovery request policy."""

from __future__ import annotations

from crawlee import RequestOptions

from docsync.crawler import build_scope_pattern, transform_discovered_request


def transform(url: str, *, base_url: str, skip=lambda _url: False) -> RequestOptions | str:
    return transform_discovered_request(
        RequestOptions(url=url),
        base_url=base_url,
        scope_pattern=build_scope_pattern(base_url),
        should_skip_url=skip,
    )


def test_discovery_policy_normalizes_valid_candidate() -> None:
    result = transform(
        "https://example.com/docs/guide#section",
        base_url="https://example.com/docs/",
    )
    assert result != "skip"
    assert result["url"] == "https://example.com/docs/guide"


def test_discovery_policy_skips_out_of_scope_assets_and_language_urls() -> None:
    base_url = "https://example.com/docs/"
    for url in (
        base_url,
        "https://example.com/docs/manual.pdf",
        "https://example.com/outside",
        "https://other.example/docs/guide",
        "mailto:docs@example.com",
        "https://example.com/docs/fr/guide",
    ):
        result = transform(
            url,
            base_url=base_url,
            skip=lambda candidate: "/fr/" in candidate,
        )
        assert result == "skip"
