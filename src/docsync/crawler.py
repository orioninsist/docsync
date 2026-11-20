"""Thin DocsSync policy on top of Crawlee Python."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import tempfile
import time
from contextlib import AsyncExitStack, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from crawlee import ConcurrencySettings, Request, RequestOptions
from crawlee._service_locator import ServiceLocator
from crawlee._utils.http_freshness import FreshnessResult, HttpFreshnessChecker
from crawlee._utils.robots import RobotsTxtFile
from crawlee._utils.sitemap import Sitemap
from crawlee.configuration import Configuration
from crawlee.crawlers import (
    BasicCrawlingContext,
    PlaywrightCrawler,
    PlaywrightCrawlingContext,
    PlaywrightPreNavCrawlingContext,
)
from crawlee.errors import HttpClientStatusCodeError
from crawlee.events import LocalEventManager
from crawlee.http_clients import ImpitHttpClient
from crawlee.request_loaders import (
    RequestManager,
    SitemapRequestLoader,
    ThrottlingRequestManager,
)
from crawlee.storage_clients import FileSystemStorageClient
from crawlee.storages import KeyValueStore, RequestQueue
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

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


def _write_failed_report(checkpoint_file: Path) -> None:
    """Write an atomic, machine-readable report of unresolved requests."""
    checkpoint = _load_checkpoint(checkpoint_file)
    raw_keys = checkpoint.get("failed_keys", [])
    raw_details = checkpoint.get("failed_details", {})
    raw_cooldowns = checkpoint.get("failed_cooldowns", {})

    keys = (
        sorted(key for key in raw_keys if isinstance(key, str))
        if isinstance(raw_keys, list)
        else []
    )
    details = raw_details if isinstance(raw_details, dict) else {}
    cooldowns = raw_cooldowns if isinstance(raw_cooldowns, dict) else {}

    entries = []
    for key in keys:
        detail = details.get(key, {})
        if not isinstance(detail, dict):
            detail = {}

        url = detail.get("url", key)
        status_code = detail.get("status_code")
        failed_at = detail.get("failed_at")
        retry_at = cooldowns.get(key)

        entries.append(
            {
                "unique_key": key,
                "url": url if isinstance(url, str) else key,
                "status_code": (
                    status_code
                    if isinstance(status_code, int)
                    and not isinstance(status_code, bool)
                    else None
                ),
                "failed_at": (failed_at if isinstance(failed_at, str) else None),
                "retry_at": (retry_at if isinstance(retry_at, str) else None),
            }
        )

    report = {
        "version": 1,
        "start_url": checkpoint.get("start_url"),
        "language": checkpoint.get("language"),
        "failed_count": len(entries),
        "failed_urls": entries,
    }
    _atomic_write(
        checkpoint_file.with_name("failed-urls.json"),
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
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

    failed_keys = checkpoint.get("failed_keys", []) if resume else []
    failed_cooldowns = checkpoint.get("failed_cooldowns", {}) if resume else {}
    failed_details = checkpoint.get("failed_details", {}) if resume else {}
    if not isinstance(failed_details, dict):
        failed_details = {}
    if not isinstance(failed_cooldowns, dict):
        failed_cooldowns = {}
    if not isinstance(failed_keys, list):
        failed_keys = []

    storage_dir.mkdir(parents=True, exist_ok=True)
    _save_checkpoint(
        checkpoint_file,
        {
            "version": 1,
            "status": "running",
            "engine": "python",
            "start_url": start_url,
            "language": language,
            "failed_keys": failed_keys,
            "failed_cooldowns": failed_cooldowns,
            "failed_details": failed_details,
        },
    )
    _write_failed_report(checkpoint_file)
    return storage_dir, checkpoint_file, resume


class DocsSyncFreshnessChecker(HttpFreshnessChecker):
    """Avoid trusting HTTP 304 if the successfully indexed output is missing."""

    def __init__(
        self,
        http_client: ImpitHttpClient,
        store: KeyValueStore,
        *,
        output_dir: Path,
        content_state: dict[str, dict[str, str]],
    ) -> None:
        super().__init__(http_client, store)
        self._output_dir = output_dir
        self._content_state = content_state
        self.unchanged_count = 0

    async def check(self, url: str) -> FreshnessResult:
        canonical_url = canonicalize_url(url)
        record = self._content_state.get(canonical_url, {})
        target = output_path(self._output_dir, canonical_url)
        if not record.get("content_hash") or not target.is_file():
            # No valid document: bypass cached validators and fetch unconditionally.
            response = await self._http_client.send_request(url, method="GET")
            status = response.status_code
            if not 200 <= status < 300:
                raise ValueError(f"HTTP freshness check failed for {url}: {status}")
            headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
            return FreshnessResult(
                changed=True,
                status_code=status,
                etag=headers.get("etag"),
                last_modified=headers.get("last-modified"),
            )
        result = await super().check(url)
        if not result.changed:
            self.unchanged_count += 1
        return result


class NavigationDelayGuard:
    """Enforce robots crawl-delay between navigation starts for each origin."""

    def __init__(self) -> None:
        self._delays: dict[str, float] = {}
        self._next_allowed: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def set_delay(self, url: str, seconds: float) -> None:
        parsed = urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if seconds > 0:
            self._delays.setdefault(origin, seconds)

    async def wait(self, url: str) -> None:
        parsed = urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        delay = self._delays.get(origin)
        if delay is None:
            return

        lock = self._locks.setdefault(origin, asyncio.Lock())
        async with lock:
            remaining = self._next_allowed.get(origin, 0.0) - time.monotonic()
            if remaining > 0:
                await asyncio.sleep(remaining)
            self._next_allowed[origin] = time.monotonic() + delay


class StreamingThrottlingRequestManager(ThrottlingRequestManager):
    """Keep Crawlee alive while native sitemap discovery is active."""

    discovery_task: asyncio.Task[None] | None = None
    navigation_delay_guard: NavigationDelayGuard | None = None

    def set_crawl_delay(self, url: str, delay_seconds: float) -> None:
        super().set_crawl_delay(url, delay_seconds)
        if self.navigation_delay_guard is not None:
            self.navigation_delay_guard.set_delay(url, delay_seconds)

    async def is_finished(self) -> bool:
        if self.discovery_task is not None:
            if not self.discovery_task.done():
                return False
            self.discovery_task.result()
        return await super().is_finished()

    async def is_empty(self) -> bool:
        if self.discovery_task is not None:
            if not self.discovery_task.done():
                return False
            self.discovery_task.result()
        return await super().is_empty()


async def _restore_failed_requests(
    domain_queue: RequestQueue,
    checkpoint: dict[str, object],
) -> None:
    """Restore failed requests without reopening pending queue entries."""
    raw_keys = checkpoint.get("failed_keys", [])
    failed_keys = (
        {key for key in raw_keys if isinstance(key, str)}
        if isinstance(raw_keys, list)
        else set()
    )
    cooldowns = checkpoint.get("failed_cooldowns", {})

    for unique_key in sorted(failed_keys):
        retry_at = cooldowns.get(unique_key) if isinstance(cooldowns, dict) else None
        if isinstance(retry_at, str):
            try:
                deadline = datetime.fromisoformat(retry_at)
                if deadline.tzinfo is not None and deadline > datetime.now(UTC):
                    continue
            except ValueError:
                pass

        request = await domain_queue.get_request(unique_key)
        if request is None:
            raise RuntimeError(
                f"Failed request is missing from persistent queue: {unique_key}"
            )
        if request.handled_at is None:
            # Already pending: Crawlee can process it without reopening.
            continue

        result = await domain_queue.reopen_request(unique_key)
        if result is None:
            raise RuntimeError(
                f"Cannot reopen handled request from persistent queue: {unique_key}"
            )


async def _run_crawler_native(
    *,
    start_url: str,
    output_dir: Path | None,
    state_dir: Path | None,
    language: str = "en",
    max_concurrency: int = 1,
    max_requests: int | None = None,
    requests_per_minute: int = 6,
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

    # SitemapRequestLoader uses Crawlee's global service locator
    # for native state persistence. Each crawl runs in its own
    # worker process, so these services are isolated per crawl.
    from crawlee import service_locator

    service_locator.set_configuration(configuration)
    service_locator.set_storage_client(storage_client)
    service_locator.set_event_manager(event_manager)

    queue = await RequestQueue.open(
        configuration=configuration,
        storage_client=storage_client,
    )
    checkpoint = _load_checkpoint(checkpoint_file)
    raw_failed_keys = checkpoint.get("failed_keys", [])
    failed_keys: set[str] = (
        {key for key in raw_failed_keys if isinstance(key, str)}
        if isinstance(raw_failed_keys, list)
        else set()
    )
    if resume:
        domain_queue = await RequestQueue.open(
            alias=f"throttled-{hostname}",
            configuration=configuration,
            storage_client=storage_client,
        )
        await _restore_failed_requests(domain_queue, checkpoint)

    request_manager = StreamingThrottlingRequestManager(
        queue,
        domains=[hostname],
        request_manager_opener=RequestQueue.open,
        service_locator=crawl_services,
    )
    navigation_delay_guard = NavigationDelayGuard()
    request_manager.navigation_delay_guard = navigation_delay_guard

    # HTTP validators must survive fresh crawl queues and process restarts.
    freshness_configuration = Configuration(
        storage_dir=str(state_dir / "freshness-storage"), purge_on_start=False
    )
    freshness_store = await KeyValueStore.open(
        alias="docsync-http-freshness-v1",
        configuration=freshness_configuration,
        storage_client=storage_client,
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
        freshness_http_client = ImpitHttpClient()
        await freshness_http_client.__aenter__()
        sitemap_stack.push_async_callback(freshness_http_client.cleanup)
        freshness_checker = DocsSyncFreshnessChecker(
            freshness_http_client,
            freshness_store,
            output_dir=output_dir,
            content_state=content_state,
        )
        active_request_manager: RequestManager = request_manager

        if discover_sitemap:
            parsed_start = urlsplit(start_url)
            origin = f"{parsed_start.scheme}://{parsed_start.netloc}"

            http_client = freshness_http_client
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
                        persist_state_key="docsync-sitemap-loader-v1",
                    )
                )

                async def feed_sitemap() -> None:
                    emitted = 0
                    while True:
                        if max_requests is not None and emitted >= max_requests:
                            return

                        if await sitemap_loader.is_finished():
                            return

                        sitemap_request = await sitemap_loader.fetch_next_request()

                        if sitemap_request is None:
                            if await sitemap_loader.is_finished():
                                return
                            await asyncio.sleep(0.1)
                            continue

                        await request_manager.add_request(sitemap_request)
                        await sitemap_loader.mark_request_as_handled(sitemap_request)
                        emitted += 1

                request_manager.discovery_task = asyncio.create_task(feed_sitemap())

            if not sitemap_sources:
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

        # Keep Crawlee's persisted RequestQueue, but start each CLI run
        # with fresh native crawl statistics. The request limit is per run.
        from crawlee.statistics import Statistics

        run_statistics = Statistics.with_default_state(
            persistence_enabled=False,
        )

        crawler = PlaywrightCrawler(
            statistics=run_statistics,
            configuration=configuration,
            event_manager=event_manager,
            storage_client=storage_client,
            headless=not headful,
            use_incognito_pages=False,
            browser_launch_options=browser_launch_options,
            request_manager=active_request_manager,
            concurrency_settings=concurrency,
            max_requests_per_crawl=max_requests,
            max_request_retries=1,
            retry_on_blocked=False,
            max_session_rotations=0,
            respect_robots_txt_file=True,
            http_freshness_checker=freshness_checker,
        )

        @crawler.pre_navigation_hook
        async def respect_navigation_delay(
            context: PlaywrightPreNavCrawlingContext,
        ) -> None:
            await navigation_delay_guard.wait(context.request.url)

        @crawler.failed_request_handler
        async def on_failed_request(
            context: PlaywrightCrawlingContext | BasicCrawlingContext, error: Exception
        ) -> None:
            async with state_lock:
                failed_keys.add(context.request.unique_key)
                checkpoint = _load_checkpoint(checkpoint_file)
                checkpoint["failed_keys"] = sorted(failed_keys)
                cooldowns = checkpoint.get("failed_cooldowns", {})
                if not isinstance(cooldowns, dict):
                    cooldowns = {}
                if isinstance(
                    error, HttpClientStatusCodeError
                ) and error.status_code in (401, 403):
                    cooldowns[context.request.unique_key] = (
                        datetime.now(UTC) + timedelta(hours=24)
                    ).isoformat()
                checkpoint["failed_cooldowns"] = cooldowns
                details = checkpoint.get("failed_details", {})
                if not isinstance(details, dict):
                    details = {}
                status_code = (
                    error.status_code
                    if isinstance(error, HttpClientStatusCodeError)
                    else None
                )
                details[context.request.unique_key] = {
                    "url": context.request.url,
                    "status_code": status_code,
                    "failed_at": datetime.now(UTC).isoformat(),
                }
                checkpoint["failed_details"] = details
                _save_checkpoint(checkpoint_file, checkpoint)
                _write_failed_report(checkpoint_file)

        @crawler.router.default_handler
        async def handler(context: PlaywrightCrawlingContext) -> None:
            # Wait for usable document content rather than a mandatory <h1>.
            # Some documentation roots use h2, ARIA headings, or linked cards.
            # Dynamic widgets can update forever, so whole-body DOM stability
            # is not a reliable signal that the document is ready.
            try:
                await context.page.wait_for_function(
                    """() => {
                        const root = document.querySelector('main, article, [role="main"]') || document.body;
                        if (!root) return false;
                        const text = (root.innerText || '').trim();
                        return text.length >= 80 ||
                            (!!root.querySelector('h1, h2, h3, [role="heading"]') && text.length > 0) ||
                            (root.querySelectorAll('a[href]').length >= 3 && text.length >= 20);
                    }""",
                    timeout=15_000,
                )
            except PlaywrightTimeoutError:
                # A sparse or slow page may still contain legitimate content.
                # Archive what is present; don't retry it solely for lacking a heading.
                print(
                    f"Document readiness timed out; inspecting current DOM: {context.page.url}"
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
                markdown = f"> Source: {url}\n\n{markdown}"
                digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
                target = output_path(output_dir, url)
                target.parent.mkdir(parents=True, exist_ok=True)
                async with state_lock:
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

            # Link discovery must run even if the document has another language.
            await context.enqueue_links(
                strategy=crawl_strategy,
                transform_request_function=transform_request,
            )

            # Only successfully indexed pages may advance HTTP validators.
            if not markdown or not should_process:
                raise RuntimeError(
                    f"Document was not successfully indexed: {context.request.url}"
                )

            if context.request.unique_key in failed_keys:
                async with state_lock:
                    failed_keys.discard(context.request.unique_key)
                    checkpoint = _load_checkpoint(checkpoint_file)
                    checkpoint["failed_keys"] = sorted(failed_keys)
                    cooldowns = checkpoint.get("failed_cooldowns", {})
                    if isinstance(cooldowns, dict):
                        cooldowns.pop(context.request.unique_key, None)
                        checkpoint["failed_cooldowns"] = cooldowns
                    details = checkpoint.get("failed_details", {})
                    if isinstance(details, dict):
                        details.pop(context.request.unique_key, None)
                        checkpoint["failed_details"] = details
                    _save_checkpoint(checkpoint_file, checkpoint)
                    _write_failed_report(checkpoint_file)

        try:
            statistics = await crawler.run(
                [canonicalize_url(start_url)],
                purge_request_queue=False,
            )
        finally:
            discovery_task = request_manager.discovery_task
            if discovery_task is not None:
                if not discovery_task.done():
                    discovery_task.cancel()
                await asyncio.gather(discovery_task, return_exceptions=True)

        # 304-skipped requests never enter the browser handler.
        counters["processed"] += freshness_checker.unchanged_count
        counters["unchanged"] += freshness_checker.unchanged_count

        stopped_at_request_limit = (
            max_requests is not None and statistics.requests_total >= max_requests
        )
        crawl_complete = (
            not stopped_at_request_limit
            and statistics.requests_failed == 0
            and not failed_keys
            and await active_request_manager.is_finished()
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

    _write_failed_report(checkpoint_file)
    return counters


async def run_crawler(
    *,
    start_url: str,
    output_dir: Path | None,
    state_dir: Path | None,
    language: str = "en",
    max_concurrency: int = 1,
    max_requests: int | None = None,
    requests_per_minute: int = 6,
    crawl_strategy: Literal[
        "all", "same-domain", "same-hostname", "same-origin"
    ] = "same-origin",
    discover_sitemap: bool = True,
    headful: bool = False,
    restart: bool = False,
) -> dict[str, int]:
    """Run each native Crawlee crawl in an isolated Python process."""
    import signal
    import sys

    arguments = {
        "start_url": start_url,
        "output_dir": str(output_dir) if output_dir is not None else None,
        "state_dir": str(state_dir) if state_dir is not None else None,
        "language": language,
        "max_concurrency": max_concurrency,
        "max_requests": max_requests,
        "requests_per_minute": requests_per_minute,
        "crawl_strategy": crawl_strategy,
        "discover_sitemap": discover_sitemap,
        "headful": headful,
        "restart": restart,
    }

    with tempfile.TemporaryDirectory(prefix="docsync-worker-") as temporary:
        result_path = Path(temporary) / "result.json"

        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "docsync._crawl_worker",
            str(result_path),
            stdin=asyncio.subprocess.PIPE,
            start_new_session=True,
        )

        try:
            await process.communicate(json.dumps(arguments).encode("utf-8"))
        except (asyncio.CancelledError, KeyboardInterrupt):
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.send_signal(signal.SIGINT)

                try:
                    await asyncio.wait_for(
                        asyncio.shield(process.wait()),
                        timeout=60,
                    )
                except TimeoutError:
                    if process.returncode is None:
                        with suppress(ProcessLookupError):
                            os.killpg(process.pid, signal.SIGTERM)

                    try:
                        await asyncio.wait_for(
                            asyncio.shield(process.wait()),
                            timeout=10,
                        )
                    except TimeoutError:
                        if process.returncode is None:
                            with suppress(ProcessLookupError):
                                os.killpg(process.pid, signal.SIGKILL)
                        await process.wait()
            raise

        if process.returncode != 0:
            raise RuntimeError(
                f"DocsSync native crawler failed (exit code {process.returncode})"
            )

        if not result_path.is_file():
            raise RuntimeError("DocsSync worker returned no result.")

        result = json.loads(result_path.read_text(encoding="utf-8"))
        if not isinstance(result, dict) or any(
            key not in result or type(result[key]) is not int
            for key in ("processed", "saved", "unchanged")
        ):
            raise RuntimeError("DocsSync worker returned invalid statistics.")
        return {key: result[key] for key in ("processed", "saved", "unchanged")}
