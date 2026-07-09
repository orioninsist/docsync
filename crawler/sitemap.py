"""Sitemap discovery and same-site URL extraction utilities."""

from __future__ import annotations

import gzip
import re
import defusedxml.ElementTree as ET
from html import unescape
from typing import Any
from urllib.parse import ParseResult, parse_qs, urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from crawler.config import CrawlerConfig
from crawler.policy_engine import SmartScopePolicy
from crawler.robots import RobotsManager
from crawler.shared.url_normalizer import normalize_url as shared_normalize_url
from crawler.sitemap_language import (
    english_candidates_from_sitemap_url_node,
    url_declares_non_english,
)

BLOCKED_PATH_PARTS = (
    "/community",
    "/community/",
    "/search",
    "/search/",
    "/search/click",
    "/search/results",
    "/hc/search",
    "/hc/en-us/search",
    "/hc/en-us/search/",
    "/hc/en-us/search/click",
    "/hc/en-us/search/results",
    "/requests",
    "/requests/",
    "/signin",
    "/signin/",
    "/login",
    "/login/",
    "/logout",
    "/logout/",
    "/auth",
    "/auth/",
    "/users/sign_in",
    "/users/sign_in/",
    "/profiles",
    "/profiles/",
    "/subscriptions",
    "/subscriptions/",
)

BLOCKED_QUERY_KEYS = {
    "data",
    "query",
    "search",
    "search_id",
    "results_count",
    "rank",
    "return_to",
    "redirect",
    "redirect_to",
    "callback",
}

BLOCKED_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".pdf",
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".gz",
    ".mp4",
    ".webm",
    ".mov",
    ".avi",
    ".mp3",
    ".wav",
    ".css",
    ".js",
    ".mjs",
    ".json",
    ".xml",
    ".rss",
    ".atom",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
)

BLOCKED_QUERY_FRAGMENTS = (
    "format=pdf",
    "download=",
    "print=",
    "output=1",
    "view=print",
)

BLOCKED_HREF_SCHEMES = (
    "mailto:",
    "tel:",
    "javascript:",
    "data:",
    "blob:",
    "file:",
    "ftp:",
)

DEFAULT_SITEMAP_PATHS = (
    "/sitemap.xml",
    "/sitemap.xml.gz",
    "/sitemap_index.xml",
    "/sitemap_index.xml.gz",
    "/sitemap-index.xml",
    "/sitemap-index.xml.gz",
    "/sitemap1.xml",
    "/sitemap/sitemap.xml",
    "/sitemaps/sitemap.xml",
    "/sitemap-index/sitemap.xml",
)

URL_PATTERN = re.compile(r"https?://[^\s<>'\"]+")

MAX_SITEMAP_DEPTH = 8
MAX_SITEMAP_URLS_PER_FILE = 50_000


