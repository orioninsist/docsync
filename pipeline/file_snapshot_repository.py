from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias, cast


SnapshotRow: TypeAlias = tuple[object, object, object, object]

CREATE_FILE_SNAPSHOTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS file_snapshots (
    path TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    modified_ns INTEGER NOT NULL
)
"""

SELECT_FILE_SNAPSHOTS_SQL = """
SELECT
    path,
    sha256,
    size,
    modified_ns
FROM file_snapshots
ORDER BY path
"""

UPSERT_FILE_SNAPSHOT_SQL = """
INSERT INTO file_snapshots (
    path,
    sha256,
    size,
    modified_ns
)
VALUES (?, ?, ?, ?)
ON CONFLICT(path) DO UPDATE SET
    sha256 = excluded.sha256,
    size = excluded.size,
    modified_ns = excluded.modified_ns
"""

DELETE_FILE_SNAPSHOT_SQL = """
DELETE FROM file_snapshots
WHERE path = ?
"""


class FileSnapshotRepositoryError(RuntimeError):
    """Raised when file snapshot persistence fails."""


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    path: Path
    sha256: str
    size: int
    modified_ns: int


class FileSnapshotRepository:
    _connection: sqlite3.Connection

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def initialize(self) -> None:
        self._execute(CREATE_FILE_SNAPSHOTS_TABLE_SQL)

    def find_all(self) -> tuple[FileSnapshot, ...]:
        try:
            raw_rows = self._connection.execute(SELECT_FILE_SNAPSHOTS_SQL).fetchall()
        except sqlite3.Error as error:
            raise FileSnapshotRepositoryError(
                "File snapshots could not be loaded."
            ) from error

        rows = cast(list[SnapshotRow], raw_rows)
        return tuple(self._snapshot_from_row(row) for row in rows)

    def save(self, snapshot: FileSnapshot) -> None:
        parameters: tuple[object, ...] = (
            snapshot.path.as_posix(),
            snapshot.sha256,
            snapshot.size,
            snapshot.modified_ns,
        )
        self._execute(UPSERT_FILE_SNAPSHOT_SQL, parameters)

    def save_all(self, snapshots: Iterable[FileSnapshot]) -> None:
        parameters: list[tuple[object, ...]] = [
            (
                snapshot.path.as_posix(),
                snapshot.sha256,
                snapshot.size,
                snapshot.modified_ns,
            )
            for snapshot in snapshots
        ]

        if not parameters:
            return

        try:
            _ = self._connection.executemany(
                UPSERT_FILE_SNAPSHOT_SQL,
                parameters,
            )
        except sqlite3.Error as error:
            raise FileSnapshotRepositoryError(
                "File snapshots could not be saved."
            ) from error

    def delete(self, path: Path) -> None:
        self._execute(DELETE_FILE_SNAPSHOT_SQL, (path.as_posix(),))

    def _execute(
        self,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> None:
        try:
            _ = self._connection.execute(statement, parameters)
        except sqlite3.Error as error:
            raise FileSnapshotRepositoryError(
                "File snapshot persistence operation failed."
            ) from error

    @staticmethod
    def _snapshot_from_row(row: SnapshotRow) -> FileSnapshot:
        path_value, sha256_value, size_value, modified_ns_value = row

        if not isinstance(path_value, str):
            raise FileSnapshotRepositoryError("File snapshot path must be a string.")

        if not isinstance(sha256_value, str):
            raise FileSnapshotRepositoryError("File snapshot sha256 must be a string.")

        if isinstance(size_value, bool) or not isinstance(size_value, int):
            raise FileSnapshotRepositoryError("File snapshot size must be an integer.")

        if isinstance(modified_ns_value, bool) or not isinstance(
            modified_ns_value,
            int,
        ):
            raise FileSnapshotRepositoryError(
                "File snapshot modified_ns must be an integer."
            )

        return FileSnapshot(
            path=Path(path_value),
            sha256=sha256_value,
            size=size_value,
            modified_ns=modified_ns_value,
        )
