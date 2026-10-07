from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .core import DEFAULT_OUTPUT_DIR, split_markdown_directory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mdparts",
        description=(
            "Recursively find .md files and merge them into an exact number "
            "of evenly sized parts by file count."
        ),
    )
    parser.add_argument("input_directory", type=Path)
    parser.add_argument(
        "--parts",
        type=int,
        required=True,
        help="Exact number of output Markdown files.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        results = split_markdown_directory(
            input_dir=args.input_directory,
            parts=args.parts,
        )
    except (ValueError, FileExistsError, OSError) as exc:
        print(f"ERROR: {exc}")
        return 1

    total_files = sum(file_count for _, file_count in results)
    print(f"Markdown files: {total_files}")
    print(f"Parts: {len(results)}")
    print(f"Output directory: {DEFAULT_OUTPUT_DIR}")

    for output_path, file_count in results:
        print(f"{output_path.name}: {file_count} files")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
