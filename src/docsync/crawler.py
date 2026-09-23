"""Thin DocsSync policy on top of Crawlee Python."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from crawlee import (
    ConcurrencySettings,
    RequestOptions,
    RequestTransformAction,
    service_locator,
)
from crawlee.configuration import Configuration
from crawlee.crawlers import (
    AdaptivePlaywrightCrawler,
    AdaptivePlaywrightCrawlingContext,
)
from crawlee.request_loaders import ThrottlingRequestManager
from crawlee.storages import RequestQueue
from trafilatura import extract

_LANGUAGE_SEGMENTS = re.compile(r"/([a-z]{2})(?:[-_][a-z]{2})?(?:/|$)", re.I)


def _normalize_language(value: str) -> str:
    language = value.strip().lower().replace("_", "-").split("-", 1)[0]
    if len(language) != 2 or not language.isalpha():
        raise ValueError("language must be a two-letter code such as 'en' or 'tr'")
    return language


def _url_language(url: str) -> str | None:
    match = _LANGUAGE_SEGMENTS.search(urlsplit(url).path)
    return match.group(1).lower() if match else None


def _same_language(url: str, language: str) -> bool:
    detected = _url_language(url)
    return detected is None or detected == language


def _output_path(output_dir: Path, url: str) -> Path:
    path = urlsplit(url).path.strip("/") or "index"
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", path).strip("-") or "index"
    return output_dir / f"{safe}.md"


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


def _is_fresh(entry: dict[str, str] | None, refresh_hours: int) -> bool:
    if not entry or refresh_hours == 0:
        return False
    try:
        saved_at = datetime.fromisoformat(entry["saved_at"])
    except (KeyError, ValueError):
        return False
    if saved_at.tzinfo is None:
        saved_at = saved_at.replace(tzinfo=UTC)
    return datetime.now(UTC) - saved_at.astimezone(UTC) < timedelta(hours=refresh_hours)


def _meaningful_result(result: Any) -> bool:
    for call in result.push_data_calls:
        data = call["data"]
        values = data if isinstance(data, list) else [data]
        for value in values:
            if not isinstance(value, dict):
                continue
            if value.get("outcome") == "skip" or value.get("markdown"):
                return True
    return False


async def run_crawler(
    *,
    start_url: str,
    output_dir: Path,
    state_dir: Path,
    language: str = "en",
    max_concurrency: int = 2,
    max_requests: int = 10_000,
    requests_per_minute: int = 20,
    refresh_hours: int = 24,
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

    scope_id = hashlib.sha256(start_url.rstrip("/").encode("utf-8")).hexdigest()[:12]
    state_file = state_dir / f"{hostname}-{scope_id}.json"
    content_state = _load_state(state_file)

    configuration = Configuration(
        storage_dir=str(state_dir / "crawlee" / scope_id),
        purge_on_start=False,
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

    crawler = AdaptivePlaywrightCrawler.with_beautifulsoup_static_parser(
        configuration=configuration,
        event_manager=service_locator.get_event_manager(),
        request_manager=request_manager,
        concurrency_settings=concurrency,
        max_requests_per_crawl=max_requests,
        max_request_retries=2,
        respect_robots_txt_file=True,
        result_checker=_meaningful_result,
    )
    counters = {"processed": 0, "saved": 0, "unchanged": 0, "skipped": 0}

    def transform(options: RequestOptions) -> RequestOptions | RequestTransformAction:
        url = str(options["url"])
        if not _same_language(url, language):
            counters["skipped"] += 1
            return "skip"
        if _is_fresh(content_state.get(url), refresh_hours):
            counters["skipped"] += 1
            return "skip"
        return options

    start = urlsplit(start_url)
    scope_path = start.path.rstrip("/") or "/"
    scope_prefix = f"{start.scheme}://{start.netloc}{scope_path}"
    scope_pattern = re.compile(rf"^{re.escape(scope_prefix)}(?:/|[?]|$)")

    exclude_patterns: list[re.Pattern[str]] = []
    if start.hostname == "github.com" and "/wiki" in scope_path:
        exclude_patterns = [
            re.compile(rf"^{re.escape(scope_prefix)}(?:/.*)?/_history(?:[?]|$)"),
            re.compile(
                rf"^{re.escape(scope_prefix)}(?:/.*)?/[0-9a-f]{{40}}(?:[?]|$)",
                re.I,
            ),
        ]

    @crawler.router.default_handler
    async def handler(context: AdaptivePlaywrightCrawlingContext) -> None:
        soup = await context.parse_with_static_parser()

        await context.enqueue_links(
            selector="a",
            attribute="href",
            strategy="same-origin",
            include=[scope_pattern],
            exclude=exclude_patterns,
            transform_request_function=transform,
        )

        html_language = str(soup.html.get("lang", "") if soup.html else "")
        if html_language and _normalize_language(html_language) != language:
            await context.push_data({"outcome": "skip", "url": context.request.url})
            return

        text = extract(
            str(soup),
            url=context.request.url,
            output_format="markdown",
            include_comments=False,
            include_links=True,
            include_tables=True,
        )
        if not text:
            return
        text = text.strip()

        await context.push_data(
            {
                "outcome": "document",
                "url": context.request.url,
                "markdown": text,
                "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
        )

    async def flush_results() -> None:
        dataset = await crawler.get_dataset()
        async for item in dataset.iterate_items():
            if item.get("outcome") == "skip":
                counters["skipped"] += 1
                continue

            url = str(item["url"])
            text = str(item["markdown"])
            digest = str(item["content_hash"])
            previous = content_state.get(url, {})
            target = _output_path(output_dir, url)

            counters["processed"] += 1
            if previous.get("content_hash") == digest and target.exists():
                counters["unchanged"] += 1
            else:
                target.write_text(text + "\n", encoding="utf-8")
                counters["saved"] += 1

            content_state[url] = {
                "content_hash": digest,
                "saved_at": datetime.now(UTC).isoformat(),
                "filename": target.name,
            }

        await dataset.drop()

    completed = False
    try:
        await crawler.run([start_url], purge_request_queue=False)
        completed = await request_manager.is_finished()
    finally:
        await flush_results()
        _save_state(state_file, content_state)
        if completed:
            await request_manager.drop()

    return counters
