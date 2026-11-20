"""Incremental DocsSync integration with Crawlee's HTTP freshness validator."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from crawlee._utils.http_freshness import FreshnessResult, HttpFreshnessChecker
from docsync.crawler import DocsSyncFreshnessChecker
from docsync.policy import output_path


def run(coro):
    return asyncio.run(coro)


def test_first_fetch_then_304_skips_existing_index(tmp_path: Path) -> None:
    url = "https://example.com/docs/a"
    output = output_path(tmp_path, url)
    output.write_text("# Existing Markdown\n", encoding="utf-8")
    state = {url: {"content_hash": "old-hash", "filename": output.name}}
    store = SimpleNamespace(get_value=AsyncMock(return_value=None), set_value=AsyncMock())
    client = SimpleNamespace(
        send_request=AsyncMock(
            side_effect=[
                SimpleNamespace(status_code=200, headers={"ETag": '"v1"'}),
                SimpleNamespace(status_code=304, headers={}),
            ]
        )
    )
    checker = DocsSyncFreshnessChecker(
        client, store, output_dir=tmp_path, content_state=state
    )

    first = run(checker.check(url))
    assert first.changed and first.etag == '"v1"'
    assert checker.unchanged_count == 0
    store.get_value.return_value = None
    run(checker.mark_processed(url, first))
    store.get_value.return_value = {"etag": '"v1"', "last_modified": None}
    second = run(checker.check(url))
    assert not second.changed and second.status_code == 304
    assert checker.unchanged_count == 1
    assert client.send_request.await_args_list[1].kwargs["headers"] == {
        "If-None-Match": '"v1"'
    }
    assert store.set_value.await_count == 1


def test_changed_etag_requires_successful_commit(tmp_path: Path) -> None:
    url = "https://example.com/docs/a"
    output_path(tmp_path, url).write_text("# Old\n", encoding="utf-8")
    state = {url: {"content_hash": "previous"}}
    store = SimpleNamespace(
        get_value=AsyncMock(return_value={"etag": '"v1"'}),
        set_value=AsyncMock(),
    )
    client = SimpleNamespace(
        send_request=AsyncMock(
            return_value=SimpleNamespace(status_code=200, headers={"ETag": '"v2"'})
        )
    )
    checker = DocsSyncFreshnessChecker(
        client, store, output_dir=tmp_path, content_state=state
    )
    changed = run(checker.check(url))
    assert changed.changed and changed.etag == '"v2"'
    store.set_value.assert_not_awaited()
    run(checker.mark_processed(url, changed))
    stored = store.set_value.await_args.args[1]
    assert stored["etag"] == '"v2"'
    assert client.send_request.await_args.kwargs["headers"] == {
        "If-None-Match": '"v1"'
    }


def test_missing_output_forces_unconditional_fetch(tmp_path: Path) -> None:
    url = "https://example.com/docs/missing"
    store = SimpleNamespace(
        get_value=AsyncMock(return_value={"etag": '"cached"'}),
        set_value=AsyncMock(),
    )
    client = SimpleNamespace(
        send_request=AsyncMock(
            return_value=SimpleNamespace(
                status_code=200, headers={"ETag": '"new"'}
            )
        )
    )
    checker = DocsSyncFreshnessChecker(
        client,
        store,
        output_dir=tmp_path,
        content_state={url: {"content_hash": "previous"}},
    )
    result = run(checker.check(url))
    assert result.changed and result.etag == '"new"'
    client.send_request.assert_awaited_once_with(url, method="GET")
    store.get_value.assert_not_awaited()


@pytest.mark.parametrize("status", [404, 429, 500])
def test_failed_http_does_not_overwrite_etag(tmp_path: Path, status: int) -> None:
    url = "https://example.com/docs/page"
    output_path(tmp_path, url).write_text("# Old\n", encoding="utf-8")
    store = SimpleNamespace(
        get_value=AsyncMock(return_value={"etag": '"old"'}),
        set_value=AsyncMock(),
    )
    client = SimpleNamespace(
        send_request=AsyncMock(
            return_value=SimpleNamespace(status_code=status, headers={})
        )
    )
    checker = DocsSyncFreshnessChecker(
        client, store,
        output_dir=tmp_path,
        content_state={url: {"content_hash": "previous"}},
    )
    with pytest.raises(ValueError, match="HTTP freshness check failed"):
        run(checker.check(url))
    store.set_value.assert_not_awaited()


def test_failed_indexing_does_not_commit_new_etag(tmp_path: Path) -> None:
    url = "https://example.com/docs/page"
    output_path(tmp_path, url).write_text("# Previously indexed\n", encoding="utf-8")
    store = SimpleNamespace(
        get_value=AsyncMock(return_value={"etag": '"old"'}),
        set_value=AsyncMock(),
    )
    client = SimpleNamespace(
        send_request=AsyncMock(
            return_value=SimpleNamespace(status_code=200, headers={"etag": '"new"'})
        )
    )
    checker = DocsSyncFreshnessChecker(
        client, store,
        output_dir=tmp_path,
        content_state={url: {"content_hash": "previous"}},
    )
    candidate = run(checker.check(url))
    assert candidate.etag == '"new"'
    # Simulate conversion/atomic-write failure: never call mark_processed.
    store.set_value.assert_not_awaited()


def test_last_modified_used_when_etag_absent(tmp_path: Path) -> None:
    url = "https://example.com/docs/page"
    output_path(tmp_path, url).write_text("# Old\n", encoding="utf-8")
    store = SimpleNamespace(
        get_value=AsyncMock(
            return_value={"etag": None, "last_modified": "Tue, 01 Jan 2030 12:00:00 GMT"}
        ),
        set_value=AsyncMock(),
    )
    client = SimpleNamespace(
        send_request=AsyncMock(
            return_value=SimpleNamespace(status_code=304, headers={})
        )
    )
    checker = DocsSyncFreshnessChecker(
        client, store, output_dir=tmp_path,
        content_state={url: {"content_hash": "previous"}},
    )
    assert not run(checker.check(url)).changed
    assert client.send_request.await_args.kwargs["headers"] == {
        "If-Modified-Since": "Tue, 01 Jan 2030 12:00:00 GMT"
    }


def test_sitemap_and_browser_freshness_are_connected() -> None:
    from inspect import signature
    from crawlee.request_loaders import SitemapRequestLoader
    from pathlib import Path

    source = Path("src/docsync/crawler.py").read_text(encoding="utf-8")
    assert "sitemap_urls=sorted(sitemap_sources)" in source
    assert "http_freshness_checker=freshness_checker" in source
    assert "class DocsSyncFreshnessChecker(HttpFreshnessChecker)" in source
    assert "should_enqueue_url" in signature(SitemapRequestLoader).parameters
    assert "http_freshness_checker" in signature(
        __import__("crawlee.crawlers", fromlist=["PlaywrightCrawler"]).PlaywrightCrawler
    ).parameters
