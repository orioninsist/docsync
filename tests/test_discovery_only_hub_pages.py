"""Regression coverage for discovery-only documentation hub pages."""

from pathlib import Path

from docsync.crawler import build_scope_pattern, filter_discovered_urls

ROOT = Path(__file__).resolve().parents[1]
CRAWLER_PATH = ROOT / "src" / "docsync" / "crawler.py"


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


def test_adaptive_handler_discovers_before_export() -> None:
    source = CRAWLER_PATH.read_text(encoding="utf-8")
    discovery = source.index("discovered_urls = await discover_and_enqueue_in_scope_links(")
    export = source.index("document = markdown_exporter.export(", discovery)
    assert discovery < export


def test_empty_pages_are_committed_as_terminal_outcomes() -> None:
    source = CRAWLER_PATH.read_text(encoding="utf-8")
    assert '"outcome": "empty"' in source
    assert 'if outcome == "empty":' in source
    assert "stats.empty_pages += 1" in source
    assert "stats.processed += 1" in source


def test_adaptive_renderers_share_one_queue_insertion_path() -> None:
    source = CRAWLER_PATH.read_text(encoding="utf-8")
    assert source.count("await context.enqueue_links(") == 1
    assert "fallback_context" not in source
