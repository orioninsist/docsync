from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

PIPELINE_FILES = (
    PROJECT_ROOT / "pipeline" / "run_pipeline.py",
    PROJECT_ROOT / "pipeline" / "release_validate.py",
)

FORBIDDEN_LOCAL_OWNERSHIP_PATTERNS = (
    "Path(__file__).resolve().parents",
    "ROOT =",
    "PROJECT_ROOT =",
    "STATE_ROOT =",
    "LOGS_ROOT =",
    "REPORTS_ROOT =",
    "RUNS_ROOT =",
)


def test_pipeline_entrypoints_do_not_redeclare_path_ownership() -> None:
    for path in PIPELINE_FILES:
        source = path.read_text(encoding="utf-8")

        for pattern in FORBIDDEN_LOCAL_OWNERSHIP_PATTERNS:
            assert pattern not in source, (
                f"{path.relative_to(PROJECT_ROOT)} must not redeclare pipeline path "
                f"ownership with {pattern!r}. Use pipeline.paths instead."
            )


def test_pipeline_entrypoints_import_centralized_paths() -> None:
    for path in PIPELINE_FILES:
        source = path.read_text(encoding="utf-8")

        assert "pipeline.paths" in source, (
            f"{path.relative_to(PROJECT_ROOT)} must import centralized path ownership "
            "from pipeline.paths."
        )
