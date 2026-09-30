import argparse
import json
from pathlib import Path

from .scanner import scan_markdown_files
from .splitter import split_files
from .summary import create_summary
from .validator import validate_output
from .writer import write_parts


def _paths_overlap(input_directory: str, output_directory: str) -> bool:
    input_path = Path(input_directory).resolve()
    output_path = Path(output_directory).resolve()

    try:
        output_path.relative_to(input_path)
        return True
    except ValueError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge Markdown files by token limit without modifying content."
    )

    parser.add_argument("input_directory")
    parser.add_argument("output_directory")
    parser.add_argument(
        "--name",
        required=True,
        help="Base name for generated Markdown parts (for example: openai).",
    )
    parser.add_argument(
        "--token-limit",
        type=int,
        required=True,
    )
    parser.add_argument(
        "--reserve-tokens",
        type=int,
        default=5000,
        help="Token budget kept unused in each part (default: 5000).",
    )

    tokenizer_group = parser.add_mutually_exclusive_group()
    tokenizer_group.add_argument(
        "--model",
        default="gpt-4o",
        help="Model name passed to tiktoken.encoding_for_model (default: gpt-4o).",
    )
    tokenizer_group.add_argument(
        "--encoding",
        dest="encoding_name",
        help="Explicit tiktoken encoding name, for example o200k_base.",
    )

    args = parser.parse_args()

    if not args.name.strip():
        parser.error("--name cannot be empty.")
    if args.name in {".", ".."} or "/" in args.name or "\\" in args.name:
        parser.error("--name must be a filename base, not a path.")
    if args.name.lower().endswith(".md"):
        parser.error("--name must not include the .md extension.")
    if args.token_limit <= 0:
        parser.error("--token-limit must be greater than zero.")
    if args.reserve_tokens < 0:
        parser.error("--reserve-tokens cannot be negative.")
    if args.reserve_tokens >= args.token_limit:
        parser.error("--reserve-tokens must be smaller than --token-limit.")
    if _paths_overlap(args.input_directory, args.output_directory):
        parser.error("OUTPUT_DIRECTORY must be outside INPUT_DIRECTORY.")

    model = None if args.encoding_name else args.model
    tokenizer_name = (
        f"encoding:{args.encoding_name}"
        if args.encoding_name
        else f"model:{args.model}"
    )

    print("Markdown Merge Started")
    print()
    print(f"Input: {args.input_directory}")
    print(f"Output: {args.output_directory}")
    print(f"Name: {args.name}")
    print(f"Token Limit: {args.token_limit}")
    print(f"Reserve Tokens: {args.reserve_tokens}")
    print(f"Tokenizer: {tokenizer_name}")
    print()

    print("Scanning markdown files...")
    files = scan_markdown_files(args.input_directory)

    if not files:
        raise SystemExit("No Markdown files found.")

    print(f"Found files: {len(files)}")
    print()

    print("Counting tokens and creating parts...")
    parts = split_files(
        files,
        args.token_limit,
        input_directory=args.input_directory,
        reserve_tokens=args.reserve_tokens,
        model=model,
        encoding_name=args.encoding_name,
    )

    print(f"Created parts: {len(parts)}")
    print()

    print("Writing output files...")
    created_files = write_parts(
        parts,
        args.output_directory,
        args.input_directory,
        args.name,
    )

    validation = validate_output(
        created_files,
        args.token_limit,
        model=model,
        encoding_name=args.encoding_name,
    )

    output_path = Path(args.output_directory)

    validation_path = output_path / "validation.txt"
    validation_path.write_text(
        validation.report,
        encoding="utf-8",
    )
    validation_path.chmod(0o644)

    summary = create_summary(
        parts,
        args.token_limit,
        len(files),
        reserve_tokens=args.reserve_tokens,
        tokenizer_name=tokenizer_name,
        validation=validation,
    )

    summary_path = output_path / "summary.txt"
    summary_path.write_text(
        summary,
        encoding="utf-8",
    )
    summary_path.chmod(0o644)

    manifest = {
        "input_directory": str(Path(args.input_directory)),
        "token_limit": args.token_limit,
        "reserve_tokens": args.reserve_tokens,
        "effective_token_limit": args.token_limit - args.reserve_tokens,
        "tokenizer": tokenizer_name,
        "input_files": len(files),
        "created_parts": len(created_files),
        "validation_passed": validation.passed,
        "parts": [
            {
                "file": item.name,
                "tokens": item.tokens,
                "sources": item.sources,
                "status": item.status,
                "source_files": [
                    file_chunk.source_path for file_chunk in parts[index].files
                ],
            }
            for index, item in enumerate(validation.parts)
        ],
    }

    manifest_path = output_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    manifest_path.chmod(0o644)

    print()
    print(summary)
    print()
    print(validation.report)
    print()

    if not validation.passed:
        raise SystemExit("Validation failed.")

    print("Completed.")
