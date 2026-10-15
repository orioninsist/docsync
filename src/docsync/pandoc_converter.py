"""Pandoc-based HTML to GitHub Flavored Markdown conversion."""

from __future__ import annotations

import os
import shutil
import subprocess


class PandocConversionError(RuntimeError):
    """Pandoc conversion failed or produced unusable output."""


def html_to_gfm(html: str) -> str:
    """Convert HTML to GFM without modifying the input HTML."""
    if not html.strip():
        raise PandocConversionError("Empty HTML input")

    executable = shutil.which("pandoc")
    if executable is None:
        raise PandocConversionError(
            "Pandoc executable not found. Install Pandoc before syncing."
        )

    try:
        result = subprocess.run(
            [
                executable,
                "--from=html",
                "--to=gfm-raw_html",
                "--wrap=none",
            ],
            input=html,
            text=True,
            capture_output=True,
            check=True,
            timeout=120,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise PandocConversionError(f"Pandoc conversion failed: {exc}") from exc

    markdown = result.stdout.strip()
    if not markdown:
        raise PandocConversionError("Pandoc produced empty Markdown")

    validator = os.environ.get("DOCSYNC_GFM_VALIDATOR") or shutil.which(
        "docsync-gfm-validator"
    )
    if not validator:
        raise PandocConversionError(
            "Goldmark validator not found. Build tools/gfm-validator and "
            "set DOCSYNC_GFM_VALIDATOR or add docsync-gfm-validator to PATH."
        )

    try:
        subprocess.run(
            [validator],
            input=markdown,
            text=True,
            capture_output=True,
            check=True,
            timeout=120,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise PandocConversionError(f"Goldmark validation failed: {exc}") from exc

    return markdown
