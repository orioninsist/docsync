from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar
from urllib.parse import urljoin, urlparse

import aiohttp

from crawler.config import CrawlerConfig
from crawler.shared.url_normalizer import normalize_url


class LlmsTxtDocumentKind(StrEnum):
    STANDARD = "llms.txt"
    FULL = "llms-full.txt"


@dataclass(frozen=True, slots=True)
class LlmsTxtLink:
    title: str
    url: str
    description: str | None


@dataclass(frozen=True, slots=True)
class LlmsTxtDocument:
    kind: LlmsTxtDocumentKind
    url: str
    title: str | None
    summary: str | None
    content: str
    links: tuple[LlmsTxtLink, ...]


@dataclass(frozen=True, slots=True)
class LlmsTxtDiscoveryResult:
    documents: tuple[LlmsTxtDocument, ...]

    @property
    def primary(self) -> LlmsTxtDocument | None:
        for document in self.documents:
            if document.kind is LlmsTxtDocumentKind.FULL:
                return document

        return self.documents[0] if self.documents else None


class LlmsTxtDiscovery:
    """Discover and parse llms.txt documents for one documentation origin."""

    _DOCUMENT_PATHS: ClassVar[tuple[tuple[LlmsTxtDocumentKind, str], ...]] = (
        (LlmsTxtDocumentKind.STANDARD, "/llms.txt"),
        (LlmsTxtDocumentKind.FULL, "/llms-full.txt"),
    )

    _MARKDOWN_LINK_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"^\s*[-*]\s+\[([^\]]+)\]\(([^)\s]+)\)(?:\s*:\s*(.+))?\s*$"
    )

    _config: CrawlerConfig

    def __init__(self, config: CrawlerConfig) -> None:
        self._config = config

    async def discover(self, base_url: str) -> LlmsTxtDiscoveryResult:
        origin = self._origin_url(base_url)

        if origin is None:
            return LlmsTxtDiscoveryResult(documents=())

        documents: list[LlmsTxtDocument] = []

        timeout = aiohttp.ClientTimeout(total=self._config.request_timeout)
        headers = {
            "Accept": "text/plain,text/markdown;q=0.9,*/*;q=0.1",
            "User-Agent": self._config.user_agent,
        }

        async with aiohttp.ClientSession(
            headers=headers,
            timeout=timeout,
        ) as session:
            for kind, path in self._DOCUMENT_PATHS:
                document = await self._fetch_document(
                    session=session,
                    kind=kind,
                    url=urljoin(origin, path),
                )

                if document is not None:
                    documents.append(document)

        return LlmsTxtDiscoveryResult(documents=tuple(documents))

    async def _fetch_document(
        self,
        *,
        session: aiohttp.ClientSession,
        kind: LlmsTxtDocumentKind,
        url: str,
    ) -> LlmsTxtDocument | None:
        try:
            async with session.get(
                url,
                allow_redirects=True,
            ) as response:
                if response.status != 200:
                    return None

                content_type = response.headers.get(
                    "Content-Type",
                    "",
                ).lower()

                if not self._is_supported_content_type(content_type):
                    return None

                content = (await response.text()).strip()

                if not content:
                    return None

                final_url = normalize_url(str(response.url)) or str(response.url)

        except aiohttp.ClientError, TimeoutError, UnicodeError:
            return None

        title, summary = self._extract_header(content)

        return LlmsTxtDocument(
            kind=kind,
            url=final_url,
            title=title,
            summary=summary,
            content=content,
            links=self._extract_links(
                content=content,
                document_url=final_url,
            ),
        )

    def _extract_header(
        self,
        content: str,
    ) -> tuple[str | None, str | None]:
        title: str | None = None
        summary_lines: list[str] = []
        title_found = False

        for raw_line in content.splitlines():
            line = raw_line.strip()

            if not line:
                if summary_lines:
                    break

                continue

            if not title_found and line.startswith("# "):
                title = line[2:].strip() or None
                title_found = True
                continue

            if line.startswith("#"):
                if summary_lines:
                    break

                continue

            if self._MARKDOWN_LINK_PATTERN.match(line):
                break

            if title_found:
                summary_lines.append(line)

        summary = " ".join(summary_lines).strip() or None
        return title, summary

    def _extract_links(
        self,
        *,
        content: str,
        document_url: str,
    ) -> tuple[LlmsTxtLink, ...]:
        links: list[LlmsTxtLink] = []
        seen_urls: set[str] = set()

        for line in content.splitlines():
            match = self._MARKDOWN_LINK_PATTERN.match(line)

            if match is None:
                continue

            title = " ".join(match.group(1).split())
            raw_url = match.group(2).strip()
            raw_description = match.group(3)

            resolved_url = normalize_url(urljoin(document_url, raw_url))

            if resolved_url is None or resolved_url in seen_urls:
                continue

            seen_urls.add(resolved_url)

            description = (
                " ".join(raw_description.split())
                if raw_description is not None
                else None
            )

            links.append(
                LlmsTxtLink(
                    title=title,
                    url=resolved_url,
                    description=description,
                )
            )

        return tuple(links)

    def _origin_url(self, base_url: str) -> str | None:
        parsed = urlparse(base_url)

        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None

        return f"{parsed.scheme}://{parsed.netloc}/"

    def _is_supported_content_type(self, content_type: str) -> bool:
        if not content_type:
            return True

        return any(
            marker in content_type
            for marker in (
                "text/plain",
                "text/markdown",
                "text/x-markdown",
                "application/octet-stream",
            )
        )
