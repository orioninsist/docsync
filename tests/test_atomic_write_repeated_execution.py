from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import docsync.incremental as incremental
from docsync.markdown import MarkdownExporter


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_url_state_repeated_atomic_replacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "state" / "url_state.json"
    target.parent.mkdir(parents=True)
    temporary = target.with_suffix(".tmp")

    monkeypatch.setattr(incremental, "URL_STATE_FILE", target)

    first = {
        "https://example.com/first": {
            "content_hash": "first-hash",
            "saved_at": "2026-07-31T10:00:00+00:00",
        }
    }
    second = {
        "https://example.com/second": {
            "content_hash": "second-hash",
            "saved_at": "2026-07-31T11:00:00+00:00",
        }
    }

    incremental.save_url_state(first)

    assert target.is_file()
    assert not temporary.exists()
    assert _read_json(target) == first

    incremental.save_url_state(second)

    assert target.is_file()
    assert not temporary.exists()
    assert _read_json(target) == second


def test_url_state_replace_failure_preserves_existing_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "state" / "url_state.json"
    target.parent.mkdir(parents=True)
    temporary = target.with_suffix(".tmp")

    monkeypatch.setattr(incremental, "URL_STATE_FILE", target)

    original = {
        "https://example.com/stable": {
            "content_hash": "stable-hash",
            "saved_at": "2026-07-31T10:00:00+00:00",
        }
    }
    replacement = {
        "https://example.com/new": {
            "content_hash": "new-hash",
            "saved_at": "2026-07-31T11:00:00+00:00",
        }
    }

    incremental.save_url_state(original)
    original_bytes = target.read_bytes()
    original_replace = Path.replace

    def failing_replace(self: Path, destination: Path) -> Path:
        if self == temporary and destination == target:
            raise OSError("simulated atomic replacement failure")
        return original_replace(self, destination)

    monkeypatch.setattr(Path, "replace", failing_replace)

    with pytest.raises(
        OSError,
        match="simulated atomic replacement failure",
    ):
        incremental.save_url_state(replacement)

    assert target.read_bytes() == original_bytes
    assert temporary.is_file()
    assert _read_json(temporary) == replacement


def test_markdown_atomic_write_replaces_existing_file_repeatedly(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "document.md"
    temporary = output_path.with_suffix(".md.tmp")

    MarkdownExporter._atomic_write(
        output_path=output_path,
        content="first",
    )

    assert output_path.read_text(encoding="utf-8") == "first"
    assert not temporary.exists()

    MarkdownExporter._atomic_write(
        output_path=output_path,
        content="second",
    )

    assert output_path.read_text(encoding="utf-8") == "second"
    assert not temporary.exists()

    MarkdownExporter._atomic_write(
        output_path=output_path,
        content="third",
    )

    assert output_path.read_text(encoding="utf-8") == "third"
    assert not temporary.exists()


