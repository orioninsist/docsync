from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DuplicateDecision:
    is_duplicate: bool
    canonical_url: str
    canonical_path: str
    content_hash: str


class DuplicateRegistry:
    """Persistent content-hash registry backed by SQLite."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path.resolve()
        self._database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self._initialize()

    def register(
        self,
        *,
        content_hash: str,
        url: str,
        output_path: Path,
        title: str,
    ) -> DuplicateDecision:
        normalized_hash = content_hash.strip().lower()
        normalized_url = url.strip()
        normalized_path = str(output_path.resolve())
        normalized_title = title.strip()

        if not normalized_hash:
            raise ValueError("content_hash cannot be empty")

        if not normalized_url:
            raise ValueError("url cannot be empty")

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")

            existing = connection.execute(
                """
                SELECT canonical_url, canonical_path
                FROM content_records
                WHERE content_hash = ?
                """,
                (normalized_hash,),
            ).fetchone()

            if existing is not None:
                canonical_url = str(existing[0])
                canonical_path = str(existing[1])

                connection.execute(
                    """
                    INSERT INTO duplicate_urls (
                        url,
                        content_hash,
                        canonical_url,
                        canonical_path
                    )
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(url) DO UPDATE SET
                        content_hash = excluded.content_hash,
                        canonical_url = excluded.canonical_url,
                        canonical_path = excluded.canonical_path,
                        detected_at = CURRENT_TIMESTAMP
                    """,
                    (
                        normalized_url,
                        normalized_hash,
                        canonical_url,
                        canonical_path,
                    ),
                )

                connection.commit()

                return DuplicateDecision(
                    is_duplicate=True,
                    canonical_url=canonical_url,
                    canonical_path=canonical_path,
                    content_hash=normalized_hash,
                )

            connection.execute(
                """
                INSERT INTO content_records (
                    content_hash,
                    canonical_url,
                    canonical_path,
                    title
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    normalized_hash,
                    normalized_url,
                    normalized_path,
                    normalized_title,
                ),
            )

            connection.commit()

            return DuplicateDecision(
                is_duplicate=False,
                canonical_url=normalized_url,
                canonical_path=normalized_path,
                content_hash=normalized_hash,
            )

    def counts(self) -> tuple[int, int]:
        with self._connect() as connection:
            unique_count = int(
                connection.execute("SELECT COUNT(*) FROM content_records").fetchone()[0]
            )
            duplicate_count = int(
                connection.execute("SELECT COUNT(*) FROM duplicate_urls").fetchone()[0]
            )

        return unique_count, duplicate_count

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                PRAGMA synchronous = NORMAL;
                PRAGMA foreign_keys = ON;
                PRAGMA busy_timeout = 10000;

                CREATE TABLE IF NOT EXISTS content_records (
                    content_hash TEXT PRIMARY KEY,
                    canonical_url TEXT NOT NULL UNIQUE,
                    canonical_path TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS duplicate_urls (
                    url TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    canonical_path TEXT NOT NULL,
                    detected_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(content_hash)
                        REFERENCES content_records(content_hash)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS
                    duplicate_urls_content_hash_index
                ON duplicate_urls(content_hash);
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self._database_path,
            timeout=10,
        )
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
        finally:
            connection.close()
