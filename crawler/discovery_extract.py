"""Discovery extraction wrappers.

Single responsibility:
- Expose stable extraction entrypoints backed by the legacy discovery module.
"""

from __future__ import annotations

from crawler.discovery import extract_real_urls_from_html


def extract_real_urls(html: str, base_url: str) -> list[str]:
    """Extract real URLs from HTML using the legacy discovery extractor."""
    return list(extract_real_urls_from_html(html, base_url))


def extract_recursive_links(html: str, base_url: str) -> list[str]:
    """Extract recursive links without depending on private legacy symbols."""
    return extract_real_urls(html, base_url)
