#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from crawler.shared.url_normalizer import normalize_url
from pipeline.time_utils import utc_now

GLOBAL_REGISTRY_DB = Path("state/global/global_url_registry.db")


@dataclass(frozen=True)
class OwnershipResult:
    allowed: bool
    status: str
    url_hash: str
    normalized_url: str
    owner_project: str | None
    message: str


def url_hash(normalized_url: str) -> str:
    return hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()


class GlobalUrlRegistry:
    def __init__(self, db_path: Path = GLOBAL_REGISTRY_DB) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.db_path))
        self.connection.row_factory = sqlite3.Row
        self._configure()
        self._create_schema()

    def _configure(self) -> None:
        self.connection.execute("PRAGMA journal_mode=WAL;")
        self.connection.execute("PRAGMA synchronous=NORMAL;")
        self.connection.execute("PRAGMA busy_timeout=30000;")
        self.connection.execute("PRAGMA foreign_keys=ON;")

    def _create_schema(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS url_ownership (
                url_hash TEXT PRIMARY KEY,
                normalized_url TEXT NOT NULL,
                owner_project TEXT NOT NULL,
                owner_project_dir TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );
            """
        )
        self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_url_ownership_owner_project
            ON url_ownership(owner_project);
            """
        )
        self.connection.commit()

    def claim_or_check(
        self,
        *,
        raw_url: str,
        owner_project: str,
        owner_project_dir: Path,
    ) -> OwnershipResult:
        if not raw_url.strip():
            raise ValueError("raw_url must not be empty.")

        if not owner_project.strip():
            raise ValueError("owner_project must not be empty.")

        normalized = normalize_url(raw_url)
        digest = url_hash(normalized)
        now = utc_now()

        existing = self.connection.execute(
            """
            SELECT *
            FROM url_ownership
            WHERE url_hash = ?
            LIMIT 1;
            """,
            (digest,),
        ).fetchone()

        if existing is None:
            self.connection.execute(
                """
                INSERT INTO url_ownership (
                    url_hash,
                    normalized_url,
                    owner_project,
                    owner_project_dir,
                    first_seen_at,
                    last_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (
                    digest,
                    normalized,
                    owner_project,
                    owner_project_dir.as_posix(),
                    now,
                    now,
                ),
            )
            self.connection.commit()

            return OwnershipResult(
                allowed=True,
                status="claimed",
                url_hash=digest,
                normalized_url=normalized,
                owner_project=owner_project,
                message=f"[CLAIMED] URL registered for project: {owner_project}",
            )

        existing_owner = str(existing["owner_project"])

        if existing_owner == owner_project:
            self.connection.execute(
                """
                UPDATE url_ownership
                SET last_seen_at = ?
                WHERE url_hash = ?;
                """,
                (now, digest),
            )
            self.connection.commit()

            return OwnershipResult(
                allowed=True,
                status="allowed_existing_owner",
                url_hash=digest,
                normalized_url=normalized,
                owner_project=existing_owner,
                message=f"[ALLOWED] URL already belongs to this project: {owner_project}",
            )

        return OwnershipResult(
            allowed=False,
            status="blocked_foreign_owner",
            url_hash=digest,
            normalized_url=normalized,
            owner_project=existing_owner,
            message=f"[BLOCKED] URL already belongs to project: {existing_owner}",
        )

    def close(self) -> None:
        self.connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Global URL ownership registry for docsync projects."
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("urls", nargs="+")
    args = parser.parse_args()

    registry = GlobalUrlRegistry()
    exit_code = 0

    try:
        for raw_url in args.urls:
            result = registry.claim_or_check(
                raw_url=raw_url,
                owner_project=args.project,
                owner_project_dir=Path(args.project_dir),
            )

            print(result.message)
            print(f"status={result.status}")
            print(f"url_hash={result.url_hash}")
            print(f"normalized_url={result.normalized_url}")

            if not result.allowed:
                exit_code = 10

    finally:
        registry.close()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
