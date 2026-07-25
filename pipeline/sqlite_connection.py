"""Central SQLite connection and transaction boundaries for pipeline modules."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

DEFAULT_BUSY_TIMEOUT_MILLISECONDS = 30_000


class SQLiteConnectionError(RuntimeError):
    """Raised when a SQLite connection cannot be opened or configured."""


class SQLiteTransactionError(RuntimeError):
    """Raised when a SQLite transaction cannot be completed."""


def connect_sqlite(
    database_path: Path,
    *,
    busy_timeout_milliseconds: int = DEFAULT_BUSY_TIMEOUT_MILLISECONDS,
) -> sqlite3.Connection:
    """Open and configure a SQLite connection."""

    resolved_database_path = _prepare_database_path(database_path)
    validated_busy_timeout = _validate_busy_timeout(
        busy_timeout_milliseconds,
    )

    try:
        connection = sqlite3.connect(resolved_database_path)
    except sqlite3.Error as error:
        raise SQLiteConnectionError(
            f"failed to open SQLite database: {resolved_database_path}",
        ) from error

    try:
        _configure_connection(
            connection,
            busy_timeout_milliseconds=validated_busy_timeout,
        )
    except sqlite3.Error as error:
        connection.close()
        raise SQLiteConnectionError(
            f"failed to configure SQLite database: {resolved_database_path}",
        ) from error

    return connection


@contextmanager
def sqlite_connection(
    database_path: Path,
    *,
    busy_timeout_milliseconds: int = DEFAULT_BUSY_TIMEOUT_MILLISECONDS,
) -> Generator[sqlite3.Connection]:
    """Provide a configured SQLite connection with deterministic closing."""

    connection = connect_sqlite(
        database_path,
        busy_timeout_milliseconds=busy_timeout_milliseconds,
    )

    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def sqlite_transaction(
    connection: sqlite3.Connection,
) -> Generator[sqlite3.Connection]:
    """Commit successful work and roll back failed work."""

    try:
        yield connection
        connection.commit()
    except sqlite3.Error as error:
        _rollback_transaction(connection)
        raise SQLiteTransactionError(
            "SQLite transaction failed",
        ) from error
    except Exception:
        _rollback_transaction(connection)
        raise


def _prepare_database_path(database_path: Path) -> Path:
    resolved_database_path = database_path.expanduser().resolve(
        strict=False,
    )

    try:
        resolved_database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
    except OSError as error:
        message = (
            "failed to create SQLite database directory: "
            f"{resolved_database_path.parent}"
        )
        raise SQLiteConnectionError(message) from error

    if not resolved_database_path.parent.is_dir():
        message = (
            "SQLite database parent is not a directory: "
            f"{resolved_database_path.parent}"
        )
        raise SQLiteConnectionError(message)

    if resolved_database_path.exists() and not resolved_database_path.is_file():
        raise SQLiteConnectionError(
            f"SQLite database path is not a file: {resolved_database_path}",
        )

    return resolved_database_path


def _validate_busy_timeout(
    busy_timeout_milliseconds: int,
) -> int:
    if isinstance(busy_timeout_milliseconds, bool):
        raise TypeError(
            "busy_timeout_milliseconds must be an integer",
        )

    if busy_timeout_milliseconds < 0:
        raise ValueError(
            "busy_timeout_milliseconds must not be negative",
        )

    return busy_timeout_milliseconds


def _configure_connection(
    connection: sqlite3.Connection,
    *,
    busy_timeout_milliseconds: int,
) -> None:
    connection.row_factory = sqlite3.Row
    _ = connection.execute("PRAGMA journal_mode=WAL")
    _ = connection.execute("PRAGMA synchronous=FULL")
    _ = connection.execute("PRAGMA foreign_keys=ON")
    _ = connection.execute(
        f"PRAGMA busy_timeout={busy_timeout_milliseconds}",
    )


def _rollback_transaction(
    connection: sqlite3.Connection,
) -> None:
    try:
        connection.rollback()
    except sqlite3.Error as rollback_error:
        raise SQLiteTransactionError(
            "SQLite transaction and rollback both failed",
        ) from rollback_error


__all__ = [
    "DEFAULT_BUSY_TIMEOUT_MILLISECONDS",
    "SQLiteConnectionError",
    "SQLiteTransactionError",
    "connect_sqlite",
    "sqlite_connection",
    "sqlite_transaction",
]
