"""Regression coverage for form extraction and terminal processed accounting."""

from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup

from docsync.markdown import MarkdownExporter

ROOT = Path(__file__).resolve().parents[1]
CRAWLER_PATH = ROOT / "src" / "docsync" / "crawler.py"
MARKDOWN_PATH = ROOT / "src" / "docsync" / "markdown.py"


def _function(
    tree: ast.Module,
    name: str,
) -> ast.AsyncFunctionDef:
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name
    ]

    assert len(matches) == 1
    return matches[0]


def _processed_augassign_lines(
    function: ast.AsyncFunctionDef,
) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.AugAssign)
        and isinstance(node.target, ast.Attribute)
        and isinstance(node.target.value, ast.Name)
        and node.target.value.id == "stats"
        and node.target.attr == "processed"
        and isinstance(node.op, ast.Add)
    ]


def test_form_explanatory_text_is_preserved(
    tmp_path: Path,
) -> None:
    exporter = MarkdownExporter(tmp_path)

    soup = BeautifulSoup(
        """
        <html>
          <head>
            <title>Submission form</title>
          </head>
          <body>
            <main>
              <form>
                <h1>Submit crawler details</h1>
                <p>
                  Explain the crawler purpose and provide public documentation.
                </p>
                <label>
                  User-Agent string
                  <input name="user_agent">
                </label>
                <label>
                  Contact email
                  <input name="email">
                </label>
              </form>
            </main>
          </body>
        </html>
        """,
        "html.parser",
    )

    document = exporter.export(
        url="https://example.com/submission-form",
        soup=soup,
        title="Submission form",
        language="en",
        write=False,
    )

    assert "Submit crawler details" in document.markdown
    assert "Explain the crawler purpose" in document.markdown
    assert "User-Agent string" in document.markdown
    assert "Contact email" in document.markdown


def test_url_only_empty_page_is_still_rejected(
    tmp_path: Path,
) -> None:
    exporter = MarkdownExporter(tmp_path)

    soup = BeautifulSoup(
        "<html><body><main><script>shell</script></main></body></html>",
        "html.parser",
    )

    try:
        exporter.export(
            url="https://example.com/empty",
            soup=soup,
            title="",
            language="en",
            write=False,
        )
    except ValueError as error:
        assert str(error).startswith("No meaningful Markdown content found:")
    else:
        raise AssertionError("Expected empty page rejection")


def test_form_is_not_globally_removed() -> None:
    source = MARKDOWN_PATH.read_text(encoding="utf-8")

    remove_block = source.split(
        "REMOVE_SELECTORS = (",
        1,
    )[1].split(
        ")",
        1,
    )[0]

    assert '"form"' not in remove_block
    assert '"input"' in remove_block
    assert '"textarea"' in remove_block
    assert '"select"' in remove_block
