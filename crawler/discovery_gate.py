"""Discovery URL gate helpers for smart queue candidate filtering."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import parse_qsl, urlparse

from crawler.shared.iso_language_gate import url_declares_non_english_or_region


def raw_discovery_block_reason(
    raw_url: str,
    *,
    utility_hosts: set[str],
    utility_path_parts: set[str],
) -> str | None:
    """Return a raw discovery block reason before URL normalization."""
    iso_reason = url_declares_non_english_or_region(raw_url)
    if iso_reason:
        return iso_reason

    parsed = urlparse(raw_url)
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.lower()
    parts = [
        part.strip().lower() for part in path.strip("/").split("/") if part.strip()
    ]

    reason: str | None = None
    if host in utility_hosts:
        reason = f"utility_app_host:{host}"
    elif parts and parts[0] in utility_path_parts:
        reason = f"utility_path:{parts[0]}"
    elif path.startswith("/_/"):
        reason = "utility_internal_path:_"

    return reason


def extract_redirect_targets(raw_url: str) -> list[str]:
    """Extract nested absolute redirect target URLs from query parameters."""
    parsed = urlparse(raw_url)
    targets: list[str] = []

    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        if key.lower().strip() not in {
            "url",
            "q",
            "continue",
            "target",
            "dest",
            "destination",
        }:
            continue

        value = value.strip()
        if value.startswith(("http://", "https://")):
            targets.append(value)

    return list(dict.fromkeys(targets))


def final_txt_candidate(  # pylint: disable=too-many-arguments
    *,
    seed_url: str,
    raw_url: str,
    raw_block_reason: Callable[[str], str | None],
    normalize_url: Callable[[str], str | None],
    is_bad_url: Callable[[str], str | None],
    looks_like_official_host: Callable[[str, str], bool],
    promote_root: Callable[[str], str],
) -> tuple[str | None, str | None]:
    """Return the final TXT candidate URL or the reason it was blocked."""
    raw_block = raw_block_reason(raw_url)
    if raw_block:
        return None, raw_block

    clean = normalize_url(raw_url)
    if clean is None:
        return None, "invalid_or_unsafe_url"

    clean_block = raw_block_reason(clean)
    if clean_block:
        return None, clean_block

    bad = is_bad_url(clean)
    if bad:
        return None, bad

    if not looks_like_official_host(seed_url, clean):
        return None, "not_internal_or_official_like"

    return promote_root(clean), None
