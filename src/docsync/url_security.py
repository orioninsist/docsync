"""URL validation, normalization, scope, and redirect security."""

from __future__ import annotations

import re
from urllib.parse import (
    parse_qsl,
    urlencode,
    urlsplit,
    urlunsplit,
)

TRACKING_QUERY_KEYS = frozenset(
    {
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
        "ref",
        "referrer",
        "source",
    }
)

def validated_http_url(value: str) -> str:
    """Validate a credential-free absolute HTTP or HTTPS URL."""

    if not isinstance(value, str):
        raise TypeError("URL must be a string")

    candidate = value.strip()
    parsed = urlsplit(candidate)

    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError(f"Only HTTP and HTTPS URLs are permitted: {value!r}")

    if not parsed.hostname:
        raise ValueError(f"URL has no hostname: {value!r}")

    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs containing embedded credentials are not permitted")

    try:
        validated_port = parsed.port
    except ValueError as error:
        raise ValueError(f"URL contains an invalid port: {value!r}") from error

    del validated_port
    return candidate


def normalize_url(url: str) -> str:
    """Normalize a validated URL deterministically."""

    validated = validated_http_url(url)
    parts = urlsplit(validated)

    scheme = parts.scheme.lower()
    hostname = (parts.hostname or "").rstrip(".").lower()

    try:
        port = parts.port
    except ValueError as error:
        raise ValueError(f"URL contains an invalid port: {url!r}") from error

    if (
        port is None
        or (scheme == "http" and port == 80)
        or (scheme == "https" and port == 443)
    ):
        netloc = hostname
    else:
        netloc = f"{hostname}:{port}"

    path = re.sub(r"/{2,}", "/", parts.path or "/")

    if path != "/":
        path = path.rstrip("/")

    filtered_query: list[tuple[str, str]] = []

    for key, value in parse_qsl(
        parts.query,
        keep_blank_values=True,
    ):
        lowered_key = key.lower()

        if lowered_key.startswith("utm_") or lowered_key in TRACKING_QUERY_KEYS:
            continue

        filtered_query.append((key, value))

    query = urlencode(sorted(filtered_query))

    normalized_url: str = urlunsplit(
        (
            scheme,
            netloc,
            path,
            query,
            "",
        )
    )
    return normalized_url


