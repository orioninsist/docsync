from __future__ import annotations

from pathlib import Path

EXPECTED_OWNER = Path("pipeline/file_hash.py")
THIS_TEST = Path("tests/test_file_hash_ownership.py")


def test_sha256_file_has_single_owner() -> None:
    project_root = Path(__file__).resolve().parents[1]
    owners: list[Path] = []

    for path in project_root.rglob("*.py"):
        relative_path = path.relative_to(project_root)

        if ".venv" in path.parts or relative_path == THIS_TEST:
            continue

        text = path.read_text(encoding="utf-8")
        if "def sha256_file(" in text:
            owners.append(relative_path)

    assert owners == [EXPECTED_OWNER]
