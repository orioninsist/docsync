from __future__ import annotations

import argparse
import asyncio
import re
import sqlite3
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

from crawler.config import CrawlerConfig
from crawler.crawler_engine import CrawlerEngine
from crawler.discovery import discover
from crawler.discovery_result import DiscoveryResult
from crawler.queue_file import print_review, read_urls_from_txt, write_seed_txt
from crawler.runtime_paths import build_runtime_paths
from crawler.scope_prefix import (
    build_allowed_path_prefix as shared_allowed_path_prefix,
)
from crawler.source_manifest import SourceManifest
from crawler.target_resolver import resolve_target, target_is_file

SOURCES_ROOT = Path("sources")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Documentation site crawler that exports English pages to Markdown."
    )
    parser.add_argument("target")
    parser.add_argument("sites", nargs="*")
    parser.add_argument(
        "--workspace",
        help="Optional workspace name used when resolving a URL or TXT target.",
    )
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--yes", action="store_true")
    return parser.parse_args()


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"^https?://", "", value)
    value = re.sub(r"^www\.", "", value)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "site"


def is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


# Queue TXT read/write and smart review helpers live in crawler.queue_file.


def guess_default_site(workspace_name: str) -> str:
    value = workspace_name.strip()

    if is_url(value):
        return value

    if "." in value:
        return value

    return f"{value}.com"


def _add_best_result(
    target: dict[str, DiscoveryResult],
    item: DiscoveryResult,
) -> None:
    existing = target.get(item.url)

    if existing is None or item.score > existing.score:
        target[item.url] = item


def _split_discovery_results(
    *,
    accepted_map: dict[str, DiscoveryResult],
    blocked_map: dict[str, DiscoveryResult],
    review_map: dict[str, DiscoveryResult],
    limit: int,
) -> tuple[list[DiscoveryResult], list[DiscoveryResult], list[DiscoveryResult]]:
    accepted_urls = set(accepted_map)
    review_urls = set(review_map) - accepted_urls
    blocked_urls = set(blocked_map) - accepted_urls - review_urls

    accepted = sorted(
        accepted_map.values(),
        key=lambda item: (-item.score, item.url),
    )[:limit]

    review = sorted(
        (review_map[url] for url in review_urls),
        key=lambda item: (-item.score, item.url),
    )[:limit]

    blocked = sorted(
        (blocked_map[url] for url in blocked_urls),
        key=lambda item: (-item.score, item.url),
    )

    return accepted, blocked, review


