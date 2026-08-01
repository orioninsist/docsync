from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from docsync.duplicates import DuplicateRegistry


def test_duplicate_registry_records_unique_and_duplicate_content(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "duplicates.sqlite3"
    registry = DuplicateRegistry(database_path)

    canonical_output = tmp_path / "canonical.md"
    duplicate_output = tmp_path / "duplicate.md"

    first = registry.register(
        content_hash="ABC123",
        url="https://example.com/canonical",
        output_path=canonical_output,
        title="Canonical",
    )

    second = registry.register(
        content_hash="abc123",
        url="https://example.com/duplicate",
        output_path=duplicate_output,
        title="Duplicate",
    )

    assert first.is_duplicate is False
    assert first.canonical_url == "https://example.com/canonical"
    assert first.canonical_path == str(canonical_output.resolve())
    assert first.content_hash == "abc123"

    assert second.is_duplicate is True
    assert second.canonical_url == "https://example.com/canonical"
    assert second.canonical_path == str(canonical_output.resolve())
    assert second.content_hash == "abc123"

    assert registry.counts() == (1, 1)


def test_duplicate_registry_updates_duplicate_url_mapping(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "duplicates.sqlite3"
    registry = DuplicateRegistry(database_path)

    registry.register(
        content_hash="first-hash",
        url="https://example.com/first",
        output_path=tmp_path / "first.md",
        title="First",
    )
    registry.register(
        content_hash="second-hash",
        url="https://example.com/second",
        output_path=tmp_path / "second.md",
        title="Second",
    )

    duplicate_url = "https://example.com/shared"

    registry.register(
        content_hash="first-hash",
        url=duplicate_url,
        output_path=tmp_path / "shared-one.md",
        title="Shared One",
    )
    registry.register(
        content_hash="second-hash",
        url=duplicate_url,
        output_path=tmp_path / "shared-two.md",
        title="Shared Two",
    )

    connection = sqlite3.connect(database_path)
    try:
        row = connection.execute(
            """
            SELECT content_hash, canonical_url
            FROM duplicate_urls
            WHERE url = ?
            """,
            (duplicate_url,),
        ).fetchone()

    finally:
        connection.close()
    assert row == (
        "second-hash",
        "https://example.com/second",
    )
    assert registry.counts() == (2, 1)


@pytest.mark.parametrize(
    ("content_hash", "url"),
    [
        ("", "https://example.com/page"),
        ("   ", "https://example.com/page"),
        ("hash", ""),
        ("hash", "   "),
    ],
)
def test_duplicate_registry_rejects_empty_required_values(
    tmp_path: Path,
    content_hash: str,
    url: str,
) -> None:
    registry = DuplicateRegistry(
        tmp_path / "duplicates.sqlite3",
    )

    with pytest.raises(ValueError):
        registry.register(
            content_hash=content_hash,
            url=url,
            output_path=tmp_path / "page.md",
            title="Page",
        )


def test_duplicate_registry_persists_across_instances(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "duplicates.sqlite3"

    first_registry = DuplicateRegistry(database_path)
    first_registry.register(
        content_hash="persistent-hash",
        url="https://example.com/original",
        output_path=tmp_path / "original.md",
        title="Original",
    )

    second_registry = DuplicateRegistry(database_path)
    decision = second_registry.register(
        content_hash="persistent-hash",
        url="https://example.com/later",
        output_path=tmp_path / "later.md",
        title="Later",
    )

    assert decision.is_duplicate is True
    assert decision.canonical_url == "https://example.com/original"
    assert second_registry.counts() == (1, 1)
