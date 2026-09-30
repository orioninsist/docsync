from pathlib import Path

from .splitter import Part


def write_parts(
    parts: list[Part],
    output_directory: str,
    input_directory: str,
    name: str,
) -> list[Path]:
    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)

    # Remove stale part files from previous runs for this merge name.
    #
    # Example:
    #   previous run -> docs-1.md ... docs-32.md
    #   current run  -> docs-1.md ... docs-28.md
    #
    # Without cleanup, docs-29.md ... docs-32.md would remain in the
    # output directory even though they no longer belong to this run.
    for stale_path in output_path.glob(f"{name}-*.md"):
        suffix = stale_path.stem.removeprefix(f"{name}-")
        if suffix.isdigit():
            stale_path.unlink()

    created_files: list[Path] = []

    for index, part in enumerate(parts, start=1):
        file_path = output_path / f"{name}-{index}.md"

        with file_path.open("w", encoding="utf-8") as output:
            for file_chunk in part.files:
                output.write(f"# Source: {file_chunk.source_path}\n\n")

                if file_chunk.content is not None:
                    output.write(file_chunk.content)
                else:
                    output.write(file_chunk.path.read_text(encoding="utf-8"))

                output.write("\n\n")

        file_path.chmod(0o644)
        created_files.append(file_path)

    return created_files
