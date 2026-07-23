from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


CREATE_FLATTENED_FILES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS flattened_files (
    target_path TEXT PRIMARY KEY,
    original_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL
)
"""

UPSERT_FLATTENED_FILE_SQL = """
INSERT INTO flattened_files (
    target_path,
    original_path,
    sha256,
    size
)
VALUES (?, ?, ?, ?)
ON CONFLICT(target_path)
DO UPDATE SET
    original_path = excluded.original_path,
    sha256 = excluded.sha256,
    size = excluded.size
"""


class SqlExecutor(Protocol):
    def execute(
        self,
        sql: str,
        parameters: tuple[object, ...] = (),
        /,
    ) -> object: ...


@dataclass(frozen=True)
class FlattenedFileRecord:
    target_path: str
    original_path: str
    sha256: str
    size: int


class FlattenedFileRepository:
    _connection: SqlExecutor

    def __init__(self, connection: SqlExecutor) -> None:
        self._connection = connection

    def initialize(self) -> None:
        _ = self._connection.execute(CREATE_FLATTENED_FILES_TABLE_SQL)

    def save(self, record: FlattenedFileRecord) -> None:
        _ = self._connection.execute(
            UPSERT_FLATTENED_FILE_SQL,
            (
                record.target_path,
                record.original_path,
                record.sha256,
                record.size,
            ),
        )


def create_flattened_file_record(
    *,
    project_directory: Path,
    target_path: Path,
    source_path: Path,
    sha256: str,
    size: int,
) -> FlattenedFileRecord:
    return FlattenedFileRecord(
        target_path=relative_path(target_path, project_directory),
        original_path=relative_path(source_path, project_directory),
        sha256=sha256,
        size=size,
    )


def relative_path(path: Path, project_directory: Path) -> str:
    return path.relative_to(project_directory).as_posix()
