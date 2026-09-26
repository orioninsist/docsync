"""Thin DocsSync policy on top of Crawlee Python."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from pathlib import Path

from crawlee import ConcurrencySettings, Glob, service_locator
from crawlee.configuration import Configuration
from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext
from crawlee.request_loaders import ThrottlingRequestManager
from crawlee.storages import RequestQueue
from html_to_markdown import convert

from docsync.policy import (
    NORMALIZE_DOCUMENT,
    default_output_dir,
    default_state_dir,
    hostname_for_url,
    normalize_language,
    output_path,
    scope_id,
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


async def run_crawler(
    *,
    start_url: str,
    output_dir: Path | None,
    state_dir: Path | None,
    language: str = "en",
    max_concurrency: int = 2,
    max_requests: int = 10_000,
    requests_per_minute: int = 20,
) -> dict[str, int]:
    """Synchronize one documentation tree using Crawlee's native lifecycle."""
    language = normalize_language(language)
    output_dir = (output_dir or default_output_dir(start_url)).expanduser().resolve()
    state_dir = (state_dir or default_state_dir(start_url)).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    hostname = hostname_for_url(start_url)
    crawl_scope_root = scope_root(start_url)
    crawl_scope_id = scope_id(start_url)
    scope_glob = Glob(f"{crawl_scope_root}/**")
    state_file = state_dir / f"{hostname}.json"
    content_state = _load_state(state_file)
    state_lock = asyncio.Lock()
    counters = {"processed": 0, "saved": 0, "unchanged": 0}

    with tempfile.TemporaryDirectory(
        prefix=f"docsync-{crawl_scope_id}-"
    ) as crawl_storage:
        configuration = Configuration(storage_dir=crawl_storage, purge_on_start=True)
        service_locator.set_configuration(configuration)
        queue = await RequestQueue.open()
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
        crawler = PlaywrightCrawler(
            configuration=configuration,
            browser_launch_options=browser_launch_options,
            event_manager=service_locator.get_event_manager(),
            request_manager=request_manager,
            concurrency_settings=concurrency,
            max_requests_per_crawl=max_requests,
            max_request_retries=2,
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
                await context.page.evaluate(NORMALIZE_DOCUMENT)
                if should_process
                else None
            )
            markdown = await asyncio.to_thread(_to_gfm, html) if html else ""

            if markdown:
                url = context.page.url
                digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
                target = output_path(output_dir, url)
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

        await crawler.run([start_url], purge_request_queue=False)

    return counters
