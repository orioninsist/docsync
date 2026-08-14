"""Structural contracts for crawler live progress event wiring."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRAWLER_PATH = ROOT / "src" / "docsync" / "crawler.py"


def _source() -> str:
    return CRAWLER_PATH.read_text(encoding="utf-8")


def _tree() -> ast.Module:
    return ast.parse(
        _source(),
        filename=str(CRAWLER_PATH),
    )


def test_run_crawler_accepts_event_sink() -> None:
    run_crawler = next(
        node
        for node in _tree().body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_crawler"
    )

    parameters = {argument.arg for argument in run_crawler.args.args}

    assert "event_sink" in parameters


def test_crawler_emits_live_events() -> None:
    source = _source()

    assert "CrawlEvent" in source
    assert "CrawlEventSink" in source
    assert "def emit_event(" in source
    assert 'phase="Discovering sitemaps"' in source
    assert 'phase="Downloading"' in source
    assert 'phase="Extracting"' in source
    assert 'phase="Request failed"' in source
    assert 'phase="Finalizing"' in source


def test_crawler_tracks_active_requests() -> None:
    source = _source()

    assert "active_requests = 0" in source
    assert "active_requests += 1" in source
    assert "active_requests - 1" in source
    assert "nonlocal active_requests" in source


def test_crawler_emits_sitemap_and_queue_information() -> None:
    source = _source()

    assert "sitemap_urls=stats.sitemap_urls" in source
    assert "sitemap_files_checked=stats.sitemap_files_checked" in source
    assert "sitemap_files_found=stats.sitemap_files_found" in source
    assert "sitemap_errors=stats.sitemap_errors" in source
    assert "discovered=len(initial_urls)" in source
    assert "queued=len(incremental_urls)" in source
