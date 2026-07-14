from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from pathlib import Path

from crawler.shared.url_normalizer import normalize_url
from crawler.time_utils import utc_now

READ_ONLY_MODE = 0o444
WRITE_MODE = 0o644

RAW_DIR_NAME = "_raw"
RAW_DB_NAME = ".raw_snapshot_state.db"


class MarkdownWriter:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = Path(output_dir)
        self.raw_root = self.output_dir / RAW_DIR_NAME
        self.db_path = self.output_dir / ".state" / RAW_DB_NAME

    def exists(self, *, url: str) -> bool:
        """
        Backward-compatible current Markdown existence check.

        This intentionally checks only the active/current Markdown file in the
        project root, not the immutable _raw snapshot history.
        """
        return self.current_markdown_exists_for_url(url=url)

    def current_markdown_exists_for_url(self, *, url: str) -> bool:
        normalized_url = self._normalize_url(url)
        url_hash = self._sha256_text(normalized_url)

        return self.current_markdown_exists(url_hash=url_hash)

    def current_markdown_exists(self, *, url_hash: str) -> bool:
        short_hash = url_hash[:12]

        if not self.output_dir.exists():
            return False

        for path in self.output_dir.glob(f"*__{short_hash}.md"):
            if path.is_file():
                return True

        return False

    def write(self, *, url: str, title: str, markdown: str) -> Path:
        normalized_url = self._normalize_url(url)
        url_hash = self._sha256_text(normalized_url)

        document = self._build_document(
            url=normalized_url,
            title=title,
            markdown=markdown,
        )

        content_hash = self._sha256_text(document)

        snapshot_path = self._write_raw_snapshot(
            url_hash=url_hash,
            normalized_url=normalized_url,
            content_hash=content_hash,
            title=title,
            document=document,
        )

        self._write_current_markdown(
            url_hash=url_hash,
            title=title,
            document=document,
        )

        return snapshot_path

    def _write_raw_snapshot(
        self,
        *,
        url_hash: str,
        normalized_url: str,
        content_hash: str,
        title: str,
        document: str,
    ) -> Path:
        snapshot_dir = self.raw_root / url_hash
        snapshot_path = snapshot_dir / f"{content_hash}.md"

        snapshot_dir.mkdir(parents=True, exist_ok=True)

        with self._connect() as conn:
            existing_same_content = conn.execute(
                """
                SELECT path
                FROM raw_snapshots
                WHERE url_hash = ?
                  AND content_hash = ?
                LIMIT 1;
                """,
                (
                    url_hash,
                    content_hash,
                ),
            ).fetchone()

            if existing_same_content is not None:
                existing_path = self.output_dir / str(existing_same_content["path"])
                self._lock(existing_path)
                return existing_path

            if snapshot_path.exists():
                self._lock(snapshot_path)
            else:
                snapshot_path.write_text(document, encoding="utf-8")
                self._lock(snapshot_path)

            relative_path = snapshot_path.relative_to(self.output_dir).as_posix()

            conn.execute(
                """
                INSERT INTO raw_snapshots (
                    url_hash,
                    normalized_url,
                    content_hash,
                    path,
                    title,
                    size,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    url_hash,
                    normalized_url,
                    content_hash,
                    relative_path,
                    self._clean_title(title),
                    snapshot_path.stat().st_size,
                    utc_now(),
                ),
            )

            conn.execute(
                """
                INSERT INTO raw_url_latest (
                    url_hash,
                    normalized_url,
                    latest_content_hash,
                    latest_path,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(url_hash)
                DO UPDATE SET
                    normalized_url = excluded.normalized_url,
                    latest_content_hash = excluded.latest_content_hash,
                    latest_path = excluded.latest_path,
                    updated_at = excluded.updated_at;
                """,
                (
                    url_hash,
                    normalized_url,
                    content_hash,
                    relative_path,
                    utc_now(),
                ),
            )

            conn.commit()

        return snapshot_path

    def _write_current_markdown(
        self,
        *,
        url_hash: str,
        title: str,
        document: str,
    ) -> Path:
        current_path = self._current_path(
            url_hash=url_hash,
            title=title,
        )

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._remove_stale_current_markdown(
            url_hash=url_hash,
            current_path=current_path,
        )

        self._unlock(current_path)
        current_path.write_text(document, encoding="utf-8")
        self._lock(current_path)

        return current_path

    def _remove_stale_current_markdown(
        self,
        *,
        url_hash: str,
        current_path: Path,
    ) -> None:
        short_hash = url_hash[:12]

        if not self.output_dir.exists():
            return

        for path in self.output_dir.glob(f"*__{short_hash}.md"):
            if not path.is_file():
                continue

            if path == current_path:
                continue

            self._unlock(path)

            try:
                path.unlink()
            except OSError:
                self._lock(path)

    def _current_path(self, *, url_hash: str, title: str) -> Path:
        filename = f"{self._safe_filename(title)}__{url_hash[:12]}.md"
        return self.output_dir / filename

    def _connect(self) -> sqlite3.Connection:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row

        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=FULL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=30000;")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url_hash TEXT NOT NULL,
                normalized_url TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                size INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(url_hash, content_hash)
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_url_latest (
                url_hash TEXT PRIMARY KEY,
                normalized_url TEXT NOT NULL,
                latest_content_hash TEXT NOT NULL,
                latest_path TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_raw_snapshots_url_hash
            ON raw_snapshots(url_hash);
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_raw_snapshots_content_hash
            ON raw_snapshots(content_hash);
            """
        )

        conn.commit()
        return conn

    def _build_document(self, *, url: str, title: str, markdown: str) -> str:
        safe_title = self._clean_title(title)
        clean_markdown = markdown.strip()

        if clean_markdown.startswith(f"# {safe_title}"):
            clean_markdown = clean_markdown[len(f"# {safe_title}") :].strip()

        return f"# {safe_title}\n\nOriginal URL: {url}\n\n---\n\n{clean_markdown}\n"

    def _normalize_url(self, url: str) -> str:
        return normalize_url(url)

    def _clean_title(self, title: str) -> str:
        title = " ".join(title.split())
        return title or "Untitled Page"

    def _safe_filename(self, title: str) -> str:
        value = self._clean_title(title).lower()
        value = re.sub(r"[^a-z0-9]+", "-", value)
        value = value.strip("-")
        return value or "document"

    def _sha256_text(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _lock(self, path: Path) -> None:
        if path.exists():
            os.chmod(path, READ_ONLY_MODE)

    def _unlock(self, path: Path) -> None:
        if path.exists():
            os.chmod(path, WRITE_MODE)