async def build_smart_workspace(
    *,
    workspace_name: str,
    sites: list[str],
    limit: int,
    auto_yes: bool,
) -> tuple[list[str], str]:
    manifest = SourceManifest.from_project_name(
        project_name=workspace_name,
        root_dir=SOURCES_ROOT,
    )
    manifest.ensure_workspace()

    workspace = manifest.project_name
    txt_path = manifest.seed_file
    queue_path = manifest.allow_file

    accepted_map: dict[str, DiscoveryResult] = {}
    blocked_map: dict[str, DiscoveryResult] = {}
    review_map: dict[str, DiscoveryResult] = {}

    print()
    print("PHASE 1: Discovery only")
    print("-----------------------")
    print("No Markdown download will happen in this phase.")
    print("English + official + smart grouping filters are applied before TXT.")
    print()

    for site in sites:
        print(f"[DISCOVER] {site}", flush=True)
        one_accepted, one_blocked, one_review = await discover(
            site,
            limit=limit,
            include_review=True,
        )

        for item in one_accepted:
            _add_best_result(accepted_map, item)

        for item in one_review:
            _add_best_result(review_map, item)

        for item in one_blocked:
            _add_best_result(blocked_map, item)

    accepted, blocked, review = _split_discovery_results(
        accepted_map=accepted_map,
        blocked_map=blocked_map,
        review_map=review_map,
        limit=limit,
    )

    # Keep every blocked URL for human review.
    # They are written as commented lines at the end of the TXT.
    # Download ignores them unless the user removes '#'.
    blocked = sorted(
        blocked,
        key=lambda item: (-item.score, item.url),
    )

    write_seed_txt(
        txt_path=txt_path,
        accepted=accepted,
        review=review,
        blocked=blocked,
    )

    while True:
        print_review(
            accepted=accepted,
            blocked=blocked,
            review=review,
            txt_path=txt_path,
        )

        queue_urls = read_urls_from_txt(txt_path)
        queue_path.write_text(
            "\n".join(queue_urls).rstrip() + ("\n" if queue_urls else ""),
            encoding="utf-8",
        )

        last_mtime = txt_path.stat().st_mtime

        print(f"TXT ready: {txt_path}")
        print(f"Queue TXT ready: {queue_path}")
        print()
        print("Edit the TXT using ANY editor (VS Code, Cursor, Kate, nano, etc.).")
        print("The program watches for saved changes.")
        print()
        print("Commands:")
        print("  y = regenerate queue from latest saved TXT and start download")
        print("  r = reload/check if TXT changed")
        print("  q = cancel")
        print()

        if auto_yes:
            break

        start_download = False

        while True:
            current = txt_path.stat().st_mtime

            if current != last_mtime:
                print("✓ TXT updated on disk.")
                last_mtime = current

            answer = input("[y/r/q] > ").strip().lower()

            if answer == "r":
                current = txt_path.stat().st_mtime

                if current != last_mtime:
                    print("✓ New changes detected.")
                    last_mtime = current
                else:
                    print("No new saved changes.")

                continue

            if answer in {"y", "yes"}:
                queue_urls = read_urls_from_txt(txt_path)

                queue_path.write_text(
                    "\n".join(queue_urls).rstrip() + ("\n" if queue_urls else ""),
                    encoding="utf-8",
                )

                print(f"Queue regenerated from latest TXT ({len(queue_urls)} URLs).")
                start_download = True
                break

            if answer in {"q", "quit", "exit"}:
                raise SystemExit(0)

        if start_download:
            break

        print()
        print("Crawl cancelled. Discovery TXT was created only.")
        print(f"Edit later: {txt_path}")
        print(f"Then run: docsync docs {queue_path}")
        raise SystemExit(0)

    targets = read_urls_from_txt(queue_path)

    if not targets:
        raise SystemExit("ERROR: Queue TXT is empty.")

    print()
    print("PHASE 2: Linear TXT download")
    print("--------------------------------")
    print(f"Reading crawl roots top-to-bottom: {queue_path}")
    print("STRICT: No recursive discovery in Phase 2.")
    print("Only uncommented TXT lines will be downloaded top-to-bottom.")
    print()

    return targets, workspace


IMPORTANT_QUERY_KEYS_FOR_SLUG = {
    "segment",
    "section",
    "category",
    "topic",
    "locale",
    "lang",
    "language",
    "hl",
}


def build_query_slug(start_url: str) -> str:
    parsed = urlparse(start_url)
    parts: list[str] = []

    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        key = key.lower().strip()
        value = value.strip()

        if key in IMPORTANT_QUERY_KEYS_FOR_SLUG and value:
            parts.append(f"{key}-{value}")

    return slugify("-".join(parts)) if parts else ""


def build_project_slug(start_url: str) -> str:
    parsed = urlparse(start_url)
    domain = slugify(parsed.netloc)
    path = parsed.path.strip("/")

    if not path:
        base = domain
    else:
        base = f"{domain}-{slugify(path.replace('/', '-'))}"

    query_slug = build_query_slug(start_url)
    return f"{base}-{query_slug}" if query_slug else base


def is_github_repository_scope(start_url: str) -> bool:
    parsed = urlparse(start_url)
    host = parsed.netloc.lower().removeprefix("www.")

    if host != "github.com":
        return False

    parts = [part for part in parsed.path.strip("/").split("/") if part]

    return len(parts) >= 2


def should_allow_cross_host_discovery(start_url: str) -> bool:
    return not is_github_repository_scope(start_url)


def build_allowed_path_prefix(start_url: str) -> str:
    """Return the shared crawler path boundary for one start URL."""
    return shared_allowed_path_prefix(start_url)


