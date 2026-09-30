from pathlib import Path


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def scan_markdown_files(
    input_directory: str,
    *,
    exclude_directory: str | None = None,
) -> list[Path]:
    path = Path(input_directory).resolve()

    if not path.exists():
        raise FileNotFoundError(f"Input directory not found: {input_directory}")
    if not path.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {input_directory}")

    excluded = Path(exclude_directory).resolve() if exclude_directory else None

    return sorted(
        file
        for file in path.rglob("*.md")
        if file.is_file()
        and not (excluded is not None and _is_relative_to(file.resolve(), excluded))
    )
