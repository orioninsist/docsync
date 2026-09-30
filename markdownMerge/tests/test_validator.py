from pathlib import Path

from markdown_merge.validator import validate_output


def test_validator_passes_valid_output(tmp_path: Path) -> None:
    file = tmp_path / "part_001.md"
    file.write_text("# Source: test.md\n\n# Test", encoding="utf-8")

    result = validate_output([file], 100)

    assert result.passed is True
    assert "PASSED" in result.report


def test_validator_fails_when_token_limit_is_exceeded(tmp_path: Path) -> None:
    file = tmp_path / "part_001.md"
    file.write_text("# Source: test.md\n\n" + ("token " * 100), encoding="utf-8")

    result = validate_output([file], 10)

    assert result.passed is False
    assert "token limit exceeded" in result.report
    assert "Validation Result: FAILED" in result.report


def test_validator_fails_when_source_markers_are_missing(tmp_path: Path) -> None:
    file = tmp_path / "part_001.md"
    file.write_text("# Test", encoding="utf-8")

    result = validate_output([file], 100)

    assert result.passed is False
    assert "no source markers found" in result.report


def test_validator_ignores_unrelated_markdown_files(tmp_path: Path) -> None:
    generated = tmp_path / "part_001.md"
    unrelated = tmp_path / "notes.md"
    generated.write_text("# Source: test.md\n\n# Test", encoding="utf-8")
    unrelated.write_text("# Notes", encoding="utf-8")

    result = validate_output([generated], 100)

    assert result.passed is True
    assert [part.name for part in result.parts] == ["part_001.md"]


def test_validator_requires_exact_source_marker_line(tmp_path: Path) -> None:
    file = tmp_path / "part_001.md"
    file.write_text(
        "# Source: real.md\n\nText containing # Source: fake.md inline.",
        encoding="utf-8",
    )

    result = validate_output([file], 100)

    assert result.parts[0].sources == 1


def test_validator_fails_for_empty_part_list() -> None:
    result = validate_output([], 100)

    assert result.passed is False
    assert "Parts Found: 0" in result.report
