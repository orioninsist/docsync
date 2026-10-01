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
from docsync.sources import get_source_adapter


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
    restart: bool,
    max_requests: int | None,
    crawl_strategy: str,
    discover_sitemap: bool,
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
    effective_output_dir.mkdir(parents=True, exist_ok=True)
    effective_state_dir.mkdir(parents=True, exist_ok=True)
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
    if restart:
        command.append("--restart")
    if max_requests is not None:
        command += ["--max-requests", str(max_requests)]
    command += ["--crawl-strategy", crawl_strategy]
    if not discover_sitemap:
        command.append("--no-sitemap")
    return subprocess.run(command, cwd=engine_dir, check=False).returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docsync",
        description="Synchronize documentation to GFM from the web or an official source adapter.",
    )
    subparsers = parser.add_subparsers(dest="command")

    sync = subparsers.add_parser(\n        "sync", help="Synchronize one documentation tree from a selected source"\n    )
    sync.add_argument("url", help="Documentation start URL")
    sync.add_argument(
        "--source",
        choices=("web", "phaser"),
        default="web",
        help="Documentation source: web uses Crawlee; phaser uses official Phaser source JSDoc (default: web)",
    )
    sync.add_argument(
        "--engine",
        choices=("python", "typescript"),
        default="python",
        help="Crawlee engine used when --source web is selected (default: python)",
    )
    sync.add_argument(\n        "--language", default="en", help="Page language for web crawling (default: en)"\n    )
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
        help="Run Chromium with a visible browser window when --source web is selected",
    )
    sync.add_argument(
        "--max-requests",
        type=int,
        help="Optional crawl request limit; omitted means no request-count limit",
    )
    sync.add_argument(
        "--crawl-strategy",
        choices=("same-origin", "same-hostname", "same-domain"),
        default="same-origin",
        help="Crawlee link scope strategy (default: same-origin)",
    )
    sync.add_argument(
        "--no-sitemap",
        action="store_true",
        help="Disable automatic sitemap seeding",
    )
    sync.add_argument(
        "--restart",
        action="store_true",
        help="Discard resumable web-crawl progress and start a fresh crawl",
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

    effective_output_dir = (
        (args.output_dir or default_output_dir(args.url)).expanduser().resolve()
    )
    effective_state_dir = (
        (args.state_dir or default_state_dir(args.url)).expanduser().resolve()
    )
    effective_output_dir.mkdir(parents=True, exist_ok=True)
    effective_state_dir.mkdir(parents=True, exist_ok=True)

    if args.source != "web":
        result = get_source_adapter(args.source).sync(
            output_dir=effective_output_dir,
            state_dir=effective_state_dir,
        )
        print(
            "done "
            f"source={args.source} "
            f"processed={result['processed']} "
            f"saved={result['saved']} "
            f"unchanged={result['unchanged']} "
            f"output={effective_output_dir} "
            f"state={effective_state_dir}"
        )
        return 0

    if args.engine == "typescript":
        if args.install_runtime:
            _ensure_typescript_runtime()
        return _run_typescript(
            url=args.url,
            language=args.language,
            output_dir=effective_output_dir,
            state_dir=effective_state_dir,
            headful=args.headful,
            restart=args.restart,
            max_requests=args.max_requests,
            crawl_strategy=args.crawl_strategy,
            discover_sitemap=not args.no_sitemap,
        )

    if args.install_runtime:
        _ensure_python_browser()
    result = asyncio.run(
        run_crawler(
            start_url=args.url,
            output_dir=effective_output_dir,
            state_dir=effective_state_dir,
            language=args.language,
            max_concurrency=2,
            max_requests=args.max_requests,
            requests_per_minute=20,
            crawl_strategy=args.crawl_strategy,
            discover_sitemap=not args.no_sitemap,
            headful=args.headful,
            restart=args.restart,
        )
    )

    print(
        "done "
        f"processed={result['processed']} "
        f"saved={result['saved']} "
        f"unchanged={result['unchanged']} "
        f"output={effective_output_dir} "
        f"state={effective_state_dir}"
    )
    return 0
