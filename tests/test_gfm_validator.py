from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from docsync.pandoc_converter import (
    PandocConversionError,
    html_to_gfm,
)

HTML = "<h1>Documentation</h1><p>Important content.</p>"


def test_goldmark_success(tmp_path: Path) -> None:
    validator = tmp_path / "accept-validator"
    validator.write_text("#!/bin/sh\ncat >/dev/null\nexit 0\n", encoding="utf-8")
    validator.chmod(0o755)

    with patch.dict(
        "os.environ",
        {"DOCSYNC_GFM_VALIDATOR": str(validator)},
    ):
        markdown = html_to_gfm(HTML)

    assert "# Documentation" in markdown
    assert "Important content." in markdown


def test_goldmark_rejects_missing_executable() -> None:
    with (
        patch.dict(
            "os.environ",
            {"DOCSYNC_GFM_VALIDATOR": "/nonexistent/docsync-validator"},
        ),
        pytest.raises(PandocConversionError, match="Goldmark validation failed"),
    ):
        html_to_gfm(HTML)


def test_goldmark_rejects_failed_validation(tmp_path: Path) -> None:
    validator = tmp_path / "reject-validator"
    validator.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    validator.chmod(0o755)

    with (
        patch.dict(
            "os.environ",
            {"DOCSYNC_GFM_VALIDATOR": str(validator)},
        ),
        pytest.raises(PandocConversionError, match="Goldmark validation failed"),
    ):
        html_to_gfm(HTML)


def test_html_table_preserves_cells_in_gfm() -> None:
    """Complex HTML tables must not become Pandoc's [TABLE] placeholder."""
    html = """
    <h1>Model specifications</h1>
    <table role="table">
      <thead><tr><th>Property</th><th>Description</th></tr></thead>
      <tbody>
        <tr>
          <td><section><p>Token limits</p></section></td>
          <td>
            <p><strong>Input token limit</strong> 1,048,576</p>
            <p><strong>Output token limit</strong> 65,536</p>
          </td>
        </tr>
      </tbody>
    </table>
    """
    markdown = html_to_gfm(html)

    assert "[TABLE]" not in markdown
    assert "Token limits" in markdown
    assert "Input token limit" in markdown
    assert "1,048,576" in markdown
    assert "Output token limit" in markdown
    assert "65,536" in markdown


def test_complex_model_table_preserves_content_and_links() -> None:
    """Preserve nested model specifications, links, and table cells."""
    html = """
    <h1>Gemini 3.5 Flash-Lite</h1>
    <ms-docs-table>
      <table class="mat-mdc-table variant-model" role="table">
        <thead>
          <tr><th>Property</th><th>Description</th></tr>
        </thead>
        <tbody>
          <tr>
            <td><section><p>Token limits</p></section></td>
            <td>
              <p><strong>Input token limit</strong> 1,048,576</p>
              <p><strong>Output token limit</strong> 65,536</p>
            </td>
          </tr>
          <tr>
            <td><p>Documentation</p></td>
            <td>
              <a href="https://example.com/docs/models">
                Model documentation
              </a>
            </td>
          </tr>
        </tbody>
      </table>
    </ms-docs-table>
    """
    markdown = html_to_gfm(html)

    assert "[TABLE]" not in markdown
    assert "<table" in markdown
    assert "</table>" in markdown
    assert "Gemini 3.5 Flash-Lite" in markdown
    assert "Token limits" in markdown
    assert "Input token limit" in markdown
    assert "1,048,576" in markdown
    assert "Output token limit" in markdown
    assert "65,536" in markdown
    assert "Model documentation" in markdown
    assert "https://example.com/docs/models" in markdown
