import argparse
import json
from pathlib import Path

from .scanner import scan_markdown_files
from .splitter import split_files
from .summary import create_summary
from .validator import CHATGPT_MAX_BYTES, validate_output
from .writer import write_parts

MARKDOWN_MERGE_BASE_DIR = Path("/home/murat/Media/8-Document/markdownMerge")
DEFAULT_TOKEN_LIMIT = 1_800_000
DEFAULT_RESERVE_TOKENS = 50_000


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
        description=(
            "Merge Markdown into a minimal number of ChatGPT/OpenAI-safe files "
            "without modifying source content."
        )
    )

    parser.add_argument("input_directory")
    parser.add_argument(
        "--name",
        help=(
            "Base name for generated Markdown parts. "
            "Defaults to the input directory name."
        ),
    )
    parser.add_argument(
        "--token-limit",
        type=int,
        default=DEFAULT_TOKEN_LIMIT,
        help=(f"Final token ceiling per output file (default: {DEFAULT_TOKEN_LIMIT})."),
    )
    parser.add_argument(
        "--reserve-tokens",
        type=int,
        default=DEFAULT_RESERVE_TOKENS,
        help=(
            "Planning safety reserve kept unused in each part "
            f"(default: {DEFAULT_RESERVE_TOKENS})."
        ),
    )

    tokenizer_group = parser.add_mutually_exclusive_group()
    tokenizer_group.add_argument(
        "--model",
        default=None,
        help="Optional model name passed to tiktoken.encoding_for_model.",
    )
    tokenizer_group.add_argument(
        "--encoding",
        dest="encoding_name",
        default=None,
        help="Explicit tiktoken encoding name. Default: o200k_base.",
    )

    args = parser.parse_args()

    input_path = Path(args.input_directory).resolve()
    name = args.name.strip() if args.name is not None else input_path.name
    output_path = MARKDOWN_MERGE_BASE_DIR / input_path.name

    if not name:
        parser.error("Could not derive an output name from INPUT_DIRECTORY.")
    if name in {".", ".."} or "/" in name or "\\" in name:
        parser.error("--name must be a filename base, not a path.")
    if name.lower().endswith(".md"):
        parser.error("--name must not include the .md extension.")
    if args.token_limit <= 0:
        parser.error("--token-limit must be greater than zero.")
    if args.reserve_tokens < 0:
        parser.error("--reserve-tokens cannot be negative.")
    if args.reserve_tokens >= args.token_limit:
        parser.error("--reserve-tokens must be smaller than --token-limit.")

    encoding_name = args.encoding_name
    model = args.model
    if model is None and encoding_name is None:
        encoding_name = "o200k_base"

    tokenizer_name = f"encoding:{encoding_name}" if encoding_name else f"model:{model}"

    print("Markdown Merge Started")
    print()
    print(f"Input: {args.input_directory}")
    print(f"Output: {output_path}")
    print(f"Name: {name}")
    print(f"Token Limit: {args.token_limit}")
    print(f"Reserve Tokens: {args.reserve_tokens}")
    print(f"Max File Bytes: {CHATGPT_MAX_BYTES}")
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
        encoding_name=encoding_name,
    )

    print(f"Created parts: {len(parts)}")
    print()

    print("Writing output files...")
    created_files = write_parts(
        parts,
        str(output_path),
        args.input_directory,
        name,
    )

    validation = validate_output(
        created_files,
        args.token_limit,
        max_bytes=CHATGPT_MAX_BYTES,
        model=model,
        encoding_name=encoding_name,
    )

    validation_path = output_path / "validation.txt"
    validation_path.write_text(validation.report, encoding="utf-8")
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
    summary_path.write_text(summary, encoding="utf-8")
    summary_path.chmod(0o644)

    manifest = {
        "input_directory": str(Path(args.input_directory)),
        "token_limit": args.token_limit,
        "reserve_tokens": args.reserve_tokens,
        "effective_token_limit": args.token_limit - args.reserve_tokens,
        "max_file_bytes": CHATGPT_MAX_BYTES,
        "tokenizer": tokenizer_name,
        "input_files": len(files),
        "created_parts": len(created_files),
        "validation_passed": validation.passed,
        "upload_ready": validation.passed,
        "parts": [
            {
                "file": item.name,
                "tokens": item.tokens,
                "bytes": item.bytes,
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
