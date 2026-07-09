from __future__ import annotations

import os
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Sequence


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    project_root = str(_project_root())
    current_pythonpath = env.get("PYTHONPATH")

    if current_pythonpath:
        env["PYTHONPATH"] = f"{project_root}{os.pathsep}{current_pythonpath}"
    else:
        env["PYTHONPATH"] = project_root

    return env


def run_python_script(
    script: Path,
    args: Sequence[str],
    *,
    cwd: Path | None = None,
) -> int:
    command = [sys.executable, str(script), *args]
    return subprocess.run(  # nosec B603
        command,
        check=False,
        cwd=cwd,
        env=_subprocess_env(),
    ).returncode


def run_command(command: Sequence[str], *, cwd: Path | None = None) -> int:
    return subprocess.run(  # nosec B603
        list(command),
        check=False,
        cwd=cwd,
        env=_subprocess_env(),
    ).returncode
