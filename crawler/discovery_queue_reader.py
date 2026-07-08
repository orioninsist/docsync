"""Backward-compatible queue reader exports."""

from __future__ import annotations

from crawler.queue_file import read_urls_from_txt

__all__ = ["read_urls_from_txt"]
