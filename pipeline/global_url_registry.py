#!/usr/bin/env python3
"""Provide persistent, project-level ownership tracking for normalized URLs."""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import SplitResult, urlsplit, urlunsplit

from pipeline.time_utils import utc_now

GLOBAL_REGISTRY_DB = Path("state/global/global_url_registry.db")
_SUPPORTED_SCHEMES = frozenset({"http", "https"})


@dataclass(frozen=True)
class OwnershipResult:
    """Describe the result of claiming or checking URL ownership."""

    allowed: bool
    status: str
    url_hash: str
    normalized_url: str
    owner_project: str | None
    message: str


def normalize_url(raw_url: str) -> str:
    """Return a deterministic HTTP or HTTPS URL representation."""

    candidate = raw_url.strip()
    if not candidate:
        raise ValueError("raw_url must not be empty.")

    parsed = urlsplit(candidate)
    scheme = parsed.scheme.lower()

    if scheme not in _SUPPORTED_SCHEMES:
        raise ValueError("URL scheme must be http or https.")

    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs containing credentials are not supported.")

    hostname = parsed.hostname
    if hostname is None:
        raise ValueError("URL must contain a hostname.")

    normalized_host = hostname.rstrip(".").lower()
    if not normalized_host:
        raise ValueError("URL hostname must not be empty.")

    normalized_netloc = _normalized_netloc(
        scheme=scheme,
        hostname=normalized_host,
        port=_validated_port(parsed),
    )
    normalized_path = parsed.path or "/"

    normalized = SplitResult(
        scheme=scheme,
        netloc=normalized_netloc,
        path=normalized_path,
        query=parsed.query,
        fragment="",
    )
    return urlunsplit(normalized)


def _validated_port(parsed: SplitResult) -> int | None:
    """Return the parsed port while converting invalid ports to ValueError."""

    try:
        return parsed.port
    except ValueError as exc:
        raise ValueError("URL contains an invalid port.") from exc


def _normalized_netloc(
    *,
    scheme: str,
    hostname: str,
    port: int | None,
) -> str:
    """Build a normalized network location without default ports."""

    host = f"[{hostname}]" if ":" in hostname else hostname

    if port is None:
        return host

    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        return host

    return f"{host}:{port}"


def url_hash(normalized_url: str) -> str:
    """Return the SHA-256 digest of a normalized URL."""

    return hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()


class GlobalUrlRegistry:
    """Persist and enforce exclusive URL ownership between projects."""

    def __init__(self, db_path: Path = GLOBAL_REGISTRY_DB) -> None:
        """Open the registry database and ensure its schema exists."""

        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.db_path))
        self.connection.row_factory = sqlite3.Row
        self._configure()
        self._create_schema()

    def _configure(self) -> None:
        """Configure SQLite for safe concurrent registry access."""

        self.connection.execute("PRAGMA journal_mode=WAL;")
        self.connection.execute("PRAGMA synchronous=NORMAL;")
        self.connection.execute("PRAGMA busy_timeout=30000;")
        self.connection.execute("PRAGMA foreign_keys=ON;")

    def _create_schema(self) -> None:
        """Create the URL ownership table and supporting index."""

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
        """Claim a URL or report its existing project ownership."""

        normalized_project = owner_project.strip()
        if not normalized_project:
            raise ValueError("owner_project must not be empty.")

        normalized = normalize_url(raw_url)
        digest = url_hash(normalized)
        now = utc_now()

        existing = self.connection.execute(
            """
            SELECT owner_project
            FROM url_ownership
            WHERE url_hash = ?
            LIMIT 1;
            """,
            (digest,),
        ).fetchone()

        if existing is None:
            return self._claim_new_url(
                digest=digest,
                normalized_url=normalized,
                owner_project=normalized_project,
                owner_project_dir=owner_project_dir,
                timestamp=now,
            )

        existing_owner = str(existing["owner_project"])
        if existing_owner == normalized_project:
            return self._allow_existing_owner(
                digest=digest,
                normalized_url=normalized,
                owner_project=existing_owner,
                timestamp=now,
            )

        return OwnershipResult(
            allowed=False,
            status="blocked_foreign_owner",
            url_hash=digest,
            normalized_url=normalized,
            owner_project=existing_owner,
            message=(f"[BLOCKED] URL already belongs to project: {existing_owner}"),
        )

    def _claim_new_url(
        self,
        *,
        digest: str,
        normalized_url: str,
        owner_project: str,
        owner_project_dir: Path,
        timestamp: str,
    ) -> OwnershipResult:
        """Persist and return a newly claimed URL."""

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
                normalized_url,
                owner_project,
                owner_project_dir.resolve().as_posix(),
                timestamp,
                timestamp,
            ),
        )
        self.connection.commit()

        return OwnershipResult(
            allowed=True,
            status="claimed",
            url_hash=digest,
            normalized_url=normalized_url,
            owner_project=owner_project,
            message=f"[CLAIMED] URL registered for project: {owner_project}",
        )

    def _allow_existing_owner(
        self,
        *,
        digest: str,
        normalized_url: str,
        owner_project: str,
        timestamp: str,
    ) -> OwnershipResult:
        """Refresh and return ownership held by the requesting project."""

        self.connection.execute(
            """
            UPDATE url_ownership
            SET last_seen_at = ?
            WHERE url_hash = ?;
            """,
            (timestamp, digest),
        )
        self.connection.commit()

        return OwnershipResult(
            allowed=True,
            status="allowed_existing_owner",
            url_hash=digest,
            normalized_url=normalized_url,
            owner_project=owner_project,
            message=(f"[ALLOWED] URL already belongs to this project: {owner_project}"),
        )

    def close(self) -> None:
        """Close the underlying SQLite connection."""

        self.connection.close()


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""

    parser = argparse.ArgumentParser(
        description="Global URL ownership registry for docsync projects."
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("urls", nargs="+")
    return parser


def main() -> int:
    """Run the global URL registry command-line interface."""

    args = _build_parser().parse_args()
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
