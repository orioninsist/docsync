"""SQLite persistence helpers for isolated crawler discovery state."""

from __future__ import annotations

import hashlib
import random
import sqlite3
import time
from pathlib import Path
from typing import Callable, TypeVar
from urllib.parse import urlparse

DISCOVERY_STATE_ROOT = Path("state/discovery")
_SQLITE_BUSY_TIMEOUT_MS = 30_000
_SQLITE_MAX_WRITE_ATTEMPTS = 8
_SQLITE_INITIAL_RETRY_DELAY_SECONDS = 0.05
_SQLITE_MAX_RETRY_DELAY_SECONDS = 1.0

_ResultT = TypeVar("_ResultT")


def discovery_url_hash(url: str) -> str:
    """Return a stable SHA-256 hash for a discovery URL."""

    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _normalize_site(seed: str) -> str:
    """Normalize a seed into an absolute site URL."""

    clean_seed = seed.strip()

    if clean_seed.startswith(("http://", "https://")):
        return clean_seed

    return f"https://{clean_seed}"


def discovery_db_key(seed: str) -> str:
    """Return a stable logical partition key for one exact seed URL."""

    normalized_seed = _normalize_site(seed)
    return hashlib.sha256(normalized_seed.encode("utf-8")).hexdigest()


def _safe_host_slug(seed: str) -> str:
    """Return a filesystem-safe host label for a discovery database."""

    parsed = urlparse(_normalize_site(seed))
    host = parsed.netloc.lower().removeprefix("www.")

    safe = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in host
    ).strip("-")

    return safe or "unknown-host"


def discovery_db_path(seed: str) -> Path:
    """Return the isolated SQLite path for one exact seed URL."""

    seed_digest = discovery_db_key(seed)
    host_slug = _safe_host_slug(seed)

    return (
        DISCOVERY_STATE_ROOT
        / host_slug
        / f"{seed_digest}.db"
    )


def _configure_connection(connection: sqlite3.Connection) -> None:
    """Apply SQLite pragmas used by crawler discovery state."""

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL;")
    connection.execute("PRAGMA synchronous=NORMAL;")
    connection.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS};")
    connection.execute("PRAGMA foreign_keys=ON;")
    connection.execute("PRAGMA temp_store=MEMORY;")


def _create_schema(connection: sqlite3.Connection) -> None:
    """Create discovery persistence tables and indexes."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS discovery_seen (
            seed_key TEXT NOT NULL,
            url_hash TEXT NOT NULL,
            url TEXT NOT NULL,
            depth INTEGER NOT NULL,
            status TEXT NOT NULL,
            discovered_from TEXT,
            reason TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(seed_key, url_hash)
        );
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_discovery_seen_seed_status
        ON discovery_seen(seed_key, status);
        """
    )


def _is_locked_error(error: sqlite3.OperationalError) -> bool:
    """Return whether an SQLite operational error is lock-related."""

    message = str(error).lower()

    return (
        "database is locked" in message
        or "database table is locked" in message
        or "database schema is locked" in message
        or "busy" in message
    )


def _rollback_quietly(connection: sqlite3.Connection) -> None:
    """Rollback an active transaction without masking the original error."""

    try:
        connection.rollback()
    except sqlite3.Error:
        pass


def _run_write_with_retry(
    connection: sqlite3.Connection,
    operation: Callable[[], _ResultT],
) -> _ResultT:
    """Run one short SQLite write transaction with bounded retry/backoff."""

    delay = _SQLITE_INITIAL_RETRY_DELAY_SECONDS
    last_error: sqlite3.OperationalError | None = None

    for attempt in range(1, _SQLITE_MAX_WRITE_ATTEMPTS + 1):
        try:
            connection.execute("BEGIN IMMEDIATE;")
            result = operation()
            connection.commit()
            return result
        except sqlite3.OperationalError as error:
            _rollback_quietly(connection)

            if not _is_locked_error(error):
                raise

            last_error = error

            if attempt >= _SQLITE_MAX_WRITE_ATTEMPTS:
                break

            jitter = random.uniform(0.0, delay * 0.25)
            time.sleep(delay + jitter)
            delay = min(
                delay * 2,
                _SQLITE_MAX_RETRY_DELAY_SECONDS,
            )
        except Exception:
            _rollback_quietly(connection)
            raise

    if last_error is None:
        raise RuntimeError("SQLite write retry loop ended without an error.")

    raise last_error


def open_discovery_db(seed: str) -> sqlite3.Connection:
    """Open and initialize the isolated database for one seed URL."""

    db_path = discovery_db_path(seed)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        str(db_path),
        timeout=_SQLITE_BUSY_TIMEOUT_MS / 1000,
        isolation_level=None,
    )

    _configure_connection(connection)

    def initialize() -> None:
        _create_schema(connection)

    _run_write_with_retry(connection, initialize)
    return connection


def discovery_mark_seen(
    connection: sqlite3.Connection,
    *,
    seed_key: str,
    url: str,
    depth: int,
    status: str,
    discovered_from: str | None,
    reason: str,
) -> bool:
    """Insert a URL into discovery state and return False for duplicates."""

    def insert() -> bool:
        try:
            connection.execute(
                """
                INSERT INTO discovery_seen (
                    seed_key,
                    url_hash,
                    url,
                    depth,
                    status,
                    discovered_from,
                    reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    seed_key,
                    discovery_url_hash(url),
                    url,
                    depth,
                    status,
                    discovered_from,
                    reason,
                ),
            )
            return True
        except sqlite3.IntegrityError:
            return False

    return _run_write_with_retry(connection, insert)


def discovery_update_seen_status(
    connection: sqlite3.Connection,
    *,
    seed_key: str,
    url: str,
    status: str,
    reason: str,
) -> None:
    """Update status and reason for an existing discovery URL."""

    def update() -> None:
        connection.execute(
            """
            UPDATE discovery_seen
            SET status = ?,
                reason = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE seed_key = ?
              AND url_hash = ?;
            """,
            (
                status,
                reason,
                seed_key,
                discovery_url_hash(url),
            ),
        )

    _run_write_with_retry(connection, update)
