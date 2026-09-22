"""Persistent state and decisions for incremental synchronization."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from docsync.url_security import normalize_url

STATE_DIR = Path("storage/docsync")
URL_STATE_SUFFIX = "url_state.json"
URL_STATE_FILE = STATE_DIR / URL_STATE_SUFFIX


def state_file_path(
    state_dir: Path,
    hostname: str,
    suffix: str,
) -> Path:
    """Return the flat per-host state file path."""

    normalized_hostname = hostname.strip().lower().rstrip(".")
    if not normalized_hostname:
        raise ValueError("hostname cannot be empty")
    if "/" in normalized_hostname or "\\" in normalized_hostname:
        raise ValueError("hostname must not contain path separators")

    return state_dir.resolve() / f"{normalized_hostname}_{suffix}"


class IncrementalStats(Protocol):
    """Statistics required by incremental filtering."""

    incremental_skipped: int
    incremental_skipped_urls: set[str]



def load_url_state(
    state_dir: Path | None = None,
    hostname: str | None = None,
) -> dict[str, dict[str, str]]:
    """Load valid URL-state records safely."""

    url_state_file = (
        state_file_path(state_dir, hostname, URL_STATE_SUFFIX)
        if state_dir is not None and hostname is not None
        else URL_STATE_FILE
    )

    if not url_state_file.exists():
        return {}

    try:
        payload = json.loads(
            url_state_file.read_text(
                encoding="utf-8",
            )
        )
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(payload, dict):
        return {}

    result: dict[str, dict[str, str]] = {}

    for url, value in payload.items():
        if not isinstance(url, str) or not isinstance(value, dict):
            continue

        saved_at = value.get("saved_at")
        filename = value.get("filename")
        digest = value.get("content_hash")
        etag = value.get("etag")
        last_modified = value.get("last_modified")

        if not isinstance(saved_at, str):
            continue

        result[url] = {
            "saved_at": saved_at,
            "filename": (filename if isinstance(filename, str) else ""),
            "content_hash": (digest if isinstance(digest, str) else ""),
            "etag": (etag if isinstance(etag, str) else ""),
            "last_modified": (last_modified if isinstance(last_modified, str) else ""),
        }

    return result


def save_url_state(
    state: dict[str, dict[str, str]],
    state_dir: Path | None = None,
    hostname: str | None = None,
) -> None:
    """Atomically replace the URL-state file."""

    url_state_file = (
        state_file_path(state_dir, hostname, URL_STATE_SUFFIX)
        if state_dir is not None and hostname is not None
        else URL_STATE_FILE
    )

    url_state_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = url_state_file.with_suffix(".tmp")

    temporary.write_text(
        json.dumps(
            state,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    temporary.replace(url_state_file)


def is_recently_saved(
    url: str,
    refresh_hours: int,
    force_refresh: bool,
    url_state: dict[str, dict[str, str]],
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether a URL is still inside its refresh window."""

    if force_refresh or refresh_hours == 0:
        return False

    normalized = normalize_url(url)
    entry = url_state.get(normalized)

    if entry is None:
        return False

    saved_at_text = entry.get("saved_at", "")

    if not saved_at_text:
        return False

    try:
        saved_at = datetime.fromisoformat(saved_at_text.replace("Z", "+00:00"))
    except ValueError:
        return False

    if saved_at.tzinfo is None:
        saved_at = saved_at.replace(tzinfo=UTC)
    else:
        saved_at = saved_at.astimezone(UTC)

    current_time = now.astimezone(UTC) if now is not None else datetime.now(UTC)

    age = current_time - saved_at

    if age < timedelta(0):
        return True

    return age < timedelta(
        hours=refresh_hours,
    )


def record_incremental_skip(
    url: str,
    stats: IncrementalStats,
) -> None:
    """Record one normalized incremental skip."""

    normalized = normalize_url(url)

    if normalized in stats.incremental_skipped_urls:
        return

    stats.incremental_skipped_urls.add(normalized)
    stats.incremental_skipped = len(stats.incremental_skipped_urls)


def filter_incremental_urls(
    urls: Iterable[str],
    refresh_hours: int,
    force_refresh: bool,
    stats: IncrementalStats,
    url_state: dict[str, dict[str, str]],
) -> list[str]:
    """Normalize, deduplicate, and remove fresh URLs."""

    selected: list[str] = []
    seen: set[str] = set()

    for url in urls:
        normalized = normalize_url(url)

        if normalized in seen:
            continue

        seen.add(normalized)

        if is_recently_saved(
            normalized,
            refresh_hours,
            force_refresh,
            url_state,
        ):
            record_incremental_skip(
                normalized,
                stats,
            )
            continue

        selected.append(normalized)

    return selected


def conditional_request_headers(
    *,
    url: str,
    url_state: dict[str, dict[str, str]],
    force_refresh: bool = False,
) -> dict[str, str]:
    """Return HTTP validators for a previously synchronized URL."""

    if force_refresh:
        return {}

    entry = url_state.get(normalize_url(url))
    if entry is None or not entry.get("content_hash", ""):
        return {}

    headers: dict[str, str] = {}
    etag = entry.get("etag", "").strip()
    last_modified = entry.get("last_modified", "").strip()

    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    return headers


def response_validators(headers: object) -> tuple[str, str]:
    """Extract cache validators from a Crawlee HTTP response header mapping."""

    getter = getattr(headers, "get", None)
    if getter is None:
        return "", ""

    etag = getter("etag") or ""
    last_modified = getter("last-modified") or ""
    return str(etag).strip(), str(last_modified).strip()


def record_incremental_success(
    *,
    url: str,
    output_path: Path,
    digest: str,
    url_state: dict[str, dict[str, str]],
    saved_at: datetime | None = None,
    etag: str = "",
    last_modified: str = "",
) -> None:
    """Record successful output in URL state."""

    normalized = normalize_url(url)
    normalized_digest = digest.strip().lower()

    if not normalized_digest:
        raise ValueError("digest cannot be empty")

    timestamp = saved_at.astimezone(UTC) if saved_at is not None else datetime.now(UTC)

    url_state[normalized] = {
        "saved_at": timestamp.isoformat(),
        "filename": output_path.name,
        "content_hash": normalized_digest,
        "etag": etag.strip(),
        "last_modified": last_modified.strip(),
    }


def content_is_unchanged(
    *,
    url: str,
    digest: str,
    url_state: dict[str, dict[str, str]],
) -> bool:
    """Return whether a URL already has the supplied digest."""

    normalized = normalize_url(url)
    entry = url_state.get(normalized)

    if entry is None:
        return False

    return entry.get("content_hash", "").lower() == digest.strip().lower()
