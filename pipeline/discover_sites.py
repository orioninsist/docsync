#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import re
import sys

from pipeline.paths import OUTPUT_ROOT, PROJECT_ROOT

# ----------------------------------------------------------
# Make project root importable regardless of where executed
# ----------------------------------------------------------
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from crawler.discovery import discover  # noqa: E402


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"^https?://", "", value)
    value = re.sub(r"^www\.", "", value)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "site"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Discover useful documentation/help/blog seed URLs."
    )
    parser.add_argument("site")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--workspace", default=None)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    workspace = args.workspace or f"discovered-{slugify(args.site)}"

    output_dir = OUTPUT_ROOT / workspace
    output_dir.mkdir(parents=True, exist_ok=True)

    accepted_results, blocked_results, review_results = await discover(
        args.site,
        limit=args.limit,
    )

    txt_file = output_dir / "sites.txt"

    with txt_file.open("w", encoding="utf-8") as file:
        for item in accepted_results:
            file.write(item.url + "\n")

    print()
    print("Smart Discovery Summary")
    print("-----------------------")
    print(f"Site      : {args.site}")
    print(f"Workspace : {workspace}")
    print(f"Accepted  : {len(accepted_results)}")
    print(f"Review    : {len(review_results)}")
    print(f"Blocked   : {len(blocked_results)}")
    print(f"Saved     : {txt_file}")
    print()

    for item in accepted_results:
        print(f"{item.score:>3}  {item.url}")

    print()
    print("Next:")
    print(f"docsync docs {txt_file}")


if __name__ == "__main__":
    asyncio.run(main())
