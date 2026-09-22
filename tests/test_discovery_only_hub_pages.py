"""Regression coverage for discovery-only documentation hub pages."""

from docsync.crawler import build_scope_pattern, filter_discovered_urls


def test_discovered_urls_are_normalized_and_filtered() -> None:
    scope_pattern = build_scope_pattern("https://support.google.com/youtube")
    assert filter_discovered_urls(
        urls=[
            "https://support.google.com/youtube/topic/9257404?hl=en",
            "https://support.google.com/youtube/topic/9257404?hl=en#section",
            "https://support.google.com/youtube/article/123",
            "https://support.google.com/accounts/login",
            "https://example.com/youtube/outside",
            "https://support.google.com/youtube/file.pdf",
        ],
        base_url="https://support.google.com/youtube",
        scope_pattern=scope_pattern,
        should_skip_url=lambda _url: False,
    ) == [
        "https://support.google.com/youtube/topic/9257404?hl=en",
        "https://support.google.com/youtube/article/123",
    ]

