from __future__ import annotations

from pathlib import Path

from crawler.time_utils import utc_now

RUNTIME_STATE_ROOT = Path("state")
RUNTIME_LOGS_ROOT = Path("logs")


def build_runtime_paths(
    project_slug: str,
    workspace: str | None,
    run_id: str | None = None,
) -> tuple[Path, Path]:
    resolved_run_id = run_id or build_run_id()
    project_logs_root = RUNTIME_LOGS_ROOT / (workspace or project_slug)

    if workspace:
        database_path = RUNTIME_STATE_ROOT / workspace / f"{project_slug}.db"
    else:
        database_path = RUNTIME_STATE_ROOT / f"{project_slug}.db"

    return (
        database_path,
        project_logs_root / resolved_run_id,
    )


def build_run_id() -> str:
    return utc_now().replace("+00:00", "Z").replace(":", "-")
