from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import cast

from crawler.config import CrawlerConfig


def has_markdown_output(output_dir: Path) -> bool:
    if not output_dir.is_dir():
        return False

    return any(
        path.is_file()
        for path in output_dir.rglob("*.md")
        if "_raw" not in path.parts and "_archive" not in path.parts
    )


def crawl_db_is_complete(db_path: Path) -> bool:
    if not db_path.is_file():
        return False

    try:
        with sqlite3.connect(str(db_path)) as connection:
            table = cast(
                tuple[str] | None,
                connection.execute(
                    (
                        "SELECT name FROM sqlite_master "
                        "WHERE type='table' AND name='url_queue';"
                    )
                ).fetchone(),
            )

            if table is None:
                return False

            row = cast(
                tuple[int | None, int | None, int | None, int | None] | None,
                connection.execute(
                    """
                    SELECT
                        SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END),
                        SUM(CASE WHEN status='processing' THEN 1 ELSE 0 END),
                        SUM(CASE WHEN status='error' THEN 1 ELSE 0 END),
                        SUM(CASE WHEN status='done' THEN 1 ELSE 0 END)
                    FROM url_queue;
                    """
                ).fetchone(),
            )

            if row is None:
                return False

            pending, processing, errors, done = row

            return (
                (pending or 0) == 0
                and (processing or 0) == 0
                and (errors or 0) == 0
                and (done or 0) > 0
            )

    except sqlite3.Error:
        return False


def already_completed(config: CrawlerConfig) -> bool:
    return crawl_db_is_complete(config.db_path) and has_markdown_output(
        config.output_dir
    )
