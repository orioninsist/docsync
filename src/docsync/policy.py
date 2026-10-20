"""Shared DocsSync document and storage policy."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

NORMALIZE_DOCUMENT = r"""
() => {
  const root =
    document.querySelector('main') ||
    document.querySelector('article') ||
    document.body;

  if (!root) return null;

  const content = root.cloneNode(true);

  content.querySelectorAll('script,style').forEach(
    element => element.remove()
  );

  return content.innerHTML;
}
"""


TRACKING_QUERY_PARAMETERS = {
    "dclid",
    "fbclid",
    "gclid",
    "msclkid",
}


def canonicalize_url(url: str) -> str:
    """Remove non-content URL noise without changing semantic query parameters."""
    parsed = urlsplit(url)
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
            and key.lower() not in TRACKING_QUERY_PARAMETERS
        ],
        doseq=True,
    )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))


def normalize_language(value: str) -> str:
    language = value.strip().lower().replace("_", "-").split("-", 1)[0]
    if len(language) != 2 or not language.isalpha():
        raise ValueError("language must be a two-letter code such as 'en' or 'tr'")
    return language


def url_matches_language(url: str, language: str) -> bool:
    """Reject explicitly different Google-style hl language variants."""
    selected = normalize_language(language)
    query = parse_qsl(urlsplit(url).query, keep_blank_values=True)
    values = [value for key, value in query if key.lower() == "hl"]
    for value in values:
        if not value.strip():
            return False
        try:
            if normalize_language(value) != selected:
                return False
        except ValueError:
            return False
    return True


def hostname_for_url(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.hostname or parsed.scheme not in {"http", "https"}:
        raise ValueError("start_url must be an absolute HTTP(S) URL")
    return parsed.hostname


def url_is_within_start_scope(start_url: str, candidate_url: str) -> bool:
    """Return True only for the start URL itself or descendants of its path."""
    start = urlsplit(canonicalize_url(start_url))
    candidate = urlsplit(canonicalize_url(candidate_url))

    if candidate.scheme != start.scheme or candidate.netloc != start.netloc:
        return False

    root_path = start.path.rstrip("/")
    candidate_path = candidate.path.rstrip("/")

    if not root_path:
        return True

    return candidate_path == root_path or candidate_path.startswith(root_path + "/")


DOCUMENTATION_BASE_DIR = Path("/home/murat/Library/Documents/Documentation")
DOCSYNC_STATE_BASE_DIR = Path("/home/murat/Library/Data/docsync")


def site_dirname(start_url: str) -> str:
    parsed = urlsplit(start_url)
    if not parsed.hostname or parsed.scheme not in {"http", "https"}:
        raise ValueError("start_url must be an absolute HTTP(S) URL")

    parts = [parsed.hostname]
    parts.extend(part for part in parsed.path.split("/") if part)
    name = "-".join(parts)
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip("-")


def default_output_dir(start_url: str) -> Path:
    return DOCUMENTATION_BASE_DIR / site_dirname(start_url)


def default_state_dir(start_url: str) -> Path:
    return DOCSYNC_STATE_BASE_DIR / site_dirname(start_url)


def output_path(output_dir: Path, url: str) -> Path:
    parsed = urlsplit(url)
    path = parsed.path.strip("/") or "index"
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", path).strip("-") or "index"
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return output_dir / f"{slug}-{url_hash}.md"
