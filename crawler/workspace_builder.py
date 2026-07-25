from __future__ import annotations

from pathlib import Path

from crawler.discovery import discover
from crawler.discovery_result import DiscoveryResult
from crawler.queue_file import print_review, read_urls_from_txt, write_review_txt
from crawler.source_manifest import SourceManifest

SOURCES_ROOT = Path("sources")


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


def _read_review_queue(review_path: Path) -> list[str]:
    queue_urls = read_urls_from_txt(review_path)

    if not queue_urls:
        raise SystemExit("ERROR: Review TXT contains no enabled URLs.")

    return queue_urls


def _print_review_instructions(review_path: Path) -> None:
    print(f"Review TXT ready: {review_path}")
    print()
    print("Edit the TXT using ANY editor (VS Code, Cursor, Kate, nano, etc.).")
    print("The program watches for saved changes.")
    print()
    print("Commands:")
    print("  y = read the latest saved TXT and start download")
    print("  r = reload/check if TXT changed")
    print("  q = cancel")
    print()


def _wait_for_review_confirmation(
    *,
    review_path: Path,
    auto_yes: bool,
) -> list[str]:
    if auto_yes:
        return _read_review_queue(review_path)

    last_mtime = review_path.stat().st_mtime

    while True:
        current_mtime = review_path.stat().st_mtime

        if current_mtime != last_mtime:
            print("✓ TXT updated on disk.")
            last_mtime = current_mtime

        answer = input("[y/r/q] > ").strip().lower()

        if answer == "r":
            current_mtime = review_path.stat().st_mtime

            if current_mtime != last_mtime:
                print("✓ New changes detected.")
                last_mtime = current_mtime
            else:
                print("No new saved changes.")

            continue

        if answer in {"y", "yes"}:
            queue_urls = _read_review_queue(review_path)
            print(f"Queue loaded from latest TXT ({len(queue_urls)} URLs).")
            return queue_urls

        if answer in {"q", "quit", "exit"}:
            print()
            print("Crawl cancelled. Discovery review TXT was created only.")
            print(f"Edit later: {review_path}")
            print(f"Then run: docsync docs {review_path}")
            raise SystemExit(0)


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

    write_review_txt(
        txt_path=manifest.review_file,
        accepted=accepted,
        review=review,
        blocked=blocked,
    )

    print_review(
        accepted=accepted,
        blocked=blocked,
        review=review,
        txt_path=manifest.review_file,
    )
    _print_review_instructions(manifest.review_file)

    targets = _wait_for_review_confirmation(
        review_path=manifest.review_file,
        auto_yes=auto_yes,
    )

    print()
    print("PHASE 2: Linear in-memory queue download")
    print("-----------------------------------------")
    print(f"Reading crawl roots top-to-bottom: {manifest.review_file}")
    print("STRICT: No recursive discovery in Phase 2.")
    print("Only uncommented TXT lines are held in the runtime queue.")
    print()

    return targets, manifest.project_name
