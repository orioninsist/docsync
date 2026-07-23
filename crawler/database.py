"""SQLite persistence layer for crawler state."""
# pylint: disable=missing-function-docstring,too-few-public-methods

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence, cast

from crawler.time_utils import utc_now

DEFAULT_QUEUE_PRIORITY = 500


@dataclass(frozen=True, slots=True)
class PageRecord:  # pylint: disable=too-many-instance-attributes
    """Normalized page persistence payload."""

    url: str
    url_hash: str
    final_url: str | None
    final_url_hash: str | None
    redirect_target_hash: str | None
    canonical_url: str | None
    content_hash: str | None
    etag: str | None
    last_modified: str | None
    status: str


class DatabaseManager:
    """Manage crawler SQLite persistence and queue state."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()

        self.connection = sqlite3.connect(
            self.db_path,
            timeout=30.0,
            isolation_level=None,
            check_same_thread=False,
        )
        self.connection.row_factory = sqlite3.Row

        self._configure_connection()
        self._create_tables()
        self._migrate_pages_table()
        self._migrate_url_queue_table()

    def _configure_connection(self) -> None:
        with self._lock:
            self.connection.execute("PRAGMA journal_mode=WAL;")
            self.connection.execute("PRAGMA synchronous=NORMAL;")
            self.connection.execute("PRAGMA busy_timeout=30000;")
            self.connection.execute("PRAGMA foreign_keys=ON;")
            self.connection.execute("PRAGMA temp_store=MEMORY;")

    def _execute_write(self, sql: str, parameters: tuple[object, ...] = ()) -> None:
        with self._lock:
            self.connection.execute("BEGIN IMMEDIATE;")
            try:
                self.connection.execute(sql, parameters)
                self.connection.execute("COMMIT;")
            except Exception:
                self.connection.execute("ROLLBACK;")
                raise

    def _execute_write_many(
        self,
        statements: Sequence[tuple[str, tuple[object, ...]]],
    ) -> None:
        with self._lock:
            self.connection.execute("BEGIN IMMEDIATE;")
            try:
                for sql, parameters in statements:
                    self.connection.execute(sql, parameters)
                self.connection.execute("COMMIT;")
            except Exception:
                self.connection.execute("ROLLBACK;")
                raise

    def _create_tables(self) -> None:
        statements = [
            (
                """
                CREATE TABLE IF NOT EXISTS pages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    url_hash TEXT NOT NULL UNIQUE,
                    final_url TEXT,
                    final_url_hash TEXT,
                    redirect_target_hash TEXT,
                    canonical_url TEXT,
                    content_hash TEXT,
                    etag TEXT,
                    last_modified TEXT,
                    status TEXT,
                    last_seen DATETIME,
                    last_updated DATETIME
                );
                """,
                (),
            ),
            (
                """
                CREATE TABLE IF NOT EXISTS url_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    url_hash TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'pending',
                    depth INTEGER NOT NULL DEFAULT 0,
                    priority INTEGER NOT NULL DEFAULT 500,
                    discovered_from TEXT,
                    created_at DATETIME,
                    updated_at DATETIME
                );
                """,
                (),
            ),
            (
                "CREATE INDEX IF NOT EXISTS idx_pages_content_hash ON pages(content_hash);",
                (),
            ),
            (
                "CREATE INDEX IF NOT EXISTS idx_pages_canonical_url ON pages(canonical_url);",
                (),
            ),
            (
                "CREATE INDEX IF NOT EXISTS idx_pages_final_url_hash ON pages(final_url_hash);",
                (),
            ),
            (
                "CREATE INDEX IF NOT EXISTS "
                "idx_pages_redirect_target_hash "
                "ON pages(redirect_target_hash);",
                (),
            ),
            (
                "CREATE INDEX IF NOT EXISTS idx_url_queue_status ON url_queue(status);",
                (),
            ),
            (
                "CREATE INDEX IF NOT EXISTS idx_url_queue_depth ON url_queue(depth);",
                (),
            ),
            (
                "CREATE INDEX IF NOT EXISTS idx_url_queue_priority ON url_queue(priority, id);",
                (),
            ),
            (
                "CREATE INDEX IF NOT EXISTS "
                "idx_url_queue_status_priority "
                "ON url_queue(status, priority, id);",
                (),
            ),
        ]

        self._execute_write_many(statements)

    def _migrate_pages_table(self) -> None:
        existing_columns = self._table_columns("pages")

        migrations = {
            "final_url": "ALTER TABLE pages ADD COLUMN final_url TEXT;",
            "final_url_hash": "ALTER TABLE pages ADD COLUMN final_url_hash TEXT;",
            "redirect_target_hash": "ALTER TABLE pages ADD COLUMN redirect_target_hash TEXT;",
            "etag": "ALTER TABLE pages ADD COLUMN etag TEXT;",
            "last_modified": "ALTER TABLE pages ADD COLUMN last_modified TEXT;",
        }

        statements: list[tuple[str, tuple[object, ...]]] = []

        for column, sql in migrations.items():
            if column not in existing_columns:
                statements.append((sql, ()))

        if statements:
            self._execute_write_many(statements)

    def _migrate_url_queue_table(self) -> None:
        existing_columns = self._table_columns("url_queue")
        statements: list[tuple[str, tuple[object, ...]]] = []

        if "priority" not in existing_columns:
            statements.append(
                (
                    "ALTER TABLE url_queue ADD COLUMN priority INTEGER NOT NULL DEFAULT 500;",
                    (),
                )
            )

        statements.extend(
            [
                (
                    "CREATE INDEX IF NOT EXISTS "
                    "idx_url_queue_priority "
                    "ON url_queue(priority, id);",
                    (),
                ),
                (
                    "CREATE INDEX IF NOT EXISTS "
                    "idx_url_queue_status_priority "
                    "ON url_queue(status, priority, id);",
                    (),
                ),
            ]
        )

        self._execute_write_many(statements)

    def _table_columns(self, table_name: str) -> set[str]:
        with self._lock:
            cursor = self.connection.execute(f"PRAGMA table_info({table_name});")
            return {str(row["name"]) for row in cursor.fetchall()}

    def get_by_url_hash(self, url_hash: str) -> Optional[sqlite3.Row]:
        with self._lock:
            cursor = self.connection.execute(
                """
                SELECT *
                FROM pages
                WHERE url_hash = ?
                LIMIT 1;
                """,
                (url_hash,),
            )
            return cast(sqlite3.Row | None, cursor.fetchone())

    def get_by_final_url_hash(self, final_url_hash: str) -> Optional[sqlite3.Row]:
        with self._lock:
            cursor = self.connection.execute(
                """
                SELECT *
                FROM pages
                WHERE final_url_hash = ?
                LIMIT 1;
                """,
                (final_url_hash,),
            )
            return cast(sqlite3.Row | None, cursor.fetchone())

    def get_by_redirect_target_hash(
        self,
        redirect_target_hash: str,
    ) -> Optional[sqlite3.Row]:
        with self._lock:
            cursor = self.connection.execute(
                """
                SELECT *
                FROM pages
                WHERE redirect_target_hash = ?
                LIMIT 1;
                """,
                (redirect_target_hash,),
            )
            return cast(sqlite3.Row | None, cursor.fetchone())

    def get_by_content_hash(self, content_hash: str) -> Optional[sqlite3.Row]:
        with self._lock:
            cursor = self.connection.execute(
                """
                SELECT *
                FROM pages
                WHERE content_hash = ?
                LIMIT 1;
                """,
                (content_hash,),
            )
            return cast(sqlite3.Row | None, cursor.fetchone())

    def get_by_canonical_url(self, canonical_url: str) -> Optional[sqlite3.Row]:
        with self._lock:
            cursor = self.connection.execute(
                """
                SELECT *
                FROM pages
                WHERE canonical_url = ?
                LIMIT 1;
                """,
                (canonical_url,),
            )
            return cast(sqlite3.Row | None, cursor.fetchone())

    def get_cache_headers_by_url_hash(self, url_hash: str) -> dict[str, str]:
        row = self.get_by_url_hash(url_hash)

        if row is None:
            return {}

        headers: dict[str, str] = {}

        if row["etag"]:
            headers["If-None-Match"] = str(row["etag"])

        if row["last_modified"]:
            headers["If-Modified-Since"] = str(row["last_modified"])

        return headers

    def _required_text_field(
        self,
        fields: Mapping[str, object],
        name: str,
    ) -> str:
        value = fields.get(name)

        if isinstance(value, str) and value:
            return value

        raise ValueError(f"Missing or invalid required page field: {name}")

    def _optional_text_field(
        self,
        fields: Mapping[str, object],
        name: str,
    ) -> str | None:
        value = fields.get(name)

        if value is None:
            return None

        if isinstance(value, str):
            return value

        raise ValueError(f"Invalid optional page field: {name}")

    def _bool_field(
        self,
        fields: Mapping[str, object],
        name: str,
        *,
        default: bool,
    ) -> bool:
        value = fields.get(name, default)

        if isinstance(value, bool):
            return value

        raise ValueError(f"Invalid boolean page field: {name}")

    def _page_record_from_fields(self, fields: Mapping[str, object]) -> PageRecord:
        return PageRecord(
            url=self._required_text_field(fields, "url"),
            url_hash=self._required_text_field(fields, "url_hash"),
            final_url=self._optional_text_field(fields, "final_url"),
            final_url_hash=self._optional_text_field(fields, "final_url_hash"),
            redirect_target_hash=self._optional_text_field(
                fields,
                "redirect_target_hash",
            ),
            canonical_url=self._optional_text_field(fields, "canonical_url"),
            content_hash=self._optional_text_field(fields, "content_hash"),
            etag=self._optional_text_field(fields, "etag"),
            last_modified=self._optional_text_field(fields, "last_modified"),
            status=self._required_text_field(fields, "status"),
        )

    def _existing_page_by_url_hash(self, url_hash: str) -> sqlite3.Row | None:
        cursor = self.connection.execute(
            """
            SELECT *
            FROM pages
            WHERE url_hash = ?
            LIMIT 1;
            """,
            (url_hash,),
        )
        return cast(sqlite3.Row | None, cursor.fetchone())

    def _insert_page(
        self,
        record: PageRecord,
        *,
        now: str,
        content_changed: bool,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO pages (
                url,
                url_hash,
                final_url,
                final_url_hash,
                redirect_target_hash,
                canonical_url,
                content_hash,
                etag,
                last_modified,
                status,
                last_seen,
                last_updated
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                record.url,
                record.url_hash,
                record.final_url,
                record.final_url_hash,
                record.redirect_target_hash,
                record.canonical_url,
                record.content_hash,
                record.etag,
                record.last_modified,
                record.status,
                now,
                now if content_changed else None,
            ),
        )

    def _update_page(
        self,
        record: PageRecord,
        existing: sqlite3.Row,
        *,
        now: str,
        content_changed: bool,
    ) -> None:
        last_updated = now if content_changed else existing["last_updated"]

        self.connection.execute(
            """
            UPDATE pages
            SET
                url = ?,
                final_url = ?,
                final_url_hash = ?,
                redirect_target_hash = ?,
                canonical_url = ?,
                content_hash = ?,
                etag = ?,
                last_modified = ?,
                status = ?,
                last_seen = ?,
                last_updated = ?
            WHERE url_hash = ?;
            """,
            (
                record.url,
                record.final_url,
                record.final_url_hash,
                record.redirect_target_hash,
                record.canonical_url,
                record.content_hash,
                record.etag,
                record.last_modified,
                record.status,
                now,
                last_updated,
                record.url_hash,
            ),
        )

    def upsert_page(self, **page_fields: object) -> None:
        record = self._page_record_from_fields(page_fields)
        content_changed = self._bool_field(
            page_fields,
            "content_changed",
            default=False,
        )
        now = utc_now()

        with self._lock:
            self.connection.execute("BEGIN IMMEDIATE;")

            try:
                existing = self._existing_page_by_url_hash(record.url_hash)

                if existing is None:
                    self._insert_page(
                        record,
                        now=now,
                        content_changed=content_changed,
                    )
                else:
                    self._update_page(
                        record,
                        existing,
                        now=now,
                        content_changed=content_changed,
                    )

                self.connection.execute("COMMIT;")

            except Exception:
                self.connection.execute("ROLLBACK;")
                raise

    def mark_status(self, **page_fields: object) -> None:
        normalized_fields = dict(page_fields)
        normalized_fields["content_changed"] = False
        self.upsert_page(**normalized_fields)

    def enqueue_url(
        self,
        *,
        url: str,
        url_hash: str,
        depth: int = 0,
        discovered_from: str | None = None,
        priority: int = DEFAULT_QUEUE_PRIORITY,
    ) -> bool:
        now = utc_now()
        priority = self._normalize_priority(priority)

        with self._lock:
            self.connection.execute("BEGIN IMMEDIATE;")

            try:
                self.connection.execute(
                    """
                    INSERT INTO url_queue (
                        url,
                        url_hash,
                        status,
                        depth,
                        priority,
                        discovered_from,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, 'pending', ?, ?, ?, ?, ?);
                    """,
                    (
                        url,
                        url_hash,
                        depth,
                        priority,
                        discovered_from,
                        now,
                        now,
                    ),
                )
                self.connection.execute("COMMIT;")
                return True

            except sqlite3.IntegrityError:
                self.connection.execute("ROLLBACK;")
                return False

            except Exception:
                self.connection.execute("ROLLBACK;")
                raise

    def requeue_url(
        self,
        *,
        url: str,
        url_hash: str,
        depth: int = 0,
        discovered_from: str | None = None,
        priority: int = DEFAULT_QUEUE_PRIORITY,
    ) -> None:
        now = utc_now()
        priority = self._normalize_priority(priority)

        self._execute_write(
            """
            UPDATE url_queue
            SET
                url = ?,
                status = 'pending',
                depth = ?,
                priority = MIN(priority, ?),
                discovered_from = COALESCE(?, discovered_from),
                updated_at = ?
            WHERE url_hash = ?;
            """,
            (
                url,
                depth,
                priority,
                discovered_from,
                now,
                url_hash,
            ),
        )

    def fetch_pending_urls(self, limit: int) -> list[sqlite3.Row]:
        with self._lock:
            cursor = self.connection.execute(
                """
                SELECT *
                FROM url_queue
                WHERE status = 'pending'
                ORDER BY priority ASC, id ASC
                LIMIT ?;
                """,
                (limit,),
            )
            return list(cursor.fetchall())

    def all_queue_url_hashes(self) -> set[str]:
        with self._lock:
            cursor = self.connection.execute(
                """
                SELECT url_hash
                FROM url_queue;
                """
            )
            return {str(row["url_hash"]) for row in cursor.fetchall()}

    def mark_queue_status(self, url_hash: str, status: str) -> None:
        allowed_statuses = {"pending", "processing", "done", "error"}

        if status not in allowed_statuses:
            raise ValueError(f"Invalid queue status: {status}")

        now = utc_now()

        self._execute_write(
            """
            UPDATE url_queue
            SET status = ?, updated_at = ?
            WHERE url_hash = ?;
            """,
            (
                status,
                now,
                url_hash,
            ),
        )

    def pending_queue_count(self) -> int:
        with self._lock:
            cursor = self.connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM url_queue
                WHERE status = 'pending';
                """
            )
            row = cursor.fetchone()
            return int(row["total"] if row else 0)

    def queued_count(self) -> int:
        with self._lock:
            cursor = self.connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM url_queue;
                """
            )
            row = cursor.fetchone()
            return int(row["total"] if row else 0)

    def reset_interrupted_processing(self) -> int:
        now = utc_now()

        with self._lock:
            self.connection.execute("BEGIN IMMEDIATE;")

            try:
                cursor = self.connection.execute(
                    """
                    UPDATE url_queue
                    SET status = 'pending', updated_at = ?
                    WHERE status = 'processing';
                    """,
                    (now,),
                )
                changed = int(cursor.rowcount if cursor.rowcount is not None else 0)
                self.connection.execute("COMMIT;")
                return changed

            except Exception:
                self.connection.execute("ROLLBACK;")
                raise

    def repair_missing_markdown_outputs(self, existing_url_hashes: set[str]) -> int:
        now = utc_now()
        repaired = 0

        with self._lock:
            self.connection.execute("BEGIN IMMEDIATE;")

            try:
                cursor = self.connection.execute(
                    """
                    SELECT url_hash
                    FROM url_queue
                    WHERE status = 'done';
                    """
                )

                rows = cursor.fetchall()

                for row in rows:
                    url_hash = str(row["url_hash"])

                    if url_hash in existing_url_hashes:
                        continue

                    self.connection.execute(
                        """
                        UPDATE url_queue
                        SET status = 'pending', updated_at = ?
                        WHERE url_hash = ?;
                        """,
                        (
                            now,
                            url_hash,
                        ),
                    )
                    repaired += 1

                self.connection.execute("COMMIT;")
                return repaired

            except Exception:
                self.connection.execute("ROLLBACK;")
                raise

    def queue_status_counts(self) -> dict[str, int]:
        with self._lock:
            cursor = self.connection.execute(
                """
                SELECT status, COUNT(*) AS total
                FROM url_queue
                GROUP BY status;
                """
            )

            counts = {
                "pending": 0,
                "processing": 0,
                "done": 0,
                "error": 0,
            }

            for row in cursor.fetchall():
                counts[str(row["status"])] = int(row["total"])

            return counts

    def _normalize_priority(self, priority: int) -> int:
        try:
            value = int(priority)
        except TypeError, ValueError:
            value = DEFAULT_QUEUE_PRIORITY

        return max(0, min(value, 1000))

    def close(self) -> None:
        with self._lock:
            self.connection.close()
