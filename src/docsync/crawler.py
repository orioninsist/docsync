"""Thin DocsSync policy on top of Crawlee Python."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from pathlib import Path

from camoufox import AsyncNewBrowser
from crawlee import ConcurrencySettings, Glob, service_locator
from crawlee.browsers import BrowserPool, PlaywrightBrowserController, PlaywrightBrowserPlugin
from crawlee.configuration import Configuration
from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext
from crawlee.events import LocalEventManager
from crawlee.request_loaders import ThrottlingRequestManager
from crawlee.storage_clients import FileSystemStorageClient
from crawlee.storages import RequestQueue
from html_to_markdown import convert
from typing_extensions import override

from docsync.policy import (
    NORMALIZE_DOCUMENT,
    default_output_dir,
    default_state_dir,
    hostname_for_url,
    normalize_language,
    output_path,
    scope_root,
)


def _load_state(path: Path) -> dict[str, dict[str, str]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _save_state(path: Path, state: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _to_gfm(html: str) -> str:
    result = convert(html)
    return result.content.strip() if result.content else ""


def _load_checkpoint(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _save_checkpoint(path: Path, checkpoint: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(checkpoint, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _prepare_crawl_storage(
    state_dir: Path,
    *,
    start_url: str,
    language: str,
    restart: bool = False,
) -> tuple[Path, Path, bool]:
    crawl_dir = state_dir / "crawl" / "python"
    storage_dir = crawl_dir / "storage"
    checkpoint_file = crawl_dir / "checkpoint.json"
    checkpoint = _load_checkpoint(checkpoint_file)

    resume = (
        not restart
        and checkpoint.get("version") == 1
        and checkpoint.get("status") == "running"
        and checkpoint.get("start_url") == start_url
        and checkpoint.get("language") == language
        and storage_dir.exists()
    )

    if not resume:
        shutil.rmtree(storage_dir, ignore_errors=True)

    storage_dir.mkdir(parents=True, exist_ok=True)
    _save_checkpoint(
        checkpoint_file,
        {
            "version": 1,
            "status": "running",
            "engine": "python",
            "start_url": start_url,
            "language": language,
        },
    )
    return storage_dir, checkpoint_file, resume


async def run_crawler(
    *,
    start_url: str,
    output_dir: Path | None,
    state_dir: Path | None,
    language: str = "en",
    max_concurrency: int = 2,
    max_requests: int = 10_000,
    requests_per_minute: int = 20,
    headful: bool = False,
    restart: bool = False,
) -> dict[str, int]:
    """Synchronize one documentation tree using Crawlee's native lifecycle."""
    language = normalize_language(language)
    output_dir = (output_dir or default_output_dir(start_url)).expanduser().resolve()
    state_dir = (state_dir or default_state_dir(start_url)).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    hostname = hostname_for_url(start_url)
    crawl_scope_root = scope_root(start_url)
    scope_glob = Glob(f"{crawl_scope_root}/**")
    state_file = state_dir / f"{hostname}.json"
    content_state = _load_state(state_file)
    state_lock = asyncio.Lock()
    counters = {"processed": 0, "saved": 0, "unchanged": 0}

    crawl_storage, checkpoint_file, resume = _prepare_crawl_storage(
        state_dir,
        start_url=start_url,
        language=language,
        restart=restart,
    )
    configuration = Configuration(
        storage_dir=str(crawl_storage),
        purge_on_start=not resume,
    )

    storage_client = FileSystemStorageClient()
    event_manager = LocalEventManager.from_config(configuration)
    service_locator.set_configuration(configuration)
    service_locator.set_storage_client(storage_client)
    service_locator.set_event_manager(event_manager)

    queue = await RequestQueue.open(
        configuration=configuration,
        storage_client=storage_client,
    )
    request_manager = ThrottlingRequestManager(
        queue,
        domains=[hostname],
        request_manager_opener=RequestQueue.open,
    )
    concurrency = ConcurrencySettings(
        min_concurrency=1,
        desired_concurrency=max_concurrency,
        max_concurrency=max_concurrency,
        max_tasks_per_minute=requests_per_minute,
    )
    browser_launch_options = (
        {"args": ["--no-sandbox"]}
        if os.environ.get("DOCSYNC_NO_SANDBOX") == "1"
        else None
    )
    protected_site = hostname == "docs.phaser.io"
    browser_pool = (
        BrowserPool(
            plugins=[
                _CamoufoxPlugin(
                    browser_launch_options={"headless": not headful},
                )
            ]
        )
        if protected_site
        else None
    )
    crawler = PlaywrightCrawler(
        configuration=configuration,
        event_manager=event_manager,
        storage_client=storage_client,
        browser_pool=browser_pool,
        headless=None if protected_site else not headful,
        use_incognito_pages=None if protected_site else headful,
        browser_launch_options=None if protected_site else browser_launch_options,
        request_manager=request_manager,
        concurrency_settings=concurrency,
        max_requests_per_crawl=max_requests,
        max_request_retries=2,
        retry_on_blocked=True,
        respect_robots_txt_file=True,
    )

    @crawler.router.default_handler
    async def handler(context: PlaywrightCrawlingContext) -> None:
        page_language = await context.page.evaluate(
            "() => document.documentElement.lang || ''"
        )
        should_process = (
            not page_language or normalize_language(page_language) == language
        )
        html = (
            await context.page.evaluate(NORMALIZE_DOCUMENT) if should_process else None
        )
        markdown = await asyncio.to_thread(_to_gfm, html) if html else ""

        if markdown:
            url = context.page.url
            digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
            target = output_path(output_dir, url)
            target.parent.mkdir(parents=True, exist_ok=True)
            async with state_lock:
                previous = content_state.get(url, {})
                counters["processed"] += 1
                if previous.get("content_hash") == digest and target.exists():
                    counters["unchanged"] += 1
                else:
                    target.write_text(markdown + "\n", encoding="utf-8")
                    counters["saved"] += 1
                content_state[url] = {
                    "content_hash": digest,
                    "filename": target.name,
                }
                _save_state(state_file, content_state)

        await context.enqueue_links(strategy="same-origin", include=[scope_glob])

    statistics = await crawler.run([start_url], purge_request_queue=False)

    stopped_at_request_limit = statistics.requests_total >= max_requests
    if not stopped_at_request_limit and await queue.is_finished():
        _save_checkpoint(
            checkpoint_file,
            {
                "version": 1,
                "status": "complete",
                "engine": "python",
                "start_url": start_url,
                "language": language,
            },
        )

    return counters