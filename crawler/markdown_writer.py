from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from crawler.shared.url_normalizer import normalize_url

READ_ONLY_MODE = 0o444
WRITE_MODE = 0o644


class MarkdownWriter:
    """Write one current Markdown file per normalized URL.

    Markdown files are stored directly inside the configured project directory.
    No raw snapshot directories, content-history files, or project-local state
    databases are created.
    """

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = Path(output_dir)

    def exists(self, *, url: str) -> bool:
        """Return whether the current Markdown file exists for a URL."""

        return self.current_markdown_exists_for_url(url=url)

    def current_markdown_exists_for_url(self, *, url: str) -> bool:
        normalized_url = self._normalize_url(url)
        url_hash = self._sha256_text(normalized_url)

        return self.current_markdown_exists(url_hash=url_hash)

    def current_markdown_exists(self, *, url_hash: str) -> bool:
        short_hash = url_hash[:12]

        if not self.output_dir.is_dir():
            return False

        return any(
            path.is_file() for path in self.output_dir.glob(f"*__{short_hash}.md")
        )

    def write(self, *, url: str, title: str, markdown: str) -> Path:
        """Write or replace the single current Markdown file for a URL."""

        normalized_url = self._normalize_url(url)
        url_hash = self._sha256_text(normalized_url)

        document = self._build_document(
            url=normalized_url,
            title=title,
            markdown=markdown,
        )

        return self._write_current_markdown(
            url_hash=url_hash,
            title=title,
            document=document,
        )

    def _write_current_markdown(
        self,
        *,
        url_hash: str,
        title: str,
        document: str,
    ) -> Path:
        current_path = self._current_path(
            url_hash=url_hash,
            title=title,
        )

        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._remove_stale_current_markdown(
            url_hash=url_hash,
            current_path=current_path,
        )

        self._unlock(current_path)
        current_path.write_text(document, encoding="utf-8")
        self._lock(current_path)

        return current_path

    def _remove_stale_current_markdown(
        self,
        *,
        url_hash: str,
        current_path: Path,
    ) -> None:
        short_hash = url_hash[:12]

        if not self.output_dir.is_dir():
            return

        for path in self.output_dir.glob(f"*__{short_hash}.md"):
            if not path.is_file() or path == current_path:
                continue

            self._unlock(path)

            try:
                path.unlink()
            except OSError:
                self._lock(path)

    def _current_path(self, *, url_hash: str, title: str) -> Path:
        filename = f"{self._safe_filename(title)}__{url_hash[:12]}.md"
        return self.output_dir / filename

    def _build_document(self, *, url: str, title: str, markdown: str) -> str:
        safe_title = self._clean_title(title)
        clean_markdown = markdown.strip()

        heading = f"# {safe_title}"

        if clean_markdown.startswith(heading):
            clean_markdown = clean_markdown[len(heading) :].strip()

        return f"{heading}\n\nOriginal URL: {url}\n\n---\n\n{clean_markdown}\n"

    def _normalize_url(self, url: str) -> str:
        normalized = normalize_url(url)

        if normalized is None:
            raise ValueError("URL could not be normalized.")

        return normalized

    def _clean_title(self, title: str) -> str:
        cleaned_title = " ".join(title.split())
        return cleaned_title or "Untitled Page"

    def _safe_filename(self, title: str) -> str:
        value = self._clean_title(title).lower()
        value = re.sub(r"[^a-z0-9]+", "-", value)
        value = value.strip("-")

        return value or "document"

    def _sha256_text(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _lock(self, path: Path) -> None:
        if path.exists():
            os.chmod(path, READ_ONLY_MODE)

    def _unlock(self, path: Path) -> None:
        if path.exists():
            os.chmod(path, WRITE_MODE)
