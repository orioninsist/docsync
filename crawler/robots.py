from __future__ import annotations

import re
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import aiohttp

from crawler.config import CrawlerConfig


class RobotsManager:
    def __init__(self, config: CrawlerConfig) -> None:
        self.config: CrawlerConfig = config
        self.parser: urllib.robotparser.RobotFileParser = (
            urllib.robotparser.RobotFileParser()
        )
        self.robots_url: str = self._build_robots_url(config.start_url)

        self.sitemaps: list[str] = []
        self.crawl_delay: float | None = None
        self.loaded: bool = False

    def _build_robots_url(self, start_url: str) -> str:
        parsed = urlparse(start_url)
        return f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    async def load(self) -> None:
        async with aiohttp.ClientSession(
            headers={"User-Agent": self.config.user_agent}
        ) as session:
            try:
                async with session.get(
                    self.robots_url,
                    timeout=aiohttp.ClientTimeout(total=self.config.request_timeout),
                ) as response:
                    if response.status >= 400:
                        self.parser.parse(["User-agent: *", "Allow: /"])
                        self._add_default_sitemaps()
                        self.loaded = True
                        return

                    text = await response.text()

            except Exception:
                self.parser.parse(["User-agent: *", "Allow: /"])
                self._add_default_sitemaps()
                self.loaded = True
                return

        self.parser.parse(text.splitlines())
        self._extract_sitemaps(text)
        self._extract_crawl_delay(text)
        self._add_default_sitemaps()
        self.loaded = True

    def _extract_sitemaps(self, robots_text: str) -> None:
        for line in robots_text.splitlines():
            line = line.strip()

            if not line:
                continue

            if not line.lower().startswith("sitemap:"):
                continue

            sitemap_url = line.split(":", 1)[1].strip()

            if sitemap_url and sitemap_url not in self.sitemaps:
                self.sitemaps.append(sitemap_url)

    def _extract_crawl_delay(self, robots_text: str) -> None:
        parser_delay = self.parser.crawl_delay(self.config.user_agent)

        if parser_delay is not None:
            self.crawl_delay = float(parser_delay)
            return

        delay_pattern = re.compile(
            r"^\s*crawl-delay\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*$",
            re.IGNORECASE,
        )

        for line in robots_text.splitlines():
            match = delay_pattern.match(line)

            if not match:
                continue

            try:
                self.crawl_delay = float(match.group(1))
                return
            except ValueError:
                continue

    def _add_default_sitemaps(self) -> None:
        candidates = [
            "/sitemap.xml",
            "/sitemap_index.xml",
            "/sitemap-index.xml",
            "/sitemap1.xml",
            "/sitemap/sitemap.xml",
        ]

        for candidate in candidates:
            sitemap_url = urljoin(self.config.start_url, candidate)

            if sitemap_url not in self.sitemaps:
                self.sitemaps.append(sitemap_url)

    def effective_min_delay(self) -> float:
        if self.crawl_delay is None:
            return self.config.min_delay

        return max(self.config.min_delay, self.crawl_delay)

    def effective_max_delay(self) -> float:
        min_delay = self.effective_min_delay()
        return max(self.config.max_delay, min_delay)

    def can_fetch(self, url: str) -> bool:
        return self.parser.can_fetch(self.config.user_agent, url)
