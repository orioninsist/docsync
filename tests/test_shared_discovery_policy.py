"""Behavioral coverage for DocsSync discovery request policy."""

from __future__ import annotations

from typing import cast

from crawlee import RequestOptions

from docsync.crawler import transform_discovered_request


def transform(url: str, *, skip=lambda _url: False) -> RequestOptions | str:
    return cast(
        RequestOptions | str,
        transform_discovered_request(
            RequestOptions(url=url),
            should_skip_url=skip,
        ),
    )


def test_discovery_policy_normalizes_valid_candidate() -> None:
    result = transform("https://example.com/docs/guide#section")
    assert result != "skip"
    assert cast(RequestOptions, result)["url"] == "https://example.com/docs/guide"


def test_discovery_policy_skips_invalid_and_language_urls() -> None:
    assert transform("mailto:docs@example.com") == "skip"
    assert (
        transform(
            "https://example.com/docs/fr/guide",
            skip=lambda candidate: "/fr/" in candidate,
        )
        == "skip"
    )
