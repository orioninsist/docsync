from __future__ import annotations

import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Sequence


def run_python_script(
    *,
    script: Path,
    args: Sequence[Path | str] = (),
    cwd: Path | None = None,
) -> int:
    if not script.is_file():
        print(f"[ERROR] Missing Python script: {script}")
        return 1

    command = [sys.executable, str(script), *(str(arg) for arg in args)]
    result = subprocess.run(command, cwd=cwd, check=False)  # nosec B603
    return result.returncode


def run_command(command: Sequence[str], *, cwd: Path | None = None) -> int:
    if not command:
        print("[ERROR] Empty command refused.")
        return 1

    result = subprocess.run(list(command), cwd=cwd, check=False)  # nosec B603
    return result.returncode
