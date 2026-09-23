"""Plain-text command line interface for DocsSync."""

from __future__ import annotations

import argparse
import asyncio
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from playwright.sync_api import sync_playwright

from docsync.crawler import run_crawler


def _ensure_pandoc() -> None:
    if shutil.which("pandoc") is None:
        raise RuntimeError("pandoc is required and was not found in PATH")


def _ensure_python_browser() -> None:
    with sync_playwright() as playwright:
        executable = Path(playwright.chromium.executable_path)
    if executable.exists():
        return

    print("docsync: preparing Python Chromium runtime (first run only)...")
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=True,
    )


def _run_typescript(
    *,
    url: str,
    language: str,
    output_dir: Path,
    state_dir: Path,
) -> int:
    root = Path(__file__).resolve().parents[2]
    engine_dir = root / "typescript"
    node_modules = engine_dir / "node_modules"

    if not node_modules.exists():
        print("docsync: preparing TypeScript dependencies (first run only)...")
        subprocess.run(["npm", "install"], cwd=engine_dir, check=True)
        subprocess.run(
            ["npx", "playwright", "install", "chromium"],
            cwd=engine_dir,
            check=True,
        )

    command = [
        "npm",
        "run",
        "docsync",
        "--",
        url,
        "--language",
        language,
        "--output-dir",
        str(output_dir),
        "--state-dir",
        str(state_dir),
    ]
    return subprocess.run(command, cwd=engine_dir, check=False).returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docsync",
        description="Synchronize documentation to GFM with Crawlee and Pandoc.",
    )
    parser.add_argument("url", help="Documentation start URL")
    parser.add_argument(
        "--engine",
        choices=("python", "typescript"),
        default="python",
        help="Crawlee engine (default: python)",
    )
    parser.add_argument("--language", default="en", help="Language code (default: en)")
    parser.add_argument("--output-dir", type=Path, default=Path("docs"))
    parser.add_argument("--state-dir", type=Path, default=Path("storage/docsync"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _ensure_pandoc()

    if args.engine == "typescript":
        return _run_typescript(
            url=args.url,
            language=args.language,
            output_dir=args.output_dir,
            state_dir=args.state_dir,
        )

    _ensure_python_browser()
    result = asyncio.run(
        run_crawler(
            start_url=args.url,
            output_dir=args.output_dir,
            state_dir=args.state_dir,
            language=args.language,
            max_concurrency=2,
            max_requests=10_000,
            requests_per_minute=20,
        )
    )

    print(
        "done "
        f"processed={result['processed']} "
        f"saved={result['saved']} "
        f"unchanged={result['unchanged']} "
        f"output={args.output_dir.expanduser().resolve()} "
        f"state={args.state_dir.expanduser().resolve()}"
    )
    return 0
