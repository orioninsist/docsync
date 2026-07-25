"""Deterministic content-cleaning boundary for document ingestion.

This module performs isolated, repeatable text cleanup on immutable ingestion
documents. It does not access the filesystem, convert source formats, calculate
budgets, perform semantic analysis, route documents, persist data, or coordinate
pipeline execution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from pipeline.ingestion.config import TransformationConfig
from pipeline.ingestion.model import IngestionDocument

_HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->", flags=re.DOTALL)
_MARKDOWN_HEADING_PATTERN = re.compile(
    r"^(?P<prefix>#{1,6})[ \t]+(?P<title>.+?)[ \t]*#*[ \t]*$"
)
_BULLET_PATTERN = re.compile(
    r"^(?P<indent>[ \t]*)(?P<marker>[-+*])(?P<spacing>[ \t]+)(?P<body>.*)$"
)
_COMMENTED_CODE_PATTERN = re.compile(
    "".join(
        (
            r"^[ \t]*(?://|#)[ \t]*(?P<code>",
            r"(?:class|def|return|import|from|if|elif|else|for|while|try|except|",
            r"finally|with|raise|yield|async|await|const|let|var|function)\b.*)$",
        )
    )
)
_HISTORICAL_HEADING_TITLES = frozenset(
    {
        "change log",
        "changelog",
        "changes",
        "history",
        "release history",
        "release notes",
        "releases",
        "version history",
    }
)


class ContentCleaningError(ValueError):
    """Raised when content-cleaning input violates its contract."""


class DocumentCleaner(Protocol):
    """Define the plug-in contract for isolated document cleaners."""

    def clean(self, document: IngestionDocument) -> IngestionDocument:
        """Return a cleaned immutable document."""
        ...


@dataclass(frozen=True, slots=True)
class DeterministicContentCleaner:
    """Clean document text using explicit deterministic transformations."""

    config: TransformationConfig = TransformationConfig()

    def clean(self, document: IngestionDocument) -> IngestionDocument:
        """Return a new document containing deterministically cleaned text."""
        cleaned_content = clean_content(
            document.content,
            config=self.config,
        )

        if cleaned_content == document.content:
            return document

        return document.with_content(
            cleaned_content,
            media_type=document.media_type,
            title=document.title,
        )


def clean_document(
    document: IngestionDocument,
    *,
    cleaner: DocumentCleaner,
) -> IngestionDocument:
    """Clean one document through an explicitly supplied cleaner."""
    cleaned_document = cleaner.clean(document)

    if cleaned_document.identity != document.identity:
        raise ContentCleaningError(
            "cleaner must preserve document identity",
        )

    if cleaned_document.source_path != document.source_path:
        raise ContentCleaningError(
            "cleaner must preserve document source_path",
        )

    return cleaned_document


def clean_content(
    content: str,
    *,
    config: TransformationConfig,
) -> str:
    """Return deterministically cleaned document content."""
    cleaned = _normalize_newlines(content)

    if config.strip_html_comments:
        cleaned = _strip_html_comments(cleaned)

    if config.strip_historical_changelogs:
        cleaned = _strip_historical_sections(cleaned)

    if config.strip_commented_code:
        cleaned = _strip_commented_code(cleaned)

    if config.consolidate_duplicate_headers:
        cleaned = _consolidate_duplicate_headers(cleaned)

    if config.collapse_redundant_bullet_levels:
        cleaned = _collapse_redundant_bullet_levels(cleaned)

    cleaned = _strip_trailing_whitespace(cleaned)

    if config.ensure_single_blank_line:
        cleaned = _ensure_single_blank_line(cleaned)

    return _normalize_document_boundary(cleaned)


def _normalize_newlines(content: str) -> str:
    return content.replace("\r\n", "\n").replace("\r", "\n")


def _strip_html_comments(content: str) -> str:
    return _HTML_COMMENT_PATTERN.sub("", content)


def _strip_historical_sections(content: str) -> str:
    lines = content.splitlines()
    retained_lines: list[str] = []
    index = 0

    while index < len(lines):
        heading = _parse_markdown_heading(lines[index])

        if heading is None or not _is_historical_heading(heading.title):
            retained_lines.append(lines[index])
            index += 1
            continue

        index = _find_next_peer_or_parent_heading(
            lines,
            start_index=index + 1,
            maximum_level=heading.level,
        )

    return "\n".join(retained_lines)


def _strip_commented_code(content: str) -> str:
    retained_lines = [
        line
        for line in content.splitlines()
        if _COMMENTED_CODE_PATTERN.fullmatch(line) is None
    ]
    return "\n".join(retained_lines)


def _consolidate_duplicate_headers(content: str) -> str:
    retained_lines: list[str] = []
    previous_heading_key: tuple[int, str] | None = None

    for line in content.splitlines():
        heading = _parse_markdown_heading(line)

        if heading is None:
            retained_lines.append(line)

            if line.strip():
                previous_heading_key = None

            continue

        heading_key = (
            heading.level,
            _normalize_heading_title(heading.title),
        )

        if heading_key == previous_heading_key:
            continue

        retained_lines.append(line)
        previous_heading_key = heading_key

    return "\n".join(retained_lines)


def _collapse_redundant_bullet_levels(content: str) -> str:
    normalized_lines: list[str] = []

    for line in content.splitlines():
        match = _BULLET_PATTERN.fullmatch(line)

        if match is None:
            normalized_lines.append(line)
            continue

        indent_width = _calculate_indent_width(match.group("indent"))
        normalized_indent = " " * ((indent_width // 2) * 2)
        normalized_lines.append(
            f"{normalized_indent}- {match.group('body').rstrip()}",
        )

    return "\n".join(normalized_lines)


def _strip_trailing_whitespace(content: str) -> str:
    return "\n".join(line.rstrip() for line in content.splitlines())


def _ensure_single_blank_line(content: str) -> str:
    normalized_lines: list[str] = []
    previous_was_blank = False

    for line in content.splitlines():
        is_blank = not line.strip()

        if is_blank and previous_was_blank:
            continue

        normalized_lines.append("" if is_blank else line)
        previous_was_blank = is_blank

    return "\n".join(normalized_lines)


def _normalize_document_boundary(content: str) -> str:
    normalized = content.strip()

    if not normalized:
        return ""

    return f"{normalized}\n"


@dataclass(frozen=True, slots=True)
class _MarkdownHeading:
    level: int
    title: str


def _parse_markdown_heading(line: str) -> _MarkdownHeading | None:
    match = _MARKDOWN_HEADING_PATTERN.fullmatch(line)

    if match is None:
        return None

    title = match.group("title").strip()

    if not title:
        return None

    return _MarkdownHeading(
        level=len(match.group("prefix")),
        title=title,
    )


def _is_historical_heading(title: str) -> bool:
    return _normalize_heading_title(title) in _HISTORICAL_HEADING_TITLES


def _normalize_heading_title(title: str) -> str:
    normalized_words = title.casefold().replace("_", " ").replace("-", " ").split()
    return " ".join(normalized_words)


def _find_next_peer_or_parent_heading(
    lines: list[str],
    *,
    start_index: int,
    maximum_level: int,
) -> int:
    index = start_index

    while index < len(lines):
        heading = _parse_markdown_heading(lines[index])

        if heading is not None and heading.level <= maximum_level:
            return index

        index += 1

    return len(lines)


def _calculate_indent_width(indent: str) -> int:
    width = 0

    for character in indent:
        width += 4 if character == "\t" else 1

    return width


__all__ = [
    "ContentCleaningError",
    "DeterministicContentCleaner",
    "DocumentCleaner",
    "clean_content",
    "clean_document",
]
