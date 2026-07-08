"""CLI approval helpers for the two-phase discovery workflow."""

from pathlib import Path

from crawler.discovery_parts.queue_manager import read_queue_file, write_queue_file


def _read_approval(prompt: str) -> bool:
    """Return True when the user explicitly approves with y or e."""
    answer = input(prompt).strip().lower()
    return answer in {"y", "e"}


def is_discovery_approved() -> bool:
    """Ask whether Phase 1 discovery should start."""
    return _read_approval("Start Phase 1 discovery? [y/e]: ")


def is_execution_approved() -> bool:
    """Ask whether Phase 2 execution should start after queue edit."""
    return _read_approval("Start Phase 2 execution from edited queue? [y/e]: ")


def save_queue_file(folder: Path, urls: list[str]) -> Path:
    """Save discovered URLs to the queue file."""
    return write_queue_file(str(folder), urls)


def load_queue_file(folder: Path) -> list[str]:
    """Load edited URLs from the queue file."""
    return read_queue_file(str(folder))
