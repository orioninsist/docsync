from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from docsync.markdown import MarkdownExporter


def test_markdown_exporter_exports_main_content_atomically(
    tmp_path: Path,
) -> None:
    exporter = MarkdownExporter(tmp_path)

    soup = BeautifulSoup(
        """
        <html>
          <head>
            <title>Ignored Browser Title</title>
            <style>.hidden { display: none; }</style>
          </head>
          <body>
            <nav>Navigation must not become the document body.</nav>
            <main>
              <h1>API Guide</h1>
              <p>
                This documentation paragraph intentionally contains enough
                meaningful text for the main-content selector to accept it.
                It describes authentication, requests, responses, pagination,
                errors, retries, limits, and reliable integration practices.
              </p>
              <script>alert("removed")</script>
            </main>
          </body>
        </html>
        """,
        "html.parser",
    )

    document = exporter.export(
        url="https://example.com/docs/api",
        soup=soup,
        title="API Guide",
        language="en",
    )

    assert document.url == "https://example.com/docs/api"
    assert document.title == "API Guide"
    assert document.language == "en"
    assert "# API Guide" in document.markdown
    assert "alert" not in document.markdown
    assert "Navigation must not" not in document.markdown
    assert document.output_path.exists()
    assert document.output_path.parent == (tmp_path / "example.com" / "docs").resolve()
    assert document.output_path.name.startswith("api-")
    assert document.output_path.suffix == ".md"
    assert not document.output_path.with_suffix(".md.tmp").exists()
    assert (
        document.content_hash
        == hashlib.sha256(document.markdown.encode("utf-8")).hexdigest()
    )

    written = document.output_path.read_text(encoding="utf-8")
    assert 'url: "https://example.com/docs/api"' in written
    assert "https://example.com/docs/api" in written
    assert document.content_hash in written
    assert document.markdown in written


def test_markdown_exporter_uses_markdown_heading_as_title(
    tmp_path: Path,
) -> None:
    exporter = MarkdownExporter(tmp_path)

    soup = BeautifulSoup(
        """
        <main>
          <h1>Derived Heading</h1>
          <p>
            This paragraph provides sufficient meaningful content for
            selection and verifies that an empty supplied title falls back
            to the first Markdown heading generated from the document.
          </p>
        </main>
        """,
        "html.parser",
    )

    document = exporter.export(
        url="https://example.com/derived",
        soup=soup,
        title="",
        language="en",
    )

    assert document.title == "Derived Heading"


def test_markdown_exporter_rejects_empty_meaningful_content(
    tmp_path: Path,
) -> None:
    exporter = MarkdownExporter(tmp_path)

    soup = BeautifulSoup(
        "<html><body><main><script>only script</script></main></body></html>",
        "html.parser",
    )

    with pytest.raises(ValueError, match="No meaningful Markdown content"):
        exporter.export(
            url="https://example.com/empty",
            soup=soup,
            title="Empty",
            language="en",
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Hello World", "hello-world"),
        ("  API___Reference  ", "api___reference"),
        ("Çığ Öğütücü", "cg-ogutucu"),
        ("...", "page"),
        ("a---b", "a-b"),
    ],
)
def test_markdown_exporter_slugify(
    value: str,
    expected: str,
) -> None:
    assert MarkdownExporter._slugify(value) == expected


def test_markdown_exporter_output_paths_are_stable_and_distinct(
    tmp_path: Path,
) -> None:
    exporter = MarkdownExporter(tmp_path)

    first = exporter._build_output_path(
        url="https://example.com/docs/page?version=1",
        title="Page",
    )
    repeated = exporter._build_output_path(
        url="https://example.com/docs/page?version=1",
        title="Changed Title",
    )
    second = exporter._build_output_path(
        url="https://example.com/docs/page?version=2",
        title="Page",
    )

    assert first == repeated
    assert first != second
    assert first.parent == (tmp_path / "example.com" / "docs").resolve()
    assert first.is_relative_to(tmp_path.resolve())
    assert second.is_relative_to(tmp_path.resolve())


def test_markdown_exporter_atomic_write_replaces_existing_file(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "document.md"
    output_path.write_text("old", encoding="utf-8")

    MarkdownExporter._atomic_write(
        output_path=output_path,
        content="new",
    )

    assert output_path.read_text(encoding="utf-8") == "new"
    assert not output_path.with_suffix(".md.tmp").exists()