def build_auto_config(start_url: str, workspace: str | None) -> CrawlerConfig:
    project_slug = build_project_slug(start_url)
    allowed_path_prefix = build_allowed_path_prefix(start_url)

    if workspace:
        output_dir = SourceManifest.from_project_name(
            project_name=workspace,
            root_dir=SOURCES_ROOT,
        ).output_dir
    else:
        output_dir = SourceManifest.from_project_name(
            project_name=project_slug,
            root_dir=SOURCES_ROOT,
        ).output_dir

    db_path, logs_dir = build_runtime_paths(project_slug, workspace)

    return CrawlerConfig(
        start_url=start_url,
        allowed_path_prefix=allowed_path_prefix,
        output_dir=output_dir,
        db_path=db_path,
        logs_dir=logs_dir,
        require_english=True,
        recursive_discovery=True,
        use_sitemap_discovery=False,
        auto_continue_until_complete=True,
        allow_official_cross_host_discovery=should_allow_cross_host_discovery(
            start_url
        ),
    )


def has_markdown_output(output_dir: Path) -> bool:
    if not output_dir.is_dir():
        return False

    return any(
        path.is_file()
        for path in output_dir.rglob("*.md")
        if "_raw" not in path.parts and "_archive" not in path.parts
    )


def crawl_db_is_complete(db_path: Path) -> bool:
    if not db_path.is_file():
        return False

    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='url_queue';"
            ).fetchone()

            if table is None:
                return False

            row = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
                    SUM(CASE WHEN status='processing' THEN 1 ELSE 0 END) AS processing,
                    SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors,
                    SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) AS done
                FROM url_queue;
                """
            ).fetchone()

            if row is None:
                return False

            return (
                int(row["pending"] or 0) == 0
                and int(row["processing"] or 0) == 0
                and int(row["errors"] or 0) == 0
                and int(row["done"] or 0) > 0
            )

    except sqlite3.Error:
        return False


def already_completed(config: CrawlerConfig) -> bool:
    return crawl_db_is_complete(config.db_path) and has_markdown_output(
        config.output_dir
    )


async def run_one(
    start_url: str,
    index: int,
    total: int,
    workspace: str | None,
    *,
    linear_download: bool = False,
) -> str:
    config = build_auto_config(start_url, workspace)

    if linear_download:
        # TXT Phase 2 behavior:
        # Each uncommented TXT line is downloaded top-to-bottom.
        # STRICT: no sitemap expansion and no recursive link discovery here.
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
        sites = args.sites
        targets, workspace = await build_smart_workspace(
            workspace_name=args.target,
            sites=sites,
            limit=args.limit,
            auto_yes=args.yes,
        )
    elif (
        not is_url(args.target)
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
        targets, resolved_workspace = resolve_target(args.target, args.workspace)
        workspace = (
            resolved_workspace
            if resolved_workspace is not None
            else args.workspace
        )

    if not targets:
        print("No URLs found.")
        return

    total = len(targets)
    processed = 0
    skipped = 0
    failed = 0
    linear_download = bool(args.sites) or not is_url(args.target)

    for index, url in enumerate(targets, start=1):
        try:
            status = await run_one(
                url,
                index,
                total,
                workspace,
                linear_download=linear_download,
            )
            if status == "processed":
                processed += 1
            else:
                skipped += 1

        except KeyboardInterrupt:
            print("Interrupted by user.")
            raise SystemExit(130)

        except SystemExit as exc:
            if exc.code == 0:
                raise
            failed += 1
            print(f"[ERROR] URL failed with exit code {exc.code}: {url}")
            print("[CONTINUE] Moving to next URL.")

        except Exception as exc:
            failed += 1
            print(f"[ERROR] crawler failed for URL: {url}", file=sys.stderr)
            print(f"[ERROR] {exc}", file=sys.stderr)
            print("[CONTINUE] Moving to next URL.")

    print()
    print("TXT Crawl Summary")
    print("-----------------")
    print(f"Total URLs: {total}")
    print(f"Processed: {processed}")
    print(f"Skipped: {skipped}")
    print(f"Failed: {failed}")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
