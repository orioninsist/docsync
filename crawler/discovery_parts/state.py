"""SQLite persistence helpers for crawler discovery state."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

DISCOVERY_DB_PATH = Path("state/global/discovery_seen.db")
_SQLITE_BUSY_TIMEOUT_MS = 30_000


def discovery_url_hash(url: str) -> str:
    """Return a stable SHA-256 hash for a discovery URL."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _normalize_site(seed: str) -> str:
    """Normalize a seed into an absolute site URL without importing discovery."""
    clean_seed = seed.strip()
    if clean_seed.startswith(("http://", "https://")):
        return clean_seed
    return f"https://{clean_seed}"


def discovery_db_key(seed: str) -> str:
    """Return a stable database partition key for a seed site."""
    parsed = urlparse(_normalize_site(seed))
    return parsed.netloc.lower().removeprefix("www.")


def _configure_connection(connection: sqlite3.Connection) -> None:
    """Apply SQLite pragmas used by crawler discovery state."""
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL;")
    connection.execute("PRAGMA synchronous=NORMAL;")
    connection.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS};")


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


def open_discovery_db() -> sqlite3.Connection:
    """Open and initialize the SQLite discovery database."""
    DISCOVERY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(DISCOVERY_DB_PATH))
    _configure_connection(connection)
    _create_schema(connection)
    connection.commit()
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
        connection.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def discovery_update_seen_status(
    connection: sqlite3.Connection,
    *,
    seed_key: str,
    url: str,
    status: str,
    reason: str,
) -> None:
    """Update status and reason for an existing discovery URL."""
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
    connection.commit()
