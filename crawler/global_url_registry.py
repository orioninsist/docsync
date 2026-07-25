"""Persist and enforce project-level URL ownership."""

from __future__ import annotations

import hashlib
import random
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar, cast
from urllib.parse import SplitResult, urlsplit, urlunsplit

from crawler.time_utils import utc_now

GLOBAL_REGISTRY_DB = Path("state/global/global_url_registry.db")
_SUPPORTED_SCHEMES = frozenset({"http", "https"})
_SQLITE_BUSY_TIMEOUT_SECONDS = 30.0
_SQLITE_MAX_WRITE_ATTEMPTS = 10
_SQLITE_INITIAL_RETRY_DELAY_SECONDS = 0.05
_SQLITE_MAX_RETRY_DELAY_SECONDS = 1.5

_ResultT = TypeVar("_ResultT")


@dataclass(frozen=True, slots=True)
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

    normalized_hostname = hostname.rstrip(".").lower()

    if not normalized_hostname:
        raise ValueError("URL hostname must not be empty.")

    normalized = SplitResult(
        scheme=scheme,
        netloc=_normalized_netloc(
            scheme=scheme,
            hostname=normalized_hostname,
            port=_validated_port(parsed),
        ),
        path=parsed.path or "/",
        query=parsed.query,
        fragment="",
    )

    return urlunsplit(normalized)


def _validated_port(parsed: SplitResult) -> int | None:
    """Return the parsed port and normalize invalid-port errors."""

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

    is_default_http_port = scheme == "http" and port == 80
    is_default_https_port = scheme == "https" and port == 443

    if is_default_http_port or is_default_https_port:
        return host

    return f"{host}:{port}"


def url_hash(normalized_url: str) -> str:
    """Return the SHA-256 digest of a normalized URL."""

    return hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()


def _is_locked_error(error: sqlite3.OperationalError) -> bool:
    """Return whether an SQLite error represents lock contention."""

    message = str(error).lower()

    return (
        "database is locked" in message
        or "database table is locked" in message
        or "database schema is locked" in message
        or "database is busy" in message
    )


class GlobalUrlRegistry:
    """Persist and enforce exclusive URL ownership between projects."""

    def __init__(self, db_path: Path = GLOBAL_REGISTRY_DB) -> None:
        """Open the registry database and ensure its schema exists."""

        self._db_path: Path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self._connection: sqlite3.Connection = sqlite3.connect(
            str(self._db_path),
            timeout=_SQLITE_BUSY_TIMEOUT_SECONDS,
            isolation_level=None,
        )
        self._connection.row_factory = sqlite3.Row

        self._configure_connection()
        self._run_write_with_retry(self._create_schema)

    @property
    def db_path(self) -> Path:
        """Return the registry database path."""

        return self._db_path

    def _configure_connection(self) -> None:
        """Configure SQLite for concurrent registry access."""

        _ = self._connection.execute("PRAGMA journal_mode=WAL;")
        _ = self._connection.execute("PRAGMA synchronous=NORMAL;")
        _ = self._connection.execute("PRAGMA busy_timeout=30000;")
        _ = self._connection.execute("PRAGMA foreign_keys=ON;")
        _ = self._connection.execute("PRAGMA temp_store=MEMORY;")

    def _create_schema(self) -> None:
        """Create the URL ownership table and its lookup index."""

        _ = self._connection.execute(
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
        _ = self._connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_url_ownership_owner_project
            ON url_ownership(owner_project);
            """
        )

    def _rollback_quietly(self) -> None:
        """Rollback without masking the original database error."""

        try:
            _ = self._connection.execute("ROLLBACK;")
        except sqlite3.Error:
            pass

    def _run_write_with_retry(
        self,
        operation: Callable[[], _ResultT],
    ) -> _ResultT:
        """Run one short atomic write with bounded retry and jitter."""

        delay = _SQLITE_INITIAL_RETRY_DELAY_SECONDS
        last_error: sqlite3.OperationalError | None = None

        for attempt in range(1, _SQLITE_MAX_WRITE_ATTEMPTS + 1):
            try:
                _ = self._connection.execute("BEGIN IMMEDIATE;")
                result = operation()
                _ = self._connection.execute("COMMIT;")
                return result

            except sqlite3.OperationalError as error:
                self._rollback_quietly()

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
                self._rollback_quietly()
                raise

        if last_error is None:
            raise RuntimeError("SQLite retry loop ended without an operational error.")

        raise last_error

    def claim_or_check(
        self,
        *,
        raw_url: str,
        owner_project: str,
        owner_project_dir: Path,
    ) -> OwnershipResult:
        """Atomically claim a URL or report its existing ownership."""

        normalized_project = owner_project.strip()

        if not normalized_project:
            raise ValueError("owner_project must not be empty.")

        normalized_url = normalize_url(raw_url)
        digest = url_hash(normalized_url)
        timestamp = utc_now()
        resolved_project_dir = owner_project_dir.resolve().as_posix()

        def claim_transaction() -> OwnershipResult:
            existing_owner = self._find_owner(digest)

            if existing_owner is None:
                _ = self._connection.execute(
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
                        normalized_project,
                        resolved_project_dir,
                        timestamp,
                        timestamp,
                    ),
                )

                return OwnershipResult(
                    allowed=True,
                    status="claimed",
                    url_hash=digest,
                    normalized_url=normalized_url,
                    owner_project=normalized_project,
                    message=(
                        f"[CLAIMED] URL registered for project: {normalized_project}"
                    ),
                )

            if existing_owner == normalized_project:
                _ = self._connection.execute(
                    """
                    UPDATE url_ownership
                    SET last_seen_at = ?
                    WHERE url_hash = ?;
                    """,
                    (
                        timestamp,
                        digest,
                    ),
                )

                return OwnershipResult(
                    allowed=True,
                    status="allowed_existing_owner",
                    url_hash=digest,
                    normalized_url=normalized_url,
                    owner_project=existing_owner,
                    message=(
                        "[ALLOWED] URL already belongs to this project: "
                        f"{existing_owner}"
                    ),
                )

            return OwnershipResult(
                allowed=False,
                status="blocked_foreign_owner",
                url_hash=digest,
                normalized_url=normalized_url,
                owner_project=existing_owner,
                message=(f"[BLOCKED] URL already belongs to project: {existing_owner}"),
            )

        return self._run_write_with_retry(claim_transaction)

    def _find_owner(self, digest: str) -> str | None:
        """Return the owning project for a URL hash when registered."""

        row = cast(
            sqlite3.Row | None,
            self._connection.execute(
                """
                SELECT owner_project
                FROM url_ownership
                WHERE url_hash = ?
                LIMIT 1;
                """,
                (digest,),
            ).fetchone(),
        )

        if row is None:
            return None

        return cast(str, row["owner_project"])

    def close(self) -> None:
        """Close the underlying SQLite connection."""

        self._connection.close()

    def __enter__(self) -> GlobalUrlRegistry:
        """Return this registry as a context manager."""

        return self

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        """Close the registry when leaving a context manager."""

        self.close()
