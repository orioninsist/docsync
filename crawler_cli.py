from __future__ import annotations

import asyncio
from pathlib import Path

from crawler.cli_args import parse_args
from crawler.config_factory import build_auto_config
from crawler.crawl_state import already_completed
from crawler.crawler_engine import CrawlerEngine
from crawler.preflight import run_project_preflight
from crawler.runtime_paths import build_run_id
from crawler.source_manifest import SourceManifest
from crawler.target_resolver import resolve_target, target_is_file
from crawler.url_utils import guess_default_site, is_url
from crawler.workspace_builder import build_smart_workspace

SOURCES_ROOT = Path("sources")


async def run_one(
    start_url: str,
    index: int,
    total: int,
    workspace: str | None,
    run_id: str,
    *,
    linear_download: bool = False,
) -> str:
    config = build_auto_config(start_url, workspace, run_id)

    if linear_download:
        object.__setattr__(config, "recursive_discovery", False)
        object.__setattr__(config, "use_sitemap_discovery", False)
        object.__setattr__(config, "auto_continue_until_complete", True)

    print()
    print(f"[{index}/{total}] Auto Config")
    print("-------------------")

    if workspace:
        print(f"Workspace: {workspace}")

    print(f"Start URL: {config.start_url}")
    print(f"Allowed path: {config.allowed_path_prefix}")
    print(f"Output dir: {config.output_dir}")
    print(f"Database: {config.db_path}")
    print(f"Logs: {config.logs_dir}")
    print()

    if already_completed(config):
        print("[INFO] Existing completed crawl found. Rechecking for updates.")

    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.db_path.parent.mkdir(parents=True, exist_ok=True)
    config.logs_dir.mkdir(parents=True, exist_ok=True)

    engine = CrawlerEngine(config)
    await engine.run()

    return "processed"


async def main() -> None:
    args = parse_args()
    run_id = build_run_id()
    workspace: str | None

    target_is_url = is_url(args.target)
    target_is_file_flag = target_is_file(args.target)
    target_is_existing_workspace = (
        not target_is_url
        and not target_is_file_flag
        and SourceManifest.from_project_name(
            project_name=args.target,
            root_dir=SOURCES_ROOT,
        ).output_dir.is_dir()
    )

    if args.sites:
        targets, workspace = await build_smart_workspace(
            workspace_name=args.target,
            sites=args.sites,
            limit=args.limit,
            auto_yes=args.yes,
        )
    elif (
        not target_is_url
        and not target_is_file_flag
        and not target_is_existing_workspace
    ):
        sites = [guess_default_site(args.target)]
        targets, workspace = await build_smart_workspace(
            workspace_name=args.target,
            sites=sites,
            limit=args.limit,
            auto_yes=args.yes,
        )
    else:
        targets, resolved_workspace = resolve_target(
            args.target,
            args.workspace,
        )
        workspace = (
            resolved_workspace if resolved_workspace is not None else args.workspace
        )

    if not targets:
        print("No URLs found.")
        return

    total = len(targets)
    processed = 0
    skipped = 0
    linear_download = bool(args.sites) or not target_is_url

    for index, url in enumerate(targets, start=1):
        status = await run_one(
            url,
            index,
            total,
            workspace,
            run_id,
            linear_download=linear_download,
        )

        if status == "processed":
            processed += 1
        else:
            skipped += 1

    print()
    print("TXT Crawl Summary")
    print("-----------------")
    print(f"Total URLs: {total}")
    print(f"Processed: {processed}")
    print(f"Skipped: {skipped}")


if __name__ == "__main__":
    run_project_preflight()
    asyncio.run(main())
