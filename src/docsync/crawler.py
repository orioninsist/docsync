"""Thin DocsSync policy on top of Crawlee Python."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit

from crawlee import ConcurrencySettings
from crawlee._service_locator import ServiceLocator
from crawlee.configuration import Configuration
from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext
from crawlee.events import LocalEventManager
from crawlee.http_clients import ImpitHttpClient
from crawlee.request_loaders import SitemapRequestLoader, ThrottlingRequestManager
from crawlee.storage_clients import FileSystemStorageClient
from crawlee.storages import RequestQueue
from html_to_markdown import convert

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
    max_requests: int | None = None,
    requests_per_minute: int = 20,
    crawl_strategy: str = "same-origin",
    discover_sitemap: bool = True,
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
    state_file = state_dir / f"{hostname}.json"
    content_state = _load_state(state_file)
    state_lock = asyncio.Lock()
    counters = {"processed": 0, "saved": 0, "unchanged": 0}
    seen_urls: set[str] = set()

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
    crawl_services = ServiceLocator(
        configuration=configuration,
        event_manager=event_manager,
        storage_client=storage_client,
    )

    queue = await RequestQueue.open(
        configuration=configuration,
        storage_client=storage_client,
    )
    request_manager = ThrottlingRequestManager(
        queue,
        domains=[hostname],
        request_manager_opener=RequestQueue.open,
        service_locator=crawl_services,
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
    crawler = PlaywrightCrawler(
        configuration=configuration,
        event_manager=event_manager,
        storage_client=storage_client,
        headless=not headful,
        use_incognito_pages=headful,
        browser_launch_options=browser_launch_options,
        request_manager=request_manager,
        concurrency_settings=concurrency,
        max_requests_per_crawl=max_requests,
        max_request_retries=2,
        retry_on_blocked=True,
        respect_robots_txt_file=True,
    )

    @crawler.router.default_handler
    async def handler(context: PlaywrightCrawlingContext) -> None:
        await context.page.locator("main, article, body").first.wait_for(
            state="attached", timeout=5_000
        )
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
                seen_urls.add(url)
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

        await context.enqueue_links(strategy=crawl_strategy)

    if discover_sitemap:
        parsed_start = urlsplit(start_url)
        sitemap_url = f"{parsed_start.scheme}://{parsed_start.netloc}/sitemap.xml"
        with suppress(Exception):
            async with ImpitHttpClient() as http_client, SitemapRequestLoader(
                sitemap_urls=[sitemap_url],
                http_client=http_client,
                enqueue_strategy=crawl_strategy,
            ) as sitemap_loader:
                while request := await sitemap_loader.fetch_next_request():
                    await queue.add_request(request)
                    await sitemap_loader.mark_request_as_handled(request)

    statistics = await crawler.run([start_url], purge_request_queue=False)

    stopped_at_request_limit = (
        max_requests is not None and statistics.requests_total >= max_requests
    )
    crawl_complete = not stopped_at_request_limit and await queue.is_finished()
    if crawl_complete:
        if not resume:
            stale_urls = set(content_state) - seen_urls
            for stale_url in stale_urls:
                stale = content_state.pop(stale_url)
                filename = stale.get("filename")
                if filename:
                    (output_dir / filename).unlink(missing_ok=True)
            if stale_urls:
                _save_state(state_file, content_state)

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
