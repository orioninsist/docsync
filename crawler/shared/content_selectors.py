"""Shared HTML content selector policies."""

from __future__ import annotations


MAIN_CONTENT_SELECTORS = (
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


PLAYWRIGHT_CONTENT_SELECTORS = (
    *MAIN_CONTENT_SELECTORS,
    "h1",
)
