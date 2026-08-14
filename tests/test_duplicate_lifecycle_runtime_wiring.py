from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module(relative: str) -> ast.Module:
    return ast.parse(
        (ROOT / relative).read_text(encoding="utf-8"),
        filename=relative,
    )


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return node.attr if prefix is None else f"{prefix}.{node.attr}"
    return None


def test_duplicate_registry_exists() -> None:
    tree = _module("src/docsync/duplicates.py")

    classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}

    assert "DuplicateRegistry" in classes
    assert "DuplicateDecision" in classes


def test_duplicate_registry_contains_upsert_logic() -> None:
    source = (ROOT / "src/docsync/duplicates.py").read_text(encoding="utf-8")

    assert "ON CONFLICT(url)" in source
    assert "duplicate_urls" in source
    assert "content_records" in source
    assert "PRIMARY KEY" in source
    assert "UNIQUE" in source


def test_duplicate_registry_uses_sqlite_transaction() -> None:
    tree = _module("src/docsync/duplicates.py")

    transaction_contexts: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue

        for item in node.items:
            context_expr = item.context_expr

            if isinstance(context_expr, ast.Call):
                name = _call_name(context_expr.func)
            else:
                name = _call_name(context_expr)

            if name is not None:
                transaction_contexts.append(name)

    assert any(
        name.endswith(("_connect", "connect", "connection"))
        for name in transaction_contexts
    ), transaction_contexts


def test_duplicate_registry_hash_normalization() -> None:
    source = (ROOT / "src/docsync/duplicates.py").read_text(encoding="utf-8")

    assert ".strip().lower()" in source


def test_content_hash_is_sha256() -> None:
    source = (ROOT / "src/docsync/markdown.py").read_text(encoding="utf-8")

    assert "hashlib.sha256" in source


def test_incremental_hash_store_present() -> None:
    source = (ROOT / "src/docsync/incremental.py").read_text(encoding="utf-8")

    assert "load_content_hashes" in source
    assert "save_content_hashes" in source
    assert "content_hash(" in source


def test_atomic_replace_present() -> None:
    source = (ROOT / "src/docsync/incremental.py").read_text(encoding="utf-8")

    assert ".replace(" in source
    assert ".tmp" in source


def test_duplicate_statistics_present() -> None:
    """Duplicate statistics are exposed by canonical crawl metrics."""
    from docsync.metrics import CrawlStats

    stats = CrawlStats(mode="http")
    stats.duplicate_content += 1

    assert stats.duplicate_content == 1
    assert "duplicate=1" in stats.finished_summary()
    assert stats.as_dict()["duplicate_content"] == 1


def test_duplicate_registry_tests_exist() -> None:
    tree = _module("tests/test_behavioral_duplicates.py")

    names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}

    expected = {
        "test_duplicate_registry_records_unique_and_duplicate_content",
        "test_duplicate_registry_updates_duplicate_url_mapping",
        "test_duplicate_registry_rejects_empty_required_values",
        "test_duplicate_registry_persists_across_instances",
    }

    assert expected <= names
