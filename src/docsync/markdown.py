from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag
from markdownify import markdownify

REMOVE_SELECTORS = (
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "canvas",
    "iframe",
    "button",
    "input",
    "select",
    "textarea",
    "nav",
    "header",
    "footer",
    "[role='navigation']",
    "[role='banner']",
    "[role='contentinfo']",
    "[aria-hidden='true']",
    ".advertisement",
    ".ads",
    ".breadcrumb",
    ".breadcrumbs",
    ".cookie-banner",
    ".cookie-consent",
    ".footer",
    ".header",
    ".menu",
    ".modal",
    ".navigation",
    ".newsletter",
    ".popup",
    ".related",
    ".share",
    ".sharing",
    ".sidebar",
    ".social",
)

CONTENT_SELECTORS = (
    "article",
    "main",
    "[role='main']",
    "[itemprop='articleBody']",
    ".article-content",
    ".article-body",
    ".entry-content",
    ".post-content",
    ".page-content",
    "#content",
)

MULTIPLE_BLANK_LINES_PATTERN = re.compile(r"\n{3,}")
TRAILING_WHITESPACE_PATTERN = re.compile(r"[ \t]+\n")
EMPTY_LINK_PATTERN = re.compile(r"\[\s*]\([^)]*\)")
EMPTY_IMAGE_PATTERN = re.compile(r"!\[\s*]\(\s*\)")
MARKDOWN_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+", re.MULTILINE)
INVALID_FILENAME_PATTERN = re.compile(r"[^a-z0-9._-]+")
DUPLICATE_HYPHENS_PATTERN = re.compile(r"-{2,}")


@dataclass(frozen=True, slots=True)
class MarkdownDocument:
    url: str
    title: str
    language: str
    markdown: str
    output_path: Path
    content_hash: str


