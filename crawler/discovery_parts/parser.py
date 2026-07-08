"""HTML parsing and Markdown conversion helpers for crawler discovery.

This module is intentionally pure:
- no HTTP
- no SQLite
- no queue orchestration
- no CLI interaction
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from typing import Final
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from markdownify import markdownify as _markdownify

_EMPTY_LINE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\n{3,}")
_SPACE_PATTERN: Final[re.Pattern[str]] = re.compile(r"[ \t]+")
_CONTROL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"
)
_MARKDOWN_LINK_PATTERN: Final[re.Pattern[str]] = re.compile(r"\[([^\]]*)\]\(\s*\)")


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """Parsed HTML document represented as title and Markdown body."""

    title: str
    markdown: str


def join_url(base_url: str, value: str) -> str | None:
    """Join a possibly relative URL with a base URL and remove fragments."""
    raw_value = unescape(value.strip())
    if not raw_value:
        return None

    parsed_value = urlparse(raw_value)
    if parsed_value.scheme and parsed_value.scheme.lower() not in {"http", "https"}:
        return None

    joined = urljoin(base_url, raw_value)
    clean, _fragment = urldefrag(joined)
    return normalize_url(clean)


def normalize_url(url: str) -> str | None:
    """Normalize an HTTP(S) URL for stable parser-level references."""
    raw_url = unescape(url.strip())
    if not raw_url:
        return None

    parsed = urlparse(raw_url)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        return None

    host = parsed.netloc.lower().strip()
    if not host:
        return None

    path = parsed.path or "/"
    normalized = urlunparse((scheme, host, path, "", parsed.query, ""))
    return (
        normalized.rstrip("/") + "/" if path == "/" and not parsed.query else normalized
    )


def extract_title(html: str) -> str:
    """Extract a readable page title from HTML."""
    soup = BeautifulSoup(html, "html.parser")

    title_tag = soup.find("title")
    if title_tag:
        title = _clean_inline_text(title_tag.get_text(" ", strip=True))
        if title:
            return title

    heading = soup.find(["h1", "h2"])
    if heading:
        title = _clean_inline_text(heading.get_text(" ", strip=True))
        if title:
            return title

    return ""


def html_to_markdown(html: str, *, base_url: str | None = None) -> str:
    """Convert HTML into clean Markdown."""
    soup = BeautifulSoup(html, "html.parser")
    _remove_noise(soup)

    if base_url:
        _absolutize_links(soup, base_url)

    markdown = str(
        _markdownify(
            str(soup),
            heading_style="ATX",
            bullets="-",
            strip=["script", "style"],
        )
    )
    return clean_markdown(markdown)


def parse_html_document(html: str, *, base_url: str | None = None) -> ParsedDocument:
    """Parse HTML and return title plus Markdown content."""
    return ParsedDocument(
        title=extract_title(html),
        markdown=html_to_markdown(html, base_url=base_url),
    )


def clean_markdown(markdown: str) -> str:
    """Normalize Markdown whitespace and remove empty links."""
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_PATTERN.sub("", text)
    text = _MARKDOWN_LINK_PATTERN.sub(r"\1", text)

    cleaned_lines: list[str] = []
    for line in text.splitlines():
        cleaned = _SPACE_PATTERN.sub(" ", line).rstrip()
        cleaned_lines.append(cleaned)

    text = "\n".join(cleaned_lines).strip()
    text = _EMPTY_LINE_PATTERN.sub("\n\n", text)
    return text + "\n" if text else ""


def _remove_noise(soup: BeautifulSoup) -> None:
    """Remove non-content HTML nodes before Markdown conversion."""
    selectors = (
        "script",
        "style",
        "noscript",
        "template",
        "svg",
        "canvas",
        "iframe",
        "form",
        "nav",
        "footer",
        "[hidden]",
        "[aria-hidden='true']",
    )
    for node in soup.select(",".join(selectors)):
        node.decompose()


def _absolutize_links(soup: BeautifulSoup, base_url: str) -> None:
    """Convert relative href/src attributes to absolute parser-safe URLs."""
    for tag in soup.find_all(True):
        if not isinstance(tag, Tag):
            continue

        for attribute in ("href", "src"):
            value = tag.get(attribute)
            if not isinstance(value, str):
                continue

            joined = join_url(base_url, value)
            if joined:
                tag[attribute] = joined


def _clean_inline_text(value: str) -> str:
    """Clean compact inline text."""
    text = _CONTROL_PATTERN.sub("", value)
    text = _SPACE_PATTERN.sub(" ", text)
    return text.strip()


__all__ = [
    "ParsedDocument",
    "clean_markdown",
    "extract_title",
    "html_to_markdown",
    "join_url",
    "normalize_url",
    "parse_html_document",
]
