"""Build crawler runtime state before crawl execution begins."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable, TypedDict

from crawler.config import CrawlerConfig
from crawler.database import DatabaseManager
from crawler.dedup import DeduplicationEngine
from crawler.observability import CrawlerObservability
from crawler.robots import RobotsManager
from crawler.sitemap import SitemapManager


class CrawlerRunRuntime(TypedDict):
    """Values prepared before crawl execution starts."""

    interrupted_count: int
    repaired_missing_outputs: int
    sitemap: SitemapManager
    sitemap_urls: list[str]
    seed_urls: list[str]


class CrawlerRuntimeBuilder:
    """Prepare crawl state without executing the crawl loop."""

    def __init__(
        self,
        *,
        config: CrawlerConfig,
        database: DatabaseManager,
        robots: RobotsManager,
        dedup: DeduplicationEngine,
        observability: CrawlerObservability,
        claim_url_ownership: Callable[[str], bool],
        normalize_english_candidate_url: Callable[[str], str | None],
        logger: logging.Logger,
    ) -> None:
        self._config = config
        self._database = database
        self._robots = robots
        self._dedup = dedup
        self._observability = observability
        self._claim_url_ownership = claim_url_ownership
        self._normalize_english_candidate_url = (
            normalize_english_candidate_url
        )
        self._logger = logger

    async def build(self) -> CrawlerRunRuntime:
        """Prepare all state required by the crawl execution stage."""

        interrupted_count = self._database.reset_interrupted_processing()
        repaired_missing_outputs = self._repair_missing_markdown_outputs()

        await self._robots.load()
        self._apply_robots_delay()

        sitemap = SitemapManager(self._config, self._robots)
        sitemap_urls = await self._discover_sitemap_urls(sitemap)
        seed_urls = self._prepare_seed_urls(sitemap, sitemap_urls)

        return {
            "interrupted_count": interrupted_count,
            "repaired_missing_outputs": repaired_missing_outputs,
            "sitemap": sitemap,
            "sitemap_urls": sitemap_urls,
            "seed_urls": seed_urls,
        }

    async def _discover_sitemap_urls(
        self,
        sitemap: SitemapManager,
    ) -> list[str]:
        sitemap_urls: list[str] = []

        if not self._config.use_sitemap_discovery:
            return sitemap_urls

        timeout_seconds = (
            self._config.sitemap_discovery_timeout_seconds
        )

        self._logger.info(
            "Starting sitemap discovery with timeout=%ss",
            timeout_seconds,
        )
        print(
            f"Sitemap discovery started. Timeout: {timeout_seconds}s",
            flush=True,
        )

        try:
            sitemap_urls = await asyncio.wait_for(
                sitemap.discover_urls(),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            self._logger.warning(
                (
                    "Sitemap discovery timed out after %ss. "
                    "Falling back to exact start URL."
                ),
                timeout_seconds,
            )
            print(
                (
                    "Sitemap discovery timed out. "
                    "Falling back to exact start URL."
                ),
                flush=True,
            )
            return sitemap_urls

        self._logger.info(
            "Sitemap discovery finished. URLs=%s",
            len(sitemap_urls),
        )
        print(
            f"Sitemap discovery finished. URLs found: {len(sitemap_urls)}",
            flush=True,
        )

        return sitemap_urls

    def _prepare_seed_urls(
        self,
        sitemap: SitemapManager,
        sitemap_urls: list[str],
    ) -> list[str]:
        seed_urls = list(sitemap_urls)
        start_url = sitemap.normalize_url(self._config.start_url)

        if start_url is None:
            return seed_urls

        if start_url not in seed_urls:
            seed_urls.insert(0, start_url)

        seed_urls = self._filter_robots_allowed_seed_urls(seed_urls)

        if not seed_urls:
            message = (
                "No crawlable seed URLs remain after robots.txt filtering. "
                "The crawler will finish without downloading pages."
            )
            print(message, flush=True)
            self._logger.warning(message)

        limited_seed_urls = self._limit_seed_urls(seed_urls)
        self._enqueue_seed_urls(limited_seed_urls)

        return limited_seed_urls

    def _filter_robots_allowed_seed_urls(
        self,
        seed_urls: list[str],
    ) -> list[str]:
        allowed_urls: list[str] = []

        for seed_url in seed_urls:
            if self._robots.can_fetch(seed_url):
                allowed_urls.append(seed_url)
                continue

            message = (
                "Seed URL blocked by robots.txt; it will not be queued: "
                f"url={seed_url}"
            )
            print(message, flush=True)
            self._logger.warning(message)

        return allowed_urls

    def _repair_missing_markdown_outputs(self) -> int:
        existing_hashes = self._existing_markdown_short_hashes()

        full_hashes = {
            url_hash
            for url_hash in self._database.all_queue_url_hashes()
            if url_hash[:12] in existing_hashes
        }

        repaired = self._database.repair_missing_markdown_outputs(
            full_hashes
        )

        if repaired:
            self._logger.info(
                (
                    "Repaired missing Markdown outputs by requeueing URLs: "
                    "count=%s output_dir=%s"
                ),
                repaired,
                self._config.output_dir,
            )

        return repaired

    def _existing_markdown_short_hashes(self) -> set[str]:
        output_dir = self._config.output_dir
        existing_hashes: set[str] = set()

        if not output_dir.exists():
            return existing_hashes

        for path in output_dir.glob("*.md"):
            short_hash = self._markdown_short_hash(path)

            if short_hash is not None:
                existing_hashes.add(short_hash)

        return existing_hashes

    @staticmethod
    def _markdown_short_hash(path: Path) -> str | None:
        if not path.is_file():
            return None

        stem = path.stem

        if "__" not in stem:
            return None

        short_hash = stem.rsplit("__", 1)[-1].strip()

        return short_hash or None

    def _apply_robots_delay(self) -> None:
        effective_min = self._robots.effective_min_delay()
        effective_max = self._robots.effective_max_delay()

        object.__setattr__(
            self._config,
            "min_delay",
            effective_min,
        )
        object.__setattr__(
            self._config,
            "max_delay",
            effective_max,
        )

    def _limit_seed_urls(self, urls: list[str]) -> list[str]:
        hard_limit = self._config.max_queue_size

        if len(urls) <= hard_limit:
            return urls

        self._logger.warning(
            (
                "Seed URL list was capped by max_queue_size: "
                "original=%s capped=%s max_queue_size=%s"
            ),
            len(urls),
            hard_limit,
            self._config.max_queue_size,
        )

        return urls[:hard_limit]

    def _enqueue_seed_urls(self, urls: list[str]) -> None:
        for raw_url in urls:
            url = self._normalize_english_candidate_url(raw_url)

            if url is None:
                self._observability.record_official_rejected(
                    url=raw_url,
                    reason=(
                        "non_english_or_invalid_seed_url_before_enqueue"
                    ),
                )
                continue

            if (
                self._database.queued_count()
                >= self._config.max_queue_size
            ):
                self._logger.warning(
                    (
                        "Max queue size reached while enqueueing seed URLs: "
                        "max_queue_size=%s"
                    ),
                    self._config.max_queue_size,
                )
                break

            if not self._claim_url_ownership(url):
                continue

            url_hash = self._dedup.url_hash(url)

            queued = self._database.enqueue_url(
                url=url,
                url_hash=url_hash,
                depth=0,
                discovered_from=None,
            )

            if queued:
                continue

            self._database.requeue_url(
                url=url,
                url_hash=url_hash,
                depth=0,
                discovered_from=None,
            )
