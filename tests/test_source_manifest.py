from pathlib import Path

import pytest

from crawler.source_manifest import SourceManifest, normalize_project_name


def test_normalize_project_name_strips_outer_whitespace() -> None:
    assert normalize_project_name("  openai  ") == "openai"


@pytest.mark.parametrize("project_name", ["", "   ", ".", ".."])
def test_normalize_project_name_rejects_unsafe_names(project_name: str) -> None:
    with pytest.raises(ValueError):
        normalize_project_name(project_name)


def test_source_manifest_builds_expected_workspace_paths(tmp_path: Path) -> None:
    manifest = SourceManifest.from_project_name(
        project_name=" openai ",
        root_dir=tmp_path,
    )

    assert manifest.project_name == "openai"
    assert manifest.workspace_dir == tmp_path / "openai"
    assert manifest.seed_file == tmp_path / "openai" / "openai.seed.txt"
    assert manifest.allow_file == tmp_path / "openai" / "openai.allow.txt"
    assert manifest.block_file == tmp_path / "openai" / "openai.block.txt"
    assert manifest.discovery_report == tmp_path / "openai" / "openai.discovery.md"
    assert manifest.output_dir == tmp_path / "openai" / "output"


def test_source_manifest_ensure_workspace_is_idempotent(tmp_path: Path) -> None:
    manifest = SourceManifest.from_project_name(
        project_name="openai",
        root_dir=tmp_path,
    )

    manifest.ensure_workspace()
    manifest.ensure_workspace()

    assert manifest.workspace_dir.is_dir()
    assert manifest.output_dir.is_dir()
