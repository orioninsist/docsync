from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

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
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def initialize(self) -> None:
        self._execute(CREATE_FILE_SNAPSHOTS_TABLE_SQL)

    def find_all(self) -> tuple[FileSnapshot, ...]:
        try:
            rows = self._connection.execute(SELECT_FILE_SNAPSHOTS_SQL).fetchall()
        except sqlite3.Error as error:
            raise FileSnapshotRepositoryError(
                "File snapshots could not be loaded."
            ) from error

        return tuple(self._snapshot_from_row(row) for row in rows)

    def save(self, snapshot: FileSnapshot) -> None:
        parameters = (
            snapshot.path.as_posix(),
            snapshot.sha256,
            snapshot.size,
            snapshot.modified_ns,
        )
        self._execute(UPSERT_FILE_SNAPSHOT_SQL, parameters)

    def save_all(self, snapshots: Iterable[FileSnapshot]) -> None:
        parameters = [
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
            self._connection.executemany(
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
            self._connection.execute(statement, parameters)
        except sqlite3.Error as error:
            raise FileSnapshotRepositoryError(
                "File snapshot persistence operation failed."
            ) from error

    @staticmethod
    def _snapshot_from_row(row: sqlite3.Row) -> FileSnapshot:
        return FileSnapshot(
            path=Path(row["path"]),
            sha256=row["sha256"],
            size=row["size"],
            modified_ns=row["modified_ns"],
        )
