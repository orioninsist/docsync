"""Plain-text command line interface for DocsSync."""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from playwright.sync_api import sync_playwright

from docsync.crawler import run_crawler
from docsync.policy import default_output_dir, default_state_dir


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


def _ensure_typescript_runtime() -> None:
    root = Path(__file__).resolve().parents[2]
    engine_dir = root / "typescript"
    node_modules = engine_dir / "node_modules"

    if not node_modules.exists():
        print("docsync: preparing TypeScript dependencies...")
        subprocess.run(["npm", "ci"], cwd=engine_dir, check=True)

    print("docsync: preparing TypeScript Chromium runtime...")
    subprocess.run(
        ["npx", "playwright", "install", "chromium"],
        cwd=engine_dir,
        check=True,
    )


def _run_typescript(
    *,
    url: str,
    language: str,
    output_dir: Path | None,
    state_dir: Path | None,
    headful: bool,
) -> int:
    root = Path(__file__).resolve().parents[2]
    engine_dir = root / "typescript"
    node_modules = engine_dir / "node_modules"

    if not node_modules.exists():
        raise RuntimeError(
            "TypeScript dependencies are missing. Run 'docsync setup --engine typescript' first."
        )

    effective_output_dir = (
        (output_dir or default_output_dir(url)).expanduser().resolve()
    )
    effective_state_dir = (state_dir or default_state_dir(url)).expanduser().resolve()
    command = [
        "npm",
        "run",
        "docsync",
        "--",
        url,
        "--language",
        language,
    ]
    command += ["--output-dir", str(effective_output_dir)]
    command += ["--state-dir", str(effective_state_dir)]
    if headful:
        command.append("--headful")
    return subprocess.run(command, cwd=engine_dir, check=False).returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docsync",
        description="Synchronize rendered documentation to GFM with Crawlee.",
    )
    subparsers = parser.add_subparsers(dest="command")

    sync = subparsers.add_parser("sync", help="Synchronize one documentation tree")
    sync.add_argument("url", help="Documentation start URL")
    sync.add_argument(
        "--engine",
        choices=("python", "typescript"),
        default="python",
        help="Crawlee engine (default: python)",
    )
    sync.add_argument("--language", default="en", help="Language code (default: en)")
    sync.add_argument(
        "--output-dir",
        type=Path,
        help="Markdown output directory (default: docs/<host>/<scope-hash>)",
    )
    sync.add_argument(
        "--state-dir",
        type=Path,
        help="Manifest directory (default: storage/docsync/<host>/<scope-hash>)",
    )
    sync.add_argument(
        "--install-runtime",
        action="store_true",
        help="Install missing browser/dependencies before syncing",
    )
    sync.add_argument(
        "--headful",
        action="store_true",
        help="Run Chromium with a visible browser window",
    )

    setup = subparsers.add_parser("setup", help="Prepare local runtime dependencies")
    setup.add_argument(
        "--engine",
        choices=("python", "typescript", "all"),
        default="all",
        help="Runtime to prepare (default: all)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if raw_args and raw_args[0] not in {"sync", "setup", "-h", "--help"}:
        raw_args = ["sync", *raw_args]
    parser = build_parser()
    args = parser.parse_args(raw_args)

    if args.command == "setup":
        if args.engine in {"python", "all"}:
            _ensure_python_browser()
        if args.engine in {"typescript", "all"}:
            _ensure_typescript_runtime()
        return 0

    if args.command != "sync":
        parser.print_help()
        return 2

    if args.engine == "typescript":
        if args.install_runtime:
            _ensure_typescript_runtime()
        return _run_typescript(
            url=args.url,
            language=args.language,
            output_dir=args.output_dir,
            state_dir=args.state_dir,
            headful=args.headful,
        )

    if args.install_runtime:
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
            headful=args.headful,
        )
    )

    print(
        "done "
        f"processed={result['processed']} "
        f"saved={result['saved']} "
        f"unchanged={result['unchanged']} "
        f"output={(args.output_dir or default_output_dir(args.url)).expanduser().resolve()} "
        f"state={(args.state_dir or default_state_dir(args.url)).expanduser().resolve()}"
    )
    return 0
