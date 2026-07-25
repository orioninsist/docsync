from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlparse


IMPORTANT_QUERY_KEYS_FOR_SLUG = {
    "segment",
    "section",
    "category",
    "topic",
    "locale",
    "lang",
    "language",
    "hl",
}


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"^https?://", "", value)
    value = re.sub(r"^www\.", "", value)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")

    return value or "site"


def is_url(value: str) -> bool:
    parsed = urlparse(value)

    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def guess_default_site(workspace_name: str) -> str:
    value = workspace_name.strip()

    if is_url(value):
        return value

    if "." in value:
        return value

    return f"{value}.com"


def build_query_slug(start_url: str) -> str:
    parsed = urlparse(start_url)
    parts: list[str] = []

    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        normalized_key = key.lower().strip()
        normalized_value = value.strip()

        if normalized_key in IMPORTANT_QUERY_KEYS_FOR_SLUG and normalized_value:
            parts.append(f"{normalized_key}-{normalized_value}")

    return slugify("-".join(parts)) if parts else ""


def build_project_slug(start_url: str) -> str:
    parsed = urlparse(start_url)
    domain = slugify(parsed.netloc)
    path = parsed.path.strip("/")

    if not path:
        base = domain
    else:
        base = f"{domain}-{slugify(path.replace('/', '-'))}"

    query_slug = build_query_slug(start_url)

    return f"{base}-{query_slug}" if query_slug else base


def is_github_repository_scope(start_url: str) -> bool:
    parsed = urlparse(start_url)
    host = parsed.netloc.lower().removeprefix("www.")

    if host != "github.com":
        return False

    parts = [part for part in parsed.path.strip("/").split("/") if part]

    return len(parts) >= 2


def should_allow_cross_host_discovery(start_url: str) -> bool:
    return not is_github_repository_scope(start_url)
