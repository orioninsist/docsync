from __future__ import annotations

from pathlib import Path

RUNTIME_STATE_ROOT = Path("state")
RUNTIME_LOGS_ROOT = Path("logs")


def build_runtime_paths(project_slug: str, workspace: str | None) -> tuple[Path, Path]:
    if workspace:
        return (
            RUNTIME_STATE_ROOT / workspace / f"{project_slug}.db",
            RUNTIME_LOGS_ROOT / workspace / project_slug,
        )

    return (
        RUNTIME_STATE_ROOT / f"{project_slug}.db",
        RUNTIME_LOGS_ROOT / project_slug,
    )
