"""Thin DocsSync policy on top of Crawlee Python."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import tempfile
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from crawlee import ConcurrencySettings, Request, RequestOptions
from crawlee._service_locator import ServiceLocator
from crawlee._utils.robots import RobotsTxtFile
from crawlee._utils.sitemap import Sitemap
from crawlee.configuration import Configuration
from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext
from crawlee.events import LocalEventManager
from crawlee.http_clients import ImpitHttpClient
from crawlee.request_loaders import (
    RequestManager,
    SitemapRequestLoader,
    ThrottlingRequestManager,
)
from crawlee.storage_clients import FileSystemStorageClient
from crawlee.storages import RequestQueue

from docsync.html_archive import archive_html
from docsync.pandoc_converter import html_to_gfm
from docsync.policy import (
    NORMALIZE_DOCUMENT,
    canonicalize_url,
    default_output_dir,
    default_state_dir,
    hostname_for_url,
    normalize_language,
    output_path,
    url_is_within_start_scope,
    url_matches_language,
)


def _atomic_write(path: Path, content: str) -> None:
    """Atomically replace a UTF-8 file after syncing its contents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _load_state(path: Path) -> dict[str, dict[str, str]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _save_state(path: Path, state: dict[str, dict[str, str]]) -> None:
    _atomic_write(
        path,
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _to_gfm(html: str) -> str:
    return html_to_gfm(html)


def _load_checkpoint(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _save_checkpoint(path: Path, checkpoint: dict[str, object]) -> None:
    _atomic_write(
        path,
        json.dumps(checkpoint, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


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
    crawl_strategy: Literal[
        "all", "same-domain", "same-hostname", "same-origin"
    ] = "same-origin",
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

    def transform_request(
        options: RequestOptions,
    ) -> RequestOptions | Literal["skip", "unchanged"]:
        url = canonicalize_url(options["url"])
        if not url_is_within_start_scope(start_url, url) or not url_matches_language(
            url, language
        ):
            return "skip"
        options["url"] = url
        return options

    async with AsyncExitStack() as sitemap_stack:
        active_request_manager: RequestManager = request_manager

        if discover_sitemap:
            parsed_start = urlsplit(start_url)
            origin = f"{parsed_start.scheme}://{parsed_start.netloc}"

            http_client = ImpitHttpClient()
            await http_client.__aenter__()
            sitemap_stack.push_async_callback(http_client.cleanup)
            sitemap_sources: set[str] = set()

            try:
                robots = await RobotsTxtFile.find(start_url, http_client)
                sitemap_sources.update(
                    robots.get_sitemaps(enqueue_strategy=crawl_strategy)
                )
            except Exception as exc:
                print(f"Unable to discover sitemaps from robots.txt: {exc}")

            if sitemap_sources:
                sitemap_loader = await sitemap_stack.enter_async_context(
                    SitemapRequestLoader(
                        sitemap_urls=sorted(sitemap_sources),
                        http_client=http_client,
                        enqueue_strategy=crawl_strategy,
                        transform_request_function=transform_request,
                    )
                )
                # Route sitemap requests through the native domain queue.
                while True:
                    sitemap_request = await sitemap_loader.fetch_next_request()
                    if sitemap_request is None:
                        if await sitemap_loader.is_finished():
                            break
                        raise RuntimeError(
                            "Sitemap loader returned no request before completion"
                        )

                    await active_request_manager.add_request(sitemap_request)
                    await sitemap_loader.mark_request_as_handled(sitemap_request)

            try:
                common_sitemap = await Sitemap.try_common_names(origin, http_client)
                for url in common_sitemap.urls:
                    canonical_url = canonicalize_url(url)
                    if not url_is_within_start_scope(
                        start_url, canonical_url
                    ) or not url_matches_language(canonical_url, language):
                        continue
                    request = Request.from_url(
                        canonical_url,
                        enqueue_strategy=crawl_strategy,
                    )
                    await active_request_manager.add_request(request)
            except Exception as exc:
                print(f"Unable to discover common sitemaps: {exc}")

        if discover_sitemap:
            robots_policy = await RobotsTxtFile.find(start_url, http_client)
            crawl_delay = robots_policy.get_crawl_delay(user_agent="*")
            if crawl_delay is not None:
                request_manager.set_crawl_delay(start_url, crawl_delay)

        crawler = PlaywrightCrawler(
            configuration=configuration,
            event_manager=event_manager,
            storage_client=storage_client,
            headless=not headful,
            use_incognito_pages=headful,
            browser_launch_options=browser_launch_options,
            request_manager=active_request_manager,
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
            if should_process:
                original_html = await context.page.content()
                await asyncio.to_thread(
                    archive_html,
                    original_html,
                    state_dir=state_dir,
                )
                html = await context.page.evaluate(NORMALIZE_DOCUMENT)
            else:
                html = None

            markdown = await asyncio.to_thread(_to_gfm, html) if html else ""

            if markdown:
                url = canonicalize_url(context.page.url)
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
                        _atomic_write(target, markdown + "\n")
                        counters["saved"] += 1
                    content_state[url] = {
                        "content_hash": digest,
                        "filename": target.name,
                    }
                    _save_state(state_file, content_state)

            await context.enqueue_links(
                strategy=crawl_strategy,
                transform_request_function=transform_request,
            )

        statistics = await crawler.run(
            [canonicalize_url(start_url)],
            purge_request_queue=False,
        )

        stopped_at_request_limit = (
            max_requests is not None and statistics.requests_total >= max_requests
        )
        crawl_complete = (
            not stopped_at_request_limit and await active_request_manager.is_finished()
        )
    if crawl_complete:
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
