from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

from crawler.shared.url_normalizer import normalize_url

READ_ONLY_MODE = 0o444
WRITE_MODE = 0o644


class MarkdownWriter:
    """Write one verified current Markdown file per normalized URL.

    Markdown files are stored directly inside the configured project directory.
    Writes are performed atomically in the destination directory. A successful
    return guarantees that the expected file exists and contains the complete
    generated document.
    """

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = Path(output_dir)

    def exists(self, *, url: str) -> bool:
        """Return whether the current Markdown file exists for a URL."""

        return self.current_markdown_exists_for_url(url=url)

    def current_markdown_exists_for_url(self, *, url: str) -> bool:
        """Return whether a Markdown output exists for the normalized URL."""

        normalized_url = self._normalize_url(url)
        url_hash = self._sha256_text(normalized_url)

        return self.current_markdown_exists(url_hash=url_hash)

    def current_markdown_exists(self, *, url_hash: str) -> bool:
        """Return whether a current Markdown file exists for a URL hash."""

        short_hash = url_hash[:12]

        if not self.output_dir.is_dir():
            return False

        return any(
            path.is_file()
            for path in self.output_dir.glob(f"*__{short_hash}.md")
        )

    def write(self, *, url: str, title: str, markdown: str) -> Path:
        """Atomically write and verify the current Markdown file for a URL."""

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
        """Atomically replace, verify, and lock one Markdown output."""

        current_path = self._current_path(
            url_hash=url_hash,
            title=title,
        )

        self.output_dir.mkdir(parents=True, exist_ok=True)

        temporary_path = self._write_temporary_file(
            current_path=current_path,
            document=document,
        )

        try:
            self._unlock(current_path)
            os.replace(temporary_path, current_path)
            self._sync_directory()
            self._verify_written_file(
                path=current_path,
                expected_document=document,
            )
            self._lock(current_path)
        except Exception as error:
            self._remove_temporary_file(temporary_path)

            raise RuntimeError(
                "Markdown output could not be written and verified: "
                f"path={current_path} error={error}"
            ) from error

        self._remove_stale_current_markdown(
            url_hash=url_hash,
            current_path=current_path,
        )

        return current_path

    def _write_temporary_file(
        self,
        *,
        current_path: Path,
        document: str,
    ) -> Path:
        """Write and fsync a temporary file beside the final destination."""

        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{current_path.name}.",
            suffix=".tmp",
            dir=self.output_dir,
            text=False,
        )
        temporary_path = Path(raw_path)

        try:
            with os.fdopen(descriptor, "wb") as file:
                payload = document.encode("utf-8")
                file.write(payload)
                file.flush()
                os.fsync(file.fileno())

            os.chmod(temporary_path, WRITE_MODE)
            return temporary_path

        except Exception as error:
            try:
                os.close(descriptor)
            except OSError:
                pass

            self._remove_temporary_file(temporary_path)

            raise RuntimeError(
                "Temporary Markdown output could not be written: "
                f"path={temporary_path} error={error}"
            ) from error

    def _verify_written_file(
        self,
        *,
        path: Path,
        expected_document: str,
    ) -> None:
        """Verify that the final file exists and contains the full document."""

        if not path.exists():
            raise RuntimeError(
                f"Markdown output does not exist after write: {path}"
            )

        if not path.is_file():
            raise RuntimeError(
                f"Markdown output path is not a regular file: {path}"
            )

        expected_bytes = expected_document.encode("utf-8")
        actual_size = path.stat().st_size

        if actual_size != len(expected_bytes):
            raise RuntimeError(
                "Markdown output size verification failed: "
                f"path={path} expected={len(expected_bytes)} "
                f"actual={actual_size}"
            )

        actual_document = path.read_text(encoding="utf-8")

        if actual_document != expected_document:
            raise RuntimeError(
                f"Markdown output content verification failed: path={path}"
            )

    def _remove_stale_current_markdown(
        self,
        *,
        url_hash: str,
        current_path: Path,
    ) -> None:
        """Remove obsolete filenames only after the new file is verified."""

        short_hash = url_hash[:12]

        if not self.output_dir.is_dir():
            return

        for path in self.output_dir.glob(f"*__{short_hash}.md"):
            if not path.is_file() or path == current_path:
                continue

            self._unlock(path)

            try:
                path.unlink()
            except OSError as error:
                self._lock(path)

                raise RuntimeError(
                    "Stale Markdown output could not be removed: "
                    f"path={path} error={error}"
                ) from error

    def _remove_temporary_file(self, path: Path) -> None:
        """Remove an abandoned temporary file when it still exists."""

        try:
            if path.exists():
                path.unlink()
        except OSError:
            return

    def _sync_directory(self) -> None:
        """Flush the destination directory entry after atomic replacement."""

        directory_descriptor: int | None = None

        try:
            directory_descriptor = os.open(
                self.output_dir,
                os.O_RDONLY,
            )
            os.fsync(directory_descriptor)
        except OSError:
            return
        finally:
            if directory_descriptor is not None:
                os.close(directory_descriptor)

    def _current_path(self, *, url_hash: str, title: str) -> Path:
        """Build the deterministic current Markdown output path."""

        filename = (
            f"{self._safe_filename(title)}__{url_hash[:12]}.md"
        )
        return self.output_dir / filename

    def _build_document(
        self,
        *,
        url: str,
        title: str,
        markdown: str,
    ) -> str:
        """Build the complete Markdown document stored on disk."""

        safe_title = self._clean_title(title)
        clean_markdown = markdown.strip()

        heading = f"# {safe_title}"

        if clean_markdown.startswith(heading):
            clean_markdown = clean_markdown[len(heading):].strip()

        return (
            f"{heading}\n\n"
            f"Original URL: {url}\n\n"
            "---\n\n"
            f"{clean_markdown}\n"
        )

    def _normalize_url(self, url: str) -> str:
        """Return the canonical URL representation used for file identity."""

        normalized = normalize_url(url)

        if normalized is None:
            raise ValueError(
                f"URL could not be normalized: {url!r}"
            )

        return normalized

    def _clean_title(self, title: str) -> str:
        """Normalize whitespace and provide a non-empty document title."""

        cleaned_title = " ".join(title.split())
        return cleaned_title or "Untitled Page"

    def _safe_filename(self, title: str) -> str:
        """Convert a title into a portable lowercase filename component."""

        value = self._clean_title(title).lower()
        value = re.sub(r"[^a-z0-9]+", "-", value)
        value = value.strip("-")

        return value or "document"

    def _sha256_text(self, value: str) -> str:
        """Return a stable SHA-256 digest for text."""

        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _lock(self, path: Path) -> None:
        """Make an existing Markdown output read-only."""

        if not path.is_file():
            raise RuntimeError(
                f"Cannot lock missing Markdown output: {path}"
            )

        try:
            os.chmod(path, READ_ONLY_MODE)
        except OSError as error:
            raise RuntimeError(
                f"Markdown output could not be locked: path={path}"
            ) from error

    def _unlock(self, path: Path) -> None:
        """Make an existing Markdown output writable."""

        if not path.exists():
            return

        if not path.is_file():
            raise RuntimeError(
                f"Markdown output path is not a regular file: {path}"
            )

        try:
            os.chmod(path, WRITE_MODE)
        except OSError as error:
            raise RuntimeError(
                f"Markdown output could not be unlocked: path={path}"
            ) from error