class SitemapManager:
    """Discover and filter sitemap URLs for the crawler discovery phase."""

    def __init__(
        self,
        config: CrawlerConfig,
        robots: RobotsManager,
    ) -> None:
        """Initialize sitemap discovery with config, robots, and scope policy."""
        self.config = config
        self.robots = robots
        self.start_netloc = urlparse(config.start_url).netloc.lower()
        self.policy = SmartScopePolicy(
            start_url=config.start_url,
            allowed_path_prefix=config.allowed_path_prefix,
        )
        self._visited_sitemaps: set[str] = set()

    async def discover_urls(self) -> list[str]:
        """Discover allowed document URLs from robots and default sitemap paths."""
        discovered: set[str] = set()

        async with aiohttp.ClientSession(
            headers={"User-Agent": self.config.user_agent},
        ) as session:
            for sitemap_url in self._expanded_sitemap_candidates():
                discovered.update(
                    await self._read_sitemap(
                        session=session,
                        sitemap_url=sitemap_url,
                        depth=0,
                    ),
                )

        return sorted(
            url
            for url in discovered
            if self._is_allowed_document_url(url) and self.robots.can_fetch(url)
        )

    def extract_links(
        self,
        html: str,
        base_url: str,
    ) -> list[str]:
        """Extract same-site document links from HTML."""
        soup = BeautifulSoup(html, "html.parser")
        discovered: set[str] = set()

        for selector in ("a[href]", "link[href]"):
            for tag in soup.select(selector):
                href = str(tag.get("href", "")).strip()
                rel_values = {str(value).lower() for value in tag.get("rel", [])}

                if not href or "canonical" in rel_values:
                    continue

                normalized = self._normalize_discovered_href(
                    href=href,
                    base_url=base_url,
                )

                if normalized and self._is_allowed_document_url(normalized):
                    discovered.add(normalized)

        return sorted(discovered)

    async def fallback_crawl_links(
        self,
        html: str,
        base_url: str,
    ) -> list[str]:
        """Return HTML links through the same extraction path used as fallback."""
        return self.extract_links(
            html=html,
            base_url=base_url,
        )

    def normalize_url(
        self,
        url: str,
    ) -> str:
        """Normalize URLs through the shared crawler normalizer."""
        return shared_normalize_url(url)

    def _expanded_sitemap_candidates(self) -> list[str]:
        candidates: list[str] = []
        seen: set[str] = set()

        parsed = urlparse(self.config.start_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        for sitemap_url in self.robots.sitemaps:
            self._append_unique_candidate(candidates, seen, sitemap_url)

        for candidate in DEFAULT_SITEMAP_PATHS:
            self._append_unique_candidate(
                candidates, seen, urljoin(base_url, candidate)
            )

        return candidates

    def _append_unique_candidate(
        self,
        candidates: list[str],
        seen: set[str],
        sitemap_url: str,
    ) -> None:
        normalized = self.normalize_url(sitemap_url)

        if normalized in seen:
            return

        seen.add(normalized)
        candidates.append(normalized)

    async def _read_sitemap(
        self,
        session: aiohttp.ClientSession,
        sitemap_url: str,
        depth: int = 0,
    ) -> set[str]:
        normalized_sitemap_url = self.normalize_url(sitemap_url)

        if self._should_skip_sitemap(normalized_sitemap_url, depth):
            return set()

        self._visited_sitemaps.add(normalized_sitemap_url)

        fetched = await self._fetch_sitemap_payload(session, normalized_sitemap_url)

        if fetched is None:
            return set()

        raw, content_type, final_sitemap_url = fetched
        text = self._decode_sitemap_payload(
            raw=raw,
            sitemap_url=final_sitemap_url,
            content_type=content_type,
        )

        if not text or not text.strip():
            return set()

        return await self._parse_sitemap_text(
            session=session,
            text=text.strip(),
            content_type=content_type,
            final_sitemap_url=final_sitemap_url,
            depth=depth,
        )

    def _should_skip_sitemap(self, sitemap_url: str, depth: int) -> bool:
        return depth > MAX_SITEMAP_DEPTH or sitemap_url in self._visited_sitemaps

    async def _fetch_sitemap_payload(
        self,
        session: aiohttp.ClientSession,
        sitemap_url: str,
    ) -> tuple[bytes, str, str] | None:
        timeout = aiohttp.ClientTimeout(total=self.config.request_timeout)

        try:
            async with session.get(
                sitemap_url,
                timeout=timeout,
                allow_redirects=True,
            ) as response:
                if response.status >= 400:
                    return None

                raw = await response.read()
                content_type = response.headers.get("Content-Type", "").lower()
                final_sitemap_url = str(response.url)

                return raw, content_type, final_sitemap_url
        except (aiohttp.ClientError, TimeoutError, OSError):
            return None

    async def _parse_sitemap_text(
        self,
        *,
        session: aiohttp.ClientSession,
        text: str,
        content_type: str,
        final_sitemap_url: str,
        depth: int,
    ) -> set[str]:
        if self._looks_like_html(text, content_type):
            return self._extract_urls_from_html_sitemap(
                html=text,
                base_url=final_sitemap_url,
            )

        root = self._parse_xml_safely(text)

        if root is None:
            return self._extract_urls_from_plain_text_sitemap(text)

        root_name = self._strip_namespace(root.tag).lower()

        if root_name == "sitemapindex":
            return await self._read_sitemap_index(
                session=session,
                root=root,
                depth=depth,
            )

        if root_name == "urlset":
            return self._extract_urls_from_urlset(root)

        return self._extract_urls_from_plain_text_sitemap(text)

    async def _read_sitemap_index(
        self,
        *,
        session: aiohttp.ClientSession,
        root: Any,
        depth: int,
    ) -> set[str]:
        urls: set[str] = set()
        namespace = self._namespace(root.tag)
        sitemap_nodes = root.findall(f".//{namespace}sitemap/{namespace}loc")

        for node in sitemap_nodes:
            if not node.text:
                continue

            child_url = self.normalize_url(unescape(node.text.strip()))

            if not self._is_same_site_url(child_url):
                continue

            urls.update(
                await self._read_sitemap(
                    session=session,
                    sitemap_url=child_url,
                    depth=depth + 1,
                ),
            )

        return urls

    def _extract_urls_from_urlset(self, root: Any) -> set[str]:
        urls: set[str] = set()
        namespace = self._namespace(root.tag)
        url_nodes = root.findall(f".//{namespace}url")

        for url_node in url_nodes[:MAX_SITEMAP_URLS_PER_FILE]:
            urls.update(self._allowed_urls_from_url_node(url_node, namespace))

        return urls

    def _allowed_urls_from_url_node(
        self,
        url_node: Any,
        namespace: str,
    ) -> set[str]:
        loc_node = url_node.find(f"{namespace}loc")

        if loc_node is None or not loc_node.text:
            return set()

        loc_url = self.normalize_url(unescape(loc_node.text.strip()))
        candidates = english_candidates_from_sitemap_url_node(
            url_node=url_node,
            fallback_url=loc_url,
            require_english=self.config.require_english,
            strip_namespace=self._strip_namespace,
        )

        return {
            normalized
            for candidate_url in candidates
            if self._is_allowed_document_url(
                normalized := self.normalize_url(candidate_url),
            )
        }

    def _parse_xml_safely(self, text: str) -> Any | None:
        try:
            return ET.fromstring(text)  # nosec B314

        except ET.ParseError:
            cleaned = self._remove_invalid_xml_chars(text)

            try:
                return ET.fromstring(cleaned)  # nosec B314

            except ET.ParseError:
                return None

    def _remove_invalid_xml_chars(self, text: str) -> str:
        return re.sub(
            r"[\x00-\x08\x0B\x0C\x0E-\x1F]",
            "",
            text,
        )

    def _looks_like_html(
        self,
        text: str,
        content_type: str,
    ) -> bool:
        if "text/html" in content_type:
            return True

        prefix = text[:500].lower()

        return "<html" in prefix or "<!doctype html" in prefix or "<body" in prefix

    def _extract_urls_from_html_sitemap(
        self,
        html: str,
        base_url: str,
    ) -> set[str]:
        urls: set[str] = set()
        soup = BeautifulSoup(html, "html.parser")

        for tag in soup.select("a[href]"):
            normalized = self._normalize_discovered_href(
                href=str(tag.get("href", "")).strip(),
                base_url=base_url,
            )

            if normalized and self._is_allowed_document_url(normalized):
                urls.add(normalized)

        return urls

    def _extract_urls_from_plain_text_sitemap(
        self,
        text: str,
    ) -> set[str]:
        urls: set[str] = set()

        for match in URL_PATTERN.finditer(text):
            normalized = self.normalize_url(unescape(match.group(0).strip()))

            if self._is_allowed_document_url(normalized):
                urls.add(normalized)

        return urls

    def _decode_sitemap_payload(
        self,
        *,
        raw: bytes,
        sitemap_url: str,
        content_type: str,
    ) -> str | None:
        try:
            payload = (
                gzip.decompress(raw)
                if self._should_decompress(raw, sitemap_url, content_type)
                else raw
            )
            return payload.decode("utf-8", errors="replace")

        except (gzip.BadGzipFile, OSError, UnicodeError):
            return None

    def _should_decompress(
        self,
        raw: bytes,
        sitemap_url: str,
        content_type: str,
    ) -> bool:
        return (
            sitemap_url.lower().endswith(".gz")
            or "gzip" in content_type
            or raw.startswith(b"\x1f\x8b")
        )

    def _normalize_discovered_href(
        self,
        *,
        href: str,
        base_url: str,
    ) -> str | None:
        cleaned_href = unescape(href.strip())

        if not cleaned_href or cleaned_href.startswith("#"):
            return None

        if cleaned_href.lower().startswith(BLOCKED_HREF_SCHEMES):
            return None

        return self.normalize_url(urljoin(base_url, cleaned_href))

    def _namespace(
        self,
        tag: str,
    ) -> str:
        if tag.startswith("{"):
            return tag.split("}", 1)[0] + "}"

        return ""

    def _strip_namespace(
        self,
        tag: str,
    ) -> str:
        if tag.startswith("{"):
            return tag.split("}", 1)[1]

        return tag

    def _is_same_site_url(
        self,
        url: str,
    ) -> bool:
        parsed = urlparse(url)
        return parsed.netloc.lower() == self.start_netloc

    def _is_allowed_document_url(
        self,
        url: str,
    ) -> bool:
        parsed = urlparse(url)

        return (
            self._has_allowed_scheme_and_host(parsed)
            and self._policy_allows(url)
            and self._path_scope_allows(parsed.path)
            and not self._path_is_blocked(parsed.path)
            and not self._has_blocked_query(parsed.query)
            and not self._language_is_blocked(url)
            and not self._has_blocked_extension(parsed.path)
            and not self._has_blocked_query_fragment(parsed.query)
        )

    def _has_allowed_scheme_and_host(self, parsed: ParseResult) -> bool:
        return (
            parsed.scheme.lower() in {"http", "https"}
            and parsed.netloc.lower() == self.start_netloc
        )

    def _policy_allows(self, url: str) -> bool:
        return self.policy.evaluate_url(url).allowed

    def _path_scope_allows(self, path: str) -> bool:
        normalized_path = self._normalized_path(path)
        allowed_prefix = self.config.allowed_path_prefix.rstrip("/") or "/"
        allowed_prefix_lower = allowed_prefix.lower()

        if allowed_prefix_lower == "/":
            return True

        return normalized_path == allowed_prefix_lower or normalized_path.startswith(
            f"{allowed_prefix_lower}/",
        )

    def _path_is_blocked(self, path: str) -> bool:
        normalized_path = self._normalized_path(path)
        path_parts = [part for part in normalized_path.strip("/").split("/") if part]

        return "community" in path_parts or self._is_blocked_application_path(
            normalized_path,
        )

    def _normalized_path(self, path: str) -> str:
        return f"/{path.lower().strip('/')}"

    def _is_blocked_application_path(
        self,
        normalized_path: str,
    ) -> bool:
        for blocked_path in BLOCKED_PATH_PARTS:
            blocked = f"/{blocked_path.strip('/')}"

            if normalized_path == blocked or normalized_path.startswith(f"{blocked}/"):
                return True

        return False

    def _has_blocked_query(
        self,
        query: str,
    ) -> bool:
        if not query:
            return False

        return any(
            key.lower() in BLOCKED_QUERY_KEYS
            for key in parse_qs(query, keep_blank_values=False)
        )

    def _language_is_blocked(self, url: str) -> bool:
        return self.config.require_english and url_declares_non_english(url)

    def _has_blocked_extension(
        self,
        path: str,
    ) -> bool:
        return path.lower().endswith(BLOCKED_EXTENSIONS)

    def _has_blocked_query_fragment(
        self,
        query: str,
    ) -> bool:
        query_lower = query.lower()

        return any(fragment in query_lower for fragment in BLOCKED_QUERY_FRAGMENTS)
