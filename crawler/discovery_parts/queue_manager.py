"""Queue TXT read/write helpers for smart discovery."""

from collections.abc import Iterable
from pathlib import Path


def queue_file_path(folder: str | Path) -> Path:
    """Return the deterministic queue file path for a crawler folder."""
    folder_path = Path(folder)
    return folder_path.with_name(f"{folder_path.name}_queue.txt")


def write_queue_file(folder: str | Path, urls: Iterable[str]) -> Path:
    """Write sorted unique URLs to the editable queue TXT file."""
    queue_path = queue_file_path(folder)
    queue_path.parent.mkdir(parents=True, exist_ok=True)

    unique_urls = sorted({url.strip() for url in urls if url.strip()})
    queue_path.write_text("\n".join(unique_urls) + "\n", encoding="utf-8")

    return queue_path


def read_queue_file(folder: str | Path) -> list[str]:
    """Read cleaned URLs from the editable queue TXT file."""
    queue_path = queue_file_path(folder)
    if not queue_path.exists():
        return []

    return [
        line.strip()
        for line in queue_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
