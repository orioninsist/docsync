from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

import docsync.incremental as incremental

ROOT = Path(__file__).resolve().parents[1]
CRAWLER_PATH = ROOT / "src" / "docsync" / "crawler.py"


def _crawler_tree() -> ast.Module:
    return ast.parse(
        CRAWLER_PATH.read_text(encoding="utf-8"),
        filename=str(CRAWLER_PATH),
    )


def _call_names() -> list[str]:
    names: list[str] = []

    for node in ast.walk(_crawler_tree()):
        if not isinstance(node, ast.Call):
            continue

        if isinstance(node.func, ast.Name):
            names.append(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.append(node.func.attr)

    return names


def test_crawler_loads_both_incremental_state_stores() -> None:
    calls = _call_names()

    assert calls.count("load_content_hashes") == 1
    assert calls.count("load_url_state") == 1


def test_crawler_records_successful_exports() -> None:
    calls = _call_names()

    assert calls.count("record_incremental_success") == 1


def test_crawler_persists_both_state_stores_once_in_finalizer() -> None:
    calls = _call_names()

    assert calls.count("save_content_hashes") == 1
    assert calls.count("save_url_state") == 1
    assert calls.count("write_crawl_report") == 1
    assert calls.count("finalize_crawl") == 2


def test_state_loaders_use_explicit_state_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "configured-state"
    state_dir.mkdir(parents=True)

    content_hash_payload = {
        "abc123": "https://example.com/docs",
    }
    url_state_payload = {
        "https://example.com/docs": {
            "saved_at": "2026-08-01T00:00:00+00:00",
            "filename": "docs.md",
            "content_hash": "abc123",
        }
    }

    (state_dir / "content_hashes.json").write_text(
        json.dumps(content_hash_payload),
        encoding="utf-8",
    )
    (state_dir / "url_state.json").write_text(
        json.dumps(url_state_payload),
        encoding="utf-8",
    )

    unreachable_default_hashes = tmp_path / "default-content-hashes.json"
    unreachable_default_url_state = tmp_path / "default-url-state.json"

    monkeypatch.setattr(
        incremental,
        "CONTENT_HASH_FILE",
        unreachable_default_hashes,
    )
    monkeypatch.setattr(
        incremental,
        "URL_STATE_FILE",
        unreachable_default_url_state,
    )

    assert incremental.load_content_hashes(state_dir) == content_hash_payload
    assert incremental.load_url_state(state_dir) == url_state_payload


def test_state_savers_use_explicit_state_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "configured-state"

    unreachable_default_hashes = tmp_path / "default-content-hashes.json"
    unreachable_default_url_state = tmp_path / "default-url-state.json"

    monkeypatch.setattr(
        incremental,
        "CONTENT_HASH_FILE",
        unreachable_default_hashes,
    )
    monkeypatch.setattr(
        incremental,
        "URL_STATE_FILE",
        unreachable_default_url_state,
    )

    content_hash_payload = {
        "abc123": "https://example.com/docs",
    }
    url_state_payload = {
        "https://example.com/docs": {
            "saved_at": "2026-08-01T00:00:00+00:00",
            "filename": "docs.md",
            "content_hash": "abc123",
        }
    }

    incremental.save_content_hashes(
        content_hash_payload,
        state_dir,
    )
    incremental.save_url_state(
        url_state_payload,
        state_dir,
    )

    assert (
        json.loads((state_dir / "content_hashes.json").read_text(encoding="utf-8"))
        == content_hash_payload
    )
    assert (
        json.loads((state_dir / "url_state.json").read_text(encoding="utf-8"))
        == url_state_payload
    )

    assert not unreachable_default_hashes.exists()
    assert not unreachable_default_url_state.exists()


def test_recorded_success_round_trips_through_configured_state(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    output_path = tmp_path / "markdown" / "docs.md"
    output_path.parent.mkdir(parents=True)
    output_path.write_text("# Docs\n", encoding="utf-8")

    hashes: dict[str, str] = {}
    url_state: dict[str, dict[str, str]] = {}

    incremental.record_incremental_success(
        url="https://example.com/docs/",
        output_path=output_path,
        digest="ABC123",
        hashes=hashes,
        url_state=url_state,
    )

    incremental.save_content_hashes(hashes, state_dir)
    incremental.save_url_state(url_state, state_dir)

    assert incremental.load_content_hashes(state_dir) == {
        "abc123": "https://example.com/docs",
    }

    loaded_state = incremental.load_url_state(state_dir)

    assert loaded_state["https://example.com/docs"]["filename"] == "docs.md"
    assert loaded_state["https://example.com/docs"]["content_hash"] == "abc123"
    assert loaded_state["https://example.com/docs"]["saved_at"]
