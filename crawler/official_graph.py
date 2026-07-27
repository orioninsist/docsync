"""Persistent storage for discovered official hosts."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

from crawler.shared.url_normalizer import normalize_url
from crawler.time_utils import utc_now

GRAPH_DB_PATH = Path("state/global/official_host_graph.db")


def host_of_url(url: str) -> str:
    """Return the normalized host of a URL."""

    normalized = normalize_url(url)
    candidate = normalized if normalized is not None else url.strip()

    return urlparse(candidate).netloc.lower().removeprefix("www.")


class OfficialHostGraph:
    """Learn and persist official hosts without making scope decisions."""

    seed_url: str
    owner_project: str
    seed_host: str
    db_path: Path
    connection: sqlite3.Connection

    def __init__(
        self,
        *,
        seed_url: str,
        owner_project: str,
        db_path: Path = GRAPH_DB_PATH,
    ) -> None:
        self.seed_url = seed_url
        self.owner_project = owner_project
        self.seed_host = host_of_url(seed_url)
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.connection = sqlite3.connect(str(self.db_path))
        self._configure()
        self._create_schema()
        self.learn_host(
            url=seed_url,
            parent_url=None,
            confidence=100,
            reason="seed_host",
            depth=0,
        )

    def _configure(self) -> None:
        """Configure SQLite for concurrent crawler access."""

        _ = self.connection.execute("PRAGMA journal_mode=WAL;")
        _ = self.connection.execute("PRAGMA synchronous=NORMAL;")
        _ = self.connection.execute("PRAGMA busy_timeout=30000;")

    def _create_schema(self) -> None:
        """Create the persistent official-host schema."""

        _ = self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS official_hosts (
                owner_project TEXT NOT NULL,
                seed_host TEXT NOT NULL,
                host TEXT NOT NULL,
                parent_host TEXT,
                confidence INTEGER NOT NULL,
                reason TEXT NOT NULL,
                depth INTEGER NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                PRIMARY KEY(owner_project, seed_host, host)
            );
            """
        )
        _ = self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_official_hosts_seed
            ON official_hosts(owner_project, seed_host);
            """
        )
        self.connection.commit()

    def close(self) -> None:
        """Close the persistent host graph connection."""

        self.connection.close()

    def known_hosts(self) -> set[str]:
        """Return every host learned for the current project and seed."""

        rows = cast(
            list[tuple[str]],
            self.connection.execute(
                """
                SELECT host
                FROM official_hosts
                WHERE owner_project = ?
                  AND seed_host = ?;
                """,
                (self.owner_project, self.seed_host),
            ).fetchall(),
        )

        return {host for (host,) in rows}

    def learn_host(
        self,
        *,
        url: str,
        parent_url: str | None,
        confidence: int,
        reason: str,
        depth: int,
    ) -> None:
        """Persist or strengthen one observed official host."""

        bounded_confidence = max(0, min(confidence, 100))
        bounded_depth = max(depth, 0)
        host = host_of_url(url)
        parent_host = host_of_url(parent_url) if parent_url else None
        now = utc_now()

        existing = cast(
            tuple[int, int] | None,
            self.connection.execute(
                """
                SELECT confidence, depth
                FROM official_hosts
                WHERE owner_project = ?
                  AND seed_host = ?
                  AND host = ?;
                """,
                (self.owner_project, self.seed_host, host),
            ).fetchone(),
        )

        if existing is None:
            self._insert_host(
                host=host,
                parent_host=parent_host,
                confidence=bounded_confidence,
                reason=reason,
                depth=bounded_depth,
                now=now,
            )
        else:
            existing_confidence, existing_depth = existing
            self._update_host(
                host=host,
                parent_host=parent_host,
                confidence=bounded_confidence,
                reason=reason,
                depth=bounded_depth,
                existing_confidence=existing_confidence,
                existing_depth=existing_depth,
                now=now,
            )

        self.connection.commit()

    def _insert_host(
        self,
        *,
        host: str,
        parent_host: str | None,
        confidence: int,
        reason: str,
        depth: int,
        now: str,
    ) -> None:
        """Insert a newly observed official host."""

        _ = self.connection.execute(
            """
            INSERT INTO official_hosts (
                owner_project,
                seed_host,
                host,
                parent_host,
                confidence,
                reason,
                depth,
                first_seen_at,
                last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                self.owner_project,
                self.seed_host,
                host,
                parent_host,
                confidence,
                reason,
                depth,
                now,
                now,
            ),
        )

    def _update_host(
        self,
        *,
        host: str,
        parent_host: str | None,
        confidence: int,
        reason: str,
        depth: int,
        existing_confidence: int,
        existing_depth: int,
        now: str,
    ) -> None:
        """Strengthen an existing official-host observation."""

        best_confidence = max(existing_confidence, confidence)
        best_depth = min(existing_depth, depth)

        _ = self.connection.execute(
            """
            UPDATE official_hosts
            SET
                parent_host = COALESCE(parent_host, ?),
                confidence = ?,
                reason = CASE
                    WHEN ? > confidence THEN ?
                    ELSE reason
                END,
                depth = ?,
                last_seen_at = ?
            WHERE owner_project = ?
              AND seed_host = ?
              AND host = ?;
            """,
            (
                parent_host,
                best_confidence,
                confidence,
                reason,
                best_depth,
                now,
                self.owner_project,
                self.seed_host,
                host,
            ),
        )
