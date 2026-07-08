from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = PROJECT_ROOT / "crawler_cli.py"
RUNTIME_PATHS_PATH = PROJECT_ROOT / "crawler" / "runtime_paths.py"


def test_runtime_paths_module_is_the_single_owner() -> None:
    cli_source = CLI_PATH.read_text(encoding="utf-8")
    runtime_paths_source = RUNTIME_PATHS_PATH.read_text(encoding="utf-8")

    assert "def build_runtime_paths(" not in cli_source
    assert "from crawler.runtime_paths import build_runtime_paths" in cli_source
    assert "def build_runtime_paths(" in runtime_paths_source


def test_cli_does_not_reintroduce_stale_runtime_roots() -> None:
    cli_source = CLI_PATH.read_text(encoding="utf-8")

    assert "RUNTIME_STATE_ROOT" not in cli_source
    assert "RUNTIME_LOGS_ROOT" not in cli_source