class MarkdownExporter:
    def __init__(self, output_directory: Path) -> None:
        self._output_directory = output_directory.resolve()
        self._output_directory.mkdir(parents=True, exist_ok=True)

    def export(
        self,
        *,
        url: str,
        soup: BeautifulSoup,
        title: str,
        language: str,
        write: bool = True,
    ) -> MarkdownDocument:
        content = self._select_content(soup)
        cleaned_content = self._clean_content(content)

        markdown_body = markdownify(
            str(cleaned_content),
            heading_style="ATX",
            bullets="-",
            strip=["script", "style"],
        )

        markdown_body = self._normalize_markdown(markdown_body)

        if not markdown_body:
            raise ValueError(f"No meaningful Markdown content found: {url}")

        resolved_title = title.strip() or self._extract_heading(markdown_body)
        resolved_title = resolved_title or url

        digest = hashlib.sha256(markdown_body.encode("utf-8")).hexdigest()

        document = MarkdownDocument(
            url=url,
            title=resolved_title,
            language=language,
            markdown=markdown_body,
            output_path=self._build_output_path(
                url=url,
                title=resolved_title,
            ),
            content_hash=digest,
        )

        if write:
            self.write(document)

        return document

    def write(
        self,
        document: MarkdownDocument,
    ) -> None:
        """Atomically persist a prepared Markdown document."""

        document_text = self._render_document(
            url=document.url,
            title=document.title,
            language=document.language,
            content_hash=document.content_hash,
            markdown_body=document.markdown,
        )

        self._atomic_write(
            output_path=document.output_path,
            content=document_text,
        )

    @staticmethod
    def _render_document(
        *,
        url: str,
        title: str,
        language: str,
        content_hash: str,
        markdown_body: str,
    ) -> str:
        """Render a prepared Markdown document with deterministic metadata."""

        normalized_body = markdown_body.rstrip()

        metadata = (
            "---\n"
            f"url: {json.dumps(url, ensure_ascii=False)}\n"
            f"title: {json.dumps(title, ensure_ascii=False)}\n"
            f"language: {json.dumps(language, ensure_ascii=False)}\n"
            f"content_hash: {content_hash}\n"
            "---\n\n"
        )

        return f"{metadata}{normalized_body}\n"

    @staticmethod
    def _select_content(soup: BeautifulSoup) -> Tag:
        for selector in CONTENT_SELECTORS:
            candidate = soup.select_one(selector)

            if candidate is None:
                continue

            candidate_text = candidate.get_text(" ", strip=True)

            if len(candidate_text) >= 100:
                return candidate

        if soup.body is not None:
            return soup.body

        return soup

    @staticmethod
    def _clean_content(content: Tag) -> BeautifulSoup:
        cleaned = BeautifulSoup(str(content), "html.parser")

        for selector in REMOVE_SELECTORS:
            for element in cleaned.select(selector):
                element.decompose()

        for element in cleaned.find_all(True):
            attributes_to_remove = tuple(
                attribute
                for attribute in element.attrs
                if attribute.lower().startswith("on")
                or attribute.lower()
                in {
                    "class",
                    "contenteditable",
                    "data-testid",
                    "dir",
                    "draggable",
                    "hidden",
                    "id",
                    "role",
                    "style",
                    "tabindex",
                }
            )

            for attribute in attributes_to_remove:
                element.attrs.pop(attribute, None)

        for anchor in cleaned.find_all("a"):
            href = anchor.get("href")

            if not isinstance(href, str) or not href.strip():
                anchor.unwrap()

        for image in cleaned.find_all("img"):
            source = image.get("src")
            alt = image.get("alt")

            if not isinstance(source, str) or not source.strip():
                image.decompose()
                continue

            if not isinstance(alt, str):
                image["alt"] = ""

        return cleaned

    @staticmethod
    def _normalize_markdown(value: str) -> str:
        normalized = value.replace("\r\n", "\n").replace("\r", "\n")
        normalized = TRAILING_WHITESPACE_PATTERN.sub("\n", normalized)
        normalized = EMPTY_LINK_PATTERN.sub("", normalized)
        normalized = EMPTY_IMAGE_PATTERN.sub("", normalized)
        normalized = MULTIPLE_BLANK_LINES_PATTERN.sub("\n\n", normalized)
        normalized = normalized.strip()

        return f"{normalized}\n" if normalized else ""

    @staticmethod
    def _extract_heading(markdown_body: str) -> str:
        for line in markdown_body.splitlines():
            stripped = line.strip()

            if not stripped.startswith("#"):
                continue

            heading = MARKDOWN_HEADING_PATTERN.sub("", stripped).strip()

            if heading:
                return heading

        return ""

    def _build_output_path(
        self,
        *,
        url: str,
        title: str,
    ) -> Path:
        parsed = urlparse(url)
        hostname = self._slugify(parsed.hostname or "unknown-host")

        path_segments = [
            self._slugify(segment)
            for segment in parsed.path.split("/")
            if segment.strip()
        ]

        title_slug = self._slugify(title)[:100] or "page"
        url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]

        directory = self._output_directory / hostname

        if path_segments:
            directory = directory.joinpath(*path_segments[:-1])

        directory.mkdir(parents=True, exist_ok=True)

        final_segment = path_segments[-1][:80] if path_segments else title_slug

        filename = f"{final_segment}-{url_hash}.md"
        output_path = (directory / filename).resolve()

        if (
            output_path != self._output_directory
            and self._output_directory not in output_path.parents
        ):
            raise ValueError(f"Generated path escaped output directory: {output_path}")

        return output_path

    @staticmethod
    def _slugify(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value)
        ascii_value = normalized.encode(
            "ascii",
            errors="ignore",
        ).decode("ascii")
        lowered = ascii_value.lower().strip()
        slug = INVALID_FILENAME_PATTERN.sub("-", lowered)
        slug = DUPLICATE_HYPHENS_PATTERN.sub("-", slug)
        return slug.strip("-._") or "page"

    @staticmethod
    def _yaml_string(value: str) -> str:
        escaped = (
            value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").strip()
        )
        return f'"{escaped}"'

    def _build_document(
        self,
        *,
        url: str,
        title: str,
        language: str,
        content_hash: str,
        markdown_body: str,
    ) -> str:
        generated_at = datetime.now(UTC).isoformat()

        frontmatter = "\n".join(
            (
                "---",
                f"title: {self._yaml_string(title)}",
                f"url: {self._yaml_string(url)}",
                f"language: {self._yaml_string(language)}",
                f"content_hash: {self._yaml_string(content_hash)}",
                f"generated_at: {self._yaml_string(generated_at)}",
                "---",
                "",
            )
        )

        return f"{frontmatter}{markdown_body}"

    @staticmethod
    def _atomic_write(
        *,
        output_path: Path,
        content: str,
    ) -> None:
        temporary_path = output_path.with_suffix(f"{output_path.suffix}.tmp")

        temporary_path.write_text(
            content,
            encoding="utf-8",
        )
        temporary_path.replace(output_path)
