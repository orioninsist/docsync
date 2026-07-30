from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar, final
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from markdownify import markdownify as md

from crawler.navigation_graph import NavigationGraph, NavigationGraphExtractor
from crawler.shared.url_normalizer import normalize_url
from crawler.shared.url_policy import BLOCKED_LINK_PREFIXES


@dataclass(frozen=True, slots=True)
class ParsedPage:
    title: str
    canonical_url: str | None
    clean_html: str
    markdown: str
    text_content: str
    navigation_graph: NavigationGraph


@final
class ContentParser:
    REMOVE_SELECTORS: ClassVar[tuple[str, ...]] = (
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

    MAIN_SELECTORS: ClassVar[tuple[str, ...]] = (
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

    LANGUAGE_CLASS_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"(?:^|\s)(?:language|lang)-([A-Za-z0-9_+#.-]+)(?:\s|$)",
        flags=re.IGNORECASE,
    )
    FENCE_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"^\s*(`{3,}|~{3,})")
    EMPTY_IMAGE_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"!\[\s*\]\([^)]+\)")
    EMPTY_LINK_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"\[\s*\]\([^)]+\)")

    _navigation_extractor: NavigationGraphExtractor

    def __init__(self) -> None:
        self._navigation_extractor = NavigationGraphExtractor()

    def parse(self, html: str, url: str) -> ParsedPage:
        navigation_graph = self._navigation_extractor.extract(
            html,
            url,
        )
        soup = BeautifulSoup(html, "html.parser")

        title = self._extract_title(soup)
        canonical_url = self._extract_canonical(soup, url)

        self._make_links_absolute(soup, url)
        self._remove_unwanted_elements(soup)

        main = self._find_main_content(soup)
        self._remove_duplicate_h1(main, title)
        self._prepare_structured_content(main)

        clean_html = str(main)
        markdown = self._convert_to_markdown(clean_html)
        text_content = self._clean_text(main.get_text(" ", strip=True))

        return ParsedPage(
            title=title,
            canonical_url=canonical_url,
            clean_html=clean_html,
            markdown=markdown,
            text_content=text_content,
            navigation_graph=navigation_graph,
        )

    def _convert_to_markdown(self, clean_html: str) -> str:
        markdown = md(
            clean_html,
            heading_style="ATX",
            bullets="-",
            autolinks=False,
            default_title=False,
            code_language_callback=self._code_language,
        )

        return self._clean_markdown(markdown)

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
        title = re.sub(
            r"\s+-\s+YouTube.*$",
            "",
            title,
            flags=re.IGNORECASE,
        )
        title = re.sub(
            r"\s+-\s+Google.*$",
            "",
            title,
            flags=re.IGNORECASE,
        )

        return title.strip() or "Untitled Page"

    def _extract_canonical(
        self,
        soup: BeautifulSoup,
        url: str,
    ) -> str | None:
        canonical = soup.find("link", rel="canonical")

        if isinstance(canonical, Tag):
            href = canonical.get("href")

            if href:
                return normalize_url(
                    urljoin(
                        url,
                        str(href).strip(),
                    )
                )

        og_url = soup.select_one('meta[property="og:url"]')

        if isinstance(og_url, Tag):
            content = og_url.get("content")

            if content:
                return normalize_url(
                    urljoin(
                        url,
                        str(content).strip(),
                    )
                )

        return None

    def _make_links_absolute(
        self,
        soup: BeautifulSoup,
        url: str,
    ) -> None:
        for tag in soup.find_all(["a", "img"]):
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

        return value_lower.startswith(BLOCKED_LINK_PREFIXES)

    def _remove_unwanted_elements(self, soup: BeautifulSoup) -> None:
        for selector in self.REMOVE_SELECTORS:
            for tag in soup.select(selector):
                tag.decompose()

    def _find_main_content(
        self,
        soup: BeautifulSoup,
    ) -> Tag | BeautifulSoup:
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

        h1_text = self._clean_title(
            first_h1.get_text(
                " ",
                strip=True,
            )
        )

        if h1_text.casefold() == title.casefold():
            first_h1.decompose()

    def _prepare_structured_content(
        self,
        main: Tag | BeautifulSoup,
    ) -> None:
        self._annotate_code_languages(main)
        self._normalize_tables(main)
        self._normalize_details(main)
        self._remove_empty_anchors(main)

    def _annotate_code_languages(
        self,
        main: Tag | BeautifulSoup,
    ) -> None:
        for code in main.find_all("code"):
            language = self._language_from_tag(code)

            if language is None:
                parent = code.parent

                if isinstance(parent, Tag) and parent.name == "pre":
                    language = self._language_from_tag(parent)

            if language is None:
                continue

            classes_attribute = code.get("class")
            classes = (
                [str(value) for value in classes_attribute]
                if isinstance(classes_attribute, list)
                else []
            )
            language_class = f"language-{language}"

            if language_class not in classes:
                classes.append(language_class)

            code["class"] = " ".join(classes)

    def _language_from_tag(self, tag: Tag) -> str | None:
        attribute_candidates = (
            tag.get("data-language"),
            tag.get("data-lang"),
            tag.get("lang"),
        )

        for candidate in attribute_candidates:
            if isinstance(candidate, str):
                language = self._normalize_language(candidate)

                if language:
                    return language

        classes = tag.get("class")

        if isinstance(classes, list):
            class_text = " ".join(str(value) for value in classes)
            match = self.LANGUAGE_CLASS_PATTERN.search(class_text)

            if match is not None:
                return self._normalize_language(match.group(1))

        return None

    def _normalize_language(self, value: str) -> str | None:
        normalized = value.strip().lower()
        normalized = re.sub(r"[^a-z0-9_+#.-]", "", normalized)

        return normalized or None

    def _code_language(self, element: Tag) -> str | None:
        return self._language_from_tag(element)

    def _normalize_tables(
        self,
        main: Tag | BeautifulSoup,
    ) -> None:
        for table in main.find_all("table"):
            self._promote_first_table_row(table)
            self._fill_empty_table_cells(table)

    def _promote_first_table_row(self, table: Tag) -> None:
        if table.find("th") is not None:
            return

        first_row = table.find("tr")

        if not isinstance(first_row, Tag):
            return

        cells = first_row.find_all(
            "td",
            recursive=False,
        )

        if not cells:
            return

        for cell in cells:
            cell.name = "th"

    def _fill_empty_table_cells(self, table: Tag) -> None:
        for cell in table.find_all(["th", "td"]):
            if cell.get_text(" ", strip=True):
                continue

            cell.string = " "

    def _normalize_details(
        self,
        main: Tag | BeautifulSoup,
    ) -> None:
        for details in main.find_all("details"):
            summary = details.find(
                "summary",
                recursive=False,
            )

            if not isinstance(summary, Tag):
                continue

            summary_text = self._clean_text(
                summary.get_text(
                    " ",
                    strip=True,
                )
            )

            if summary_text:
                summary.name = "h4"
            else:
                summary.decompose()

    def _remove_empty_anchors(
        self,
        main: Tag | BeautifulSoup,
    ) -> None:
        for anchor in main.find_all("a"):
            if anchor.get_text(" ", strip=True):
                continue

            if anchor.find("img") is not None:
                continue

            _ = anchor.unwrap()

    def _clean_markdown(self, markdown: str) -> str:
        normalized = markdown.replace(
            "\r\n",
            "\n",
        ).replace(
            "\r",
            "\n",
        )

        cleaned_lines: list[str] = []
        inside_fence = False
        active_fence = ""
        blank_count = 0

        for raw_line in normalized.split("\n"):
            fence = self._fence_marker(raw_line)

            if fence is not None:
                line = raw_line.rstrip()

                if inside_fence and fence.startswith(active_fence):
                    inside_fence = False
                    active_fence = ""
                elif not inside_fence:
                    inside_fence = True
                    active_fence = fence

                blank_count = 0
                cleaned_lines.append(line)
                continue

            if inside_fence:
                cleaned_lines.append(raw_line.rstrip())
                continue

            line = self._clean_prose_line(raw_line)

            if not line:
                blank_count += 1

                if blank_count <= 1:
                    cleaned_lines.append("")

                continue

            blank_count = 0
            cleaned_lines.append(line)

        cleaned = "\n".join(cleaned_lines).strip()
        cleaned = self.EMPTY_IMAGE_PATTERN.sub("", cleaned)
        cleaned = self.EMPTY_LINK_PATTERN.sub("", cleaned)
        cleaned = self._normalize_table_markdown(cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

        return cleaned.strip()

    def _fence_marker(self, line: str) -> str | None:
        match = self.FENCE_PATTERN.match(line)

        if match is None:
            return None

        return match.group(1)

    def _clean_prose_line(self, line: str) -> str:
        stripped = line.rstrip()

        if not stripped.strip():
            return ""

        if self._is_table_row(stripped):
            return self._clean_table_row(stripped)

        leading = stripped[: len(stripped) - len(stripped.lstrip())]
        content = stripped.lstrip()

        if self._is_list_or_quote_line(content):
            content = re.sub(r"[ \t]+", " ", content)

            return f"{leading}{content}".rstrip()

        return re.sub(r"[ \t]+", " ", stripped).strip()

    def _is_list_or_quote_line(self, line: str) -> bool:
        return bool(
            re.match(
                r"(?:[-+*]|\d+[.)]|>)\s+",
                line,
            )
        )

    def _is_table_row(self, line: str) -> bool:
        stripped = line.strip()

        return (
            stripped.startswith("|")
            and stripped.endswith("|")
            and stripped.count("|") >= 2
        )

    def _clean_table_row(self, line: str) -> str:
        cells = [
            re.sub(r"[ \t]+", " ", cell.strip())
            for cell in line.strip().strip("|").split("|")
        ]

        return f"| {' | '.join(cells)} |"

    def _normalize_table_markdown(self, markdown: str) -> str:
        lines = markdown.splitlines()
        normalized: list[str] = []
        index = 0

        while index < len(lines):
            line = lines[index]

            if not self._is_table_row(line):
                normalized.append(line)
                index += 1
                continue

            table_lines: list[str] = []

            while index < len(lines) and self._is_table_row(lines[index]):
                table_lines.append(self._clean_table_row(lines[index]))
                index += 1

            normalized.extend(self._ensure_table_separator(table_lines))

        return "\n".join(normalized)

    def _ensure_table_separator(
        self,
        table_lines: list[str],
    ) -> list[str]:
        if len(table_lines) < 2:
            return table_lines

        if self._is_table_separator(table_lines[1]):
            return table_lines

        column_count = max(
            table_lines[0].count("|") - 1,
            1,
        )
        separator = "| " + " | ".join("---" for _ in range(column_count)) + " |"

        return [
            table_lines[0],
            separator,
            *table_lines[1:],
        ]

    def _is_table_separator(self, line: str) -> bool:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]

        return bool(cells) and all(
            re.fullmatch(r":?-{3,}:?", cell) is not None for cell in cells
        )

    def _clean_text(self, text: str) -> str:
        return " ".join(text.split())
