from __future__ import annotations

from pathlib import Path

from crawler.discovery import discover
from crawler.discovery_result import DiscoveryResult
from crawler.queue_file import print_review, read_urls_from_txt, write_seed_txt
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
        _ = queue_path.write_text(
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

                _ = queue_path.write_text(
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
