#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, TypeAlias, cast

SqlParameter: TypeAlias = str | bytes | int | float | None
PositionalParameters: TypeAlias = Sequence[SqlParameter]
NamedParameters: TypeAlias = Mapping[str, SqlParameter]
SqlParameters: TypeAlias = PositionalParameters | NamedParameters
SqlParameterBatch: TypeAlias = Iterable[SqlParameters]

EMPTY_PARAMETERS: tuple[()] = ()


class SqliteExecutionError(RuntimeError):
    """Raised when a SQLite statement cannot be executed."""


def execute_statement(
    connection: sqlite3.Connection,
    statement: str,
    parameters: SqlParameters = EMPTY_PARAMETERS,
) -> sqlite3.Cursor:
    normalized_statement = _normalize_statement(statement)

    try:
        return connection.execute(normalized_statement, parameters)
    except sqlite3.Error as error:
        raise SqliteExecutionError(
            _build_error_message("execute", normalized_statement)
        ) from error


def execute_many(
    connection: sqlite3.Connection,
    statement: str,
    parameter_batch: SqlParameterBatch,
) -> sqlite3.Cursor:
    normalized_statement = _normalize_statement(statement)

    try:
        return connection.executemany(normalized_statement, parameter_batch)
    except sqlite3.Error as error:
        raise SqliteExecutionError(
            _build_error_message("execute many", normalized_statement)
        ) from error


def fetch_one(
    connection: sqlite3.Connection,
    statement: str,
    parameters: SqlParameters = EMPTY_PARAMETERS,
) -> sqlite3.Row | None:
    cursor = execute_statement(connection, statement, parameters)
    return cast(sqlite3.Row | None, cursor.fetchone())


def fetch_all(
    connection: sqlite3.Connection,
    statement: str,
    parameters: SqlParameters = EMPTY_PARAMETERS,
) -> list[sqlite3.Row]:
    cursor = execute_statement(connection, statement, parameters)
    return cursor.fetchall()


def fetch_scalar(
    connection: sqlite3.Connection,
    statement: str,
    parameters: SqlParameters = EMPTY_PARAMETERS,
) -> Any:
    row = fetch_one(connection, statement, parameters)

    if row is None:
        return None

    return row[0]


def _normalize_statement(statement: str) -> str:
    normalized_statement = statement.strip()

    if not normalized_statement:
        raise ValueError("SQL statement must not be empty.")

    return normalized_statement


def _build_error_message(operation: str, statement: str) -> str:
    statement_summary = " ".join(statement.split())
    return f"Failed to {operation} SQLite statement: {statement_summary}"
