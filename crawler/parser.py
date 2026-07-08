from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from crawler.shared.url_normalizer import normalize_url
from markdownify import markdownify as md


@dataclass(frozen=True)
class ParsedPage:
    title: str
    canonical_url: str | None
    clean_html: str
    markdown: str
    text_content: str


class ContentParser:
    REMOVE_SELECTORS = (
        "script",
        "style",
        "noscript",
        "iframe",
        "svg",
        "form",
        "button",
        "nav",
        "footer",
        "header",
        "aside",
        "[role='navigation']",
        "[role='banner']",
        "[role='contentinfo']",
        "[aria-hidden='true']",
        ".cookie",
        ".cookies",
        ".cookie-banner",
        ".cookie-consent",
        ".modal",
        ".popup",
        ".newsletter",
        ".sidebar",
        ".toc",
        ".table-of-contents",
        ".breadcrumb",
        ".breadcrumbs",
    )

    MAIN_SELECTORS = (
        "main",
        "article",
        "[role='main']",
        ".content",
        ".documentation",
        ".docs-content",
        ".doc-content",
        ".markdown-body",
        ".article-content",
        ".post-content",
        ".entry-content",
    )

    BLOCKED_LINK_PREFIXES = (
        "#",
        "mailto:",
        "tel:",
        "javascript:",
        "data:",
        "blob:",
        "file:",
    )

    def parse(self, html: str, url: str) -> ParsedPage:
        soup = BeautifulSoup(html, "html.parser")

        title = self._extract_title(soup)
        canonical_url = self._extract_canonical(soup, url)

        self._make_links_absolute(soup, url)
        self._remove_unwanted_elements(soup)

        main = self._find_main_content(soup)
        self._remove_duplicate_h1(main, title)

        clean_html = str(main)

        markdown = md(
            clean_html,
            heading_style="ATX",
            bullets="-",
            autolinks=False,
            default_title=False,
        )

        markdown = self._clean_markdown(markdown)
        text_content = self._clean_text(main.get_text(" ", strip=True))

        return ParsedPage(
            title=title,
            canonical_url=canonical_url,
            clean_html=clean_html,
            markdown=markdown,
            text_content=text_content,
        )

    def _extract_title(self, soup: BeautifulSoup) -> str:
        og_title = soup.select_one('meta[property="og:title"]')

        if og_title and og_title.get("content"):
            return self._clean_title(str(og_title["content"]))

        heading = soup.find("h1")

        if heading:
            text = heading.get_text(" ", strip=True)

            if text:
                return self._clean_title(text)

        if soup.title and soup.title.string:
            return self._clean_title(soup.title.string)

        return "Untitled Page"

    def _clean_title(self, title: str) -> str:
        title = " ".join(title.split())
        title = re.sub(r"\s+\|\s+.*$", "", title)
        title = re.sub(r"\s+-\s+YouTube.*$", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\s+-\s+Google.*$", "", title, flags=re.IGNORECASE)

        return title.strip() or "Untitled Page"

    def _extract_canonical(self, soup: BeautifulSoup, url: str) -> str | None:
        canonical = soup.find("link", rel="canonical")

        if isinstance(canonical, Tag):
            href = canonical.get("href")

            if href:
                return normalize_url(urljoin(url, str(href).strip()))

        og_url = soup.select_one('meta[property="og:url"]')

        if isinstance(og_url, Tag):
            content = og_url.get("content")

            if content:
                return normalize_url(urljoin(url, str(content).strip()))

        return None

    def _make_links_absolute(self, soup: BeautifulSoup, url: str) -> None:
        for tag in soup.find_all(["a", "img"]):
            if not isinstance(tag, Tag):
                continue

            attribute = "href" if tag.name == "a" else "src"
            value = tag.get(attribute)

            if not value:
                continue

            value_text = str(value).strip()

            if not value_text:
                continue

            if self._is_blocked_link_value(value_text):
                continue

            tag[attribute] = urljoin(url, value_text)

    def _is_blocked_link_value(self, value: str) -> bool:
        value_lower = value.strip().lower()
        return value_lower.startswith(self.BLOCKED_LINK_PREFIXES)

    def _remove_unwanted_elements(self, soup: BeautifulSoup) -> None:
        for selector in self.REMOVE_SELECTORS:
            for tag in soup.select(selector):
                tag.decompose()

    def _find_main_content(self, soup: BeautifulSoup) -> Tag | BeautifulSoup:
        for selector in self.MAIN_SELECTORS:
            element = soup.select_one(selector)

            if isinstance(element, Tag) and self._has_enough_text(element):
                return element

        body = soup.find("body")

        if isinstance(body, Tag):
            return body

        return soup

    def _has_enough_text(self, tag: Tag) -> bool:
        text = self._clean_text(tag.get_text(" ", strip=True))
        return len(text) >= 100

    def _remove_duplicate_h1(
        self,
        main: Tag | BeautifulSoup,
        title: str,
    ) -> None:
        first_h1 = main.find("h1")

        if not isinstance(first_h1, Tag):
            return

        h1_text = self._clean_title(first_h1.get_text(" ", strip=True))

        if h1_text.casefold() == title.casefold():
            first_h1.decompose()

    def _clean_markdown(self, markdown: str) -> str:
        markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")

        lines = markdown.split("\n")
        cleaned_lines: list[str] = []

        blank_count = 0

        for line in lines:
            line = line.rstrip()
            line = re.sub(r"[ \t]+", " ", line)

            if not line.strip():
                blank_count += 1

                if blank_count <= 2:
                    cleaned_lines.append("")

                continue

            blank_count = 0
            cleaned_lines.append(line)

        markdown = "\n".join(cleaned_lines).strip()

        markdown = re.sub(r"\n{3,}", "\n\n", markdown)
        markdown = re.sub(r"!\[\s*\]\([^)]+\)", "", markdown)
        markdown = re.sub(r"\[\s*\]\([^)]+\)", "", markdown)

        return markdown.strip()

    def _clean_text(self, text: str) -> str:
        return " ".join(text.split())
