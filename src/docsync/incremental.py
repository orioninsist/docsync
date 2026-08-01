"""Persistent state and decisions for incremental synchronization."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from docsync.url_security import normalize_url

DEFAULT_REFRESH_HOURS = 24

STATE_DIR = Path("storage/docsync")
CONTENT_HASH_FILENAME = "content_hashes.json"
URL_STATE_FILENAME = "url_state.json"
CONTENT_HASH_FILE = STATE_DIR / CONTENT_HASH_FILENAME
URL_STATE_FILE = STATE_DIR / URL_STATE_FILENAME


class IncrementalConfig(Protocol):
    """Configuration required by incremental filtering."""

    refresh_hours: int
    force_refresh: bool


class IncrementalStats(Protocol):
    """Statistics required by incremental filtering."""

    incremental_skipped: int
    incremental_skipped_urls: set[str]


def content_hash(markdown: str) -> str:
    """Return a stable SHA-256 digest for normalized Markdown content."""

    normalized = markdown.replace("\r\n", "\n").replace("\r", "\n")
    body = normalized.strip()

    return hashlib.sha256(
        body.encode("utf-8"),
    ).hexdigest()


def load_content_hashes(
    state_dir: Path | None = None,
) -> dict[str, str]:
    """Load the legacy content-hash mapping safely."""

    content_hash_file = (
        state_dir.resolve() / CONTENT_HASH_FILENAME
        if state_dir is not None
        else CONTENT_HASH_FILE
    )

    if not content_hash_file.exists():
        return {}

    try:
        payload = json.loads(
            content_hash_file.read_text(
                encoding="utf-8",
            )
        )
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(payload, dict):
        return {}

    return {
        str(key): str(value)
        for key, value in payload.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def save_content_hashes(
    hashes: dict[str, str],
    state_dir: Path | None = None,
) -> None:
    """Atomically replace the content-hash state file."""

    content_hash_file = (
        state_dir.resolve() / CONTENT_HASH_FILENAME
        if state_dir is not None
        else CONTENT_HASH_FILE
    )

    content_hash_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    serialized = json.dumps(
        hashes,
        indent=2,
        sort_keys=True,
    )

    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=content_hash_file.parent,
        prefix=f".{content_hash_file.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)

    try:
        with os.fdopen(
            file_descriptor,
            mode="w",
            encoding="utf-8",
        ) as temporary_file:
            temporary_file.write(serialized)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        temporary_path.replace(content_hash_file)
    finally:
        temporary_path.unlink(missing_ok=True)


def load_url_state(
    state_dir: Path | None = None,
) -> dict[str, dict[str, str]]:
    """Load valid legacy URL-state records safely."""

    url_state_file = (
        state_dir.resolve() / URL_STATE_FILENAME
        if state_dir is not None
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

        if not isinstance(saved_at, str):
            continue

        result[url] = {
            "saved_at": saved_at,
            "filename": (filename if isinstance(filename, str) else ""),
            "content_hash": (digest if isinstance(digest, str) else ""),
        }

    return result


def save_url_state(
    state: dict[str, dict[str, str]],
    state_dir: Path | None = None,
) -> None:
    """Atomically replace the URL-state file."""

    url_state_file = (
        state_dir.resolve() / URL_STATE_FILENAME
        if state_dir is not None
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
    config: IncrementalConfig,
    url_state: dict[str, dict[str, str]],
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether a URL is still inside its refresh window."""

    if config.force_refresh or config.refresh_hours == 0:
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
        hours=config.refresh_hours,
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
    config: IncrementalConfig,
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
            config,
            url_state,
        ):
            record_incremental_skip(
                normalized,
                stats,
            )
            continue

        selected.append(normalized)

    return selected


def record_incremental_success(
    *,
    url: str,
    output_path: Path,
    digest: str,
    hashes: dict[str, str],
    url_state: dict[str, dict[str, str]],
    saved_at: datetime | None = None,
) -> None:
    """Record successful output in both legacy state stores."""

    normalized = normalize_url(url)
    normalized_digest = digest.strip().lower()

    if not normalized_digest:
        raise ValueError("digest cannot be empty")

    timestamp = saved_at.astimezone(UTC) if saved_at is not None else datetime.now(UTC)

    hashes[normalized_digest] = normalized
    url_state[normalized] = {
        "saved_at": timestamp.isoformat(),
        "filename": output_path.name,
        "content_hash": normalized_digest,
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
