"""Thin DocsSync policy on top of Crawlee Python."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import signal
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from crawlee import ConcurrencySettings, Glob, service_locator
from crawlee.configuration import Configuration
from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext
from crawlee.request_loaders import ThrottlingRequestManager
from crawlee.storages import RequestQueue
from trafilatura import extract


def _normalize_language(value: str) -> str:
    language = value.strip().lower().replace("_", "-").split("-", 1)[0]
    if len(language) != 2 or not language.isalpha():
        raise ValueError("language must be a two-letter code such as 'en' or 'tr'")
    return language


def _output_path(output_dir: Path, url: str) -> Path:
    parsed = urlsplit(url)
    path = parsed.path.strip("/") or "index"
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", path).strip("-") or "index"
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return output_dir / f"{slug}-{url_hash}.md"


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
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


async def run_crawler(
    *,
    start_url: str,
    output_dir: Path,
    state_dir: Path,
    language: str = "en",
    max_concurrency: int = 2,
    max_requests: int = 10_000,
    requests_per_minute: int = 20,
) -> dict[str, int]:
    """Synchronize one documentation tree using Crawlee's native lifecycle."""

    language = _normalize_language(language)
    output_dir = output_dir.expanduser().resolve()
    state_dir = state_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    hostname = urlsplit(start_url).hostname
    if not hostname or urlsplit(start_url).scheme not in {"http", "https"}:
        raise ValueError("start_url must be an absolute HTTP(S) URL")

    scope_root = start_url.rstrip("/")
    scope_glob = Glob(f"{scope_root}/**")
    scope_id = hashlib.sha256(scope_root.encode("utf-8")).hexdigest()[:12]
    state_file = state_dir / f"{hostname}.json"
    content_state = _load_state(state_file)
    state_lock = asyncio.Lock()

    counters = {"processed": 0, "saved": 0, "unchanged": 0}

    with tempfile.TemporaryDirectory(prefix=f"docsync-{scope_id}-") as crawl_storage:
        configuration = Configuration(
            storage_dir=crawl_storage,
            purge_on_start=True,
        )
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

        crawler = PlaywrightCrawler(
            configuration=configuration,
            event_manager=service_locator.get_event_manager(),
            request_manager=request_manager,
            concurrency_settings=concurrency,
            max_requests_per_crawl=max_requests,
            max_request_retries=2,
            respect_robots_txt_file=True,
        )

        @crawler.router.default_handler
        async def handler(context: PlaywrightCrawlingContext) -> None:
            await context.enqueue_links(
                strategy="same-origin",
                include=[scope_glob],
            )

            text = extract(
                await context.page.content(),
                url=context.request.url,
                output_format="markdown",
                include_comments=False,
                include_links=True,
                include_tables=True,
                target_language=language,
            )
            if not text:
                return
            text = text.strip()

            url = context.request.url
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            target = _output_path(output_dir, url)

            async with state_lock:
                previous = content_state.get(url, {})
                counters["processed"] += 1

                if previous.get("content_hash") == digest and target.exists():
                    counters["unchanged"] += 1
                    status = "unchanged"
                else:
                    target.write_text(text + "\n", encoding="utf-8")
                    counters["saved"] += 1
                    status = "saved"

                content_state[url] = {
                    "content_hash": digest,
                    "filename": target.name,
                }
                _save_state(state_file, content_state)
                print(
                    "docsync [python] "
                    f"processed={counters['processed']} "
                    f"saved={counters['saved']} "
                    f"unchanged={counters['unchanged']} "
                    f"status={status} url={url}",
                    flush=True,
                )

        main_loop = asyncio.get_running_loop()
        crawler_loop: asyncio.AbstractEventLoop | None = None
        crawler_started = asyncio.Event()

        def run_crawler_thread() -> None:
            nonlocal crawler_loop
            crawler_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(crawler_loop)
            main_loop.call_soon_threadsafe(crawler_started.set)
            try:
                crawler_loop.run_until_complete(
                    crawler.run([start_url], purge_request_queue=False)
                )
            finally:
                crawler_loop.close()

        crawl_task = asyncio.create_task(asyncio.to_thread(run_crawler_thread))
        await crawler_started.wait()

        stop_requested = False

        def handle_sigint() -> None:
            nonlocal stop_requested
            if stop_requested or crawler_loop is None:
                return
            stop_requested = True
            print("docsync: stopping gracefully...", flush=True)
            crawler_loop.call_soon_threadsafe(
                crawler.stop,
                "Interrupted by user.",
            )

        main_loop.add_signal_handler(signal.SIGINT, handle_sigint)
        try:
            await crawl_task
        finally:
            main_loop.remove_signal_handler(signal.SIGINT)

    return counters
