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
