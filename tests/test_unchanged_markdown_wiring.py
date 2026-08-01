from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import Mock

from bs4 import BeautifulSoup

from docsync.incremental import content_is_unchanged
from docsync.markdown import MarkdownExporter

ROOT = Path(__file__).resolve().parents[1]
CRAWLER_PATH = ROOT / "src" / "docsync" / "crawler.py"
MARKDOWN_PATH = ROOT / "src" / "docsync" / "markdown.py"


def _tree(path: Path) -> ast.Module:
    return ast.parse(
        path.read_text(encoding="utf-8"),
        filename=str(path),
    )


def _calls(path: Path, name: str) -> list[ast.Call]:
    result: list[ast.Call] = []

    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Call):
            continue

        if (isinstance(node.func, ast.Name) and node.func.id == name) or (
            isinstance(node.func, ast.Attribute) and node.func.attr == name
        ):
            result.append(node)

    return result


def _fixture_soup() -> BeautifulSoup:
    return BeautifulSoup(
        """
        <main>
          <h1>Stable Documentation</h1>
          <p>
            This stable documentation body contains enough meaningful content
            to verify preparation, hashing, and conditional persistence.
          </p>
        </main>
        """,
        "html.parser",
    )


def test_markdown_export_can_prepare_without_writing(
    tmp_path: Path,
) -> None:
    exporter = MarkdownExporter(tmp_path)

    document = exporter.export(
        url="https://example.com/docs",
        soup=_fixture_soup(),
        title="Stable Documentation",
        language="en",
        write=False,
    )

    assert not document.output_path.exists()
    assert document.markdown
    assert document.content_hash


def test_markdown_write_persists_prepared_document(
    tmp_path: Path,
) -> None:
    exporter = MarkdownExporter(tmp_path)

    document = exporter.export(
        url="https://example.com/docs",
        soup=_fixture_soup(),
        title="Stable Documentation",
        language="en",
        write=False,
    )

    exporter.write(document)

    assert document.output_path.is_file()
    assert document.markdown in document.output_path.read_text(
        encoding="utf-8",
    )


def test_prepared_unchanged_document_does_not_require_write(
    tmp_path: Path,
) -> None:
    exporter = MarkdownExporter(tmp_path)

    original = exporter.export(
        url="https://example.com/docs",
        soup=_fixture_soup(),
        title="Stable Documentation",
        language="en",
    )
    original_bytes = original.output_path.read_bytes()
    original_mtime = original.output_path.stat().st_mtime_ns

    prepared = exporter.export(
        url="https://example.com/docs",
        soup=_fixture_soup(),
        title="Stable Documentation",
        language="en",
        write=False,
    )

    state = {
        "https://example.com/docs": {
            "saved_at": "2026-08-01T00:00:00+00:00",
            "filename": original.output_path.name,
            "content_hash": original.content_hash,
        }
    }

    assert content_is_unchanged(
        url=prepared.url,
        digest=prepared.content_hash,
        url_state=state,
    )
    assert original.output_path.read_bytes() == original_bytes
    assert original.output_path.stat().st_mtime_ns == original_mtime


def test_export_write_false_does_not_call_atomic_write(
    tmp_path: Path,
) -> None:
    exporter = MarkdownExporter(tmp_path)
    atomic_write = Mock()
    exporter._atomic_write = atomic_write

    exporter.export(
        url="https://example.com/docs",
        soup=_fixture_soup(),
        title="Stable Documentation",
        language="en",
        write=False,
    )

    atomic_write.assert_not_called()


def test_export_default_still_writes(
    tmp_path: Path,
) -> None:
    exporter = MarkdownExporter(tmp_path)

    document = exporter.export(
        url="https://example.com/docs",
        soup=_fixture_soup(),
        title="Stable Documentation",
        language="en",
    )

    assert document.output_path.is_file()


def test_crawler_prepares_markdown_without_immediate_write() -> None:
    calls = _calls(CRAWLER_PATH, "export")

    matching = [
        call
        for call in calls
        if any(
            keyword.arg == "write"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is False
            for keyword in call.keywords
        )
    ]

    assert len(matching) == 1


def test_crawler_checks_content_before_writing() -> None:
    assert len(_calls(CRAWLER_PATH, "content_is_unchanged")) == 1
    assert len(_calls(CRAWLER_PATH, "write")) == 1


def test_markdown_exporter_declares_write_method() -> None:
    tree = _tree(MARKDOWN_PATH)

    exporter = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "MarkdownExporter"
    )

    methods = {
        node.name
        for node in exporter.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "export" in methods
    assert "write" in methods
