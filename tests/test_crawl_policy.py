from __future__ import annotations

from docsync.cli import build_parser
from docsync.policy import NORMALIZE_DOCUMENT


def test_web_crawl_defaults_are_unlimited_and_sitemap_enabled() -> None:
    args = build_parser().parse_args(["sync", "https://example.com/docs"])
    assert args.max_requests is None
    assert args.crawl_strategy == "same-origin"
    assert args.no_sitemap is False


def test_web_crawl_can_set_explicit_limit_scope_and_disable_sitemap() -> None:
    args = build_parser().parse_args(
        [
            "sync",
            "https://example.com/docs",
            "--max-requests",
            "250",
            "--crawl-strategy",
            "same-domain",
            "--no-sitemap",
        ]
    )
    assert args.max_requests == 250
    assert args.crawl_strategy == "same-domain"
    assert args.no_sitemap is True


def test_document_normalizer_preserves_semantic_asides_and_role_buttons() -> None:
    assert "nav,aside" not in NORMALIZE_DOCUMENT
    assert '[role="button"]' not in NORMALIZE_DOCUMENT
