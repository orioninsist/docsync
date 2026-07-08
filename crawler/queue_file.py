from __future__ import annotations

import os
import subprocess  # nosec B404
from pathlib import Path
from shutil import which
from urllib.parse import urlparse

from crawler.discovery import DiscoveryResult

_ALLOWED_EDITORS = frozenset(
    {
        "nano",
        "vim",
        "vi",
        "nvim",
        "emacs",
        "micro",
        "gedit",
        "kate",
        "code",
    }
)


def read_urls_from_txt(path: Path) -> list[str]:
    urls: list[str] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line or line.startswith("#"):
            continue

        urls.append(line)

    return urls


def _resolve_editor_command() -> str:
    editor = os.environ.get("EDITOR") or "nano"
    editor_name = Path(editor).name

    if editor_name not in _ALLOWED_EDITORS:
        return "nano"

    resolved_editor = which(editor_name)
    if resolved_editor is None:
        return "nano"

    return resolved_editor


def open_editor(path: Path) -> None:
    editor = _resolve_editor_command()
    subprocess.run([editor, str(path)], check=False)  # nosec B603


def smart_group_key(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    parts = [part for part in parsed.path.strip("/").split("/") if part]

    if parts:
        first = parts[0].lower()
        if first in {"docs", "documentation", "doc"}:
            return host, "docs"
        if first in {"api", "reference"}:
            return host, "api-reference"
        if first in {"developers", "developer"}:
            return host, "developers"
        if first in {"help", "support"}:
            return host, "help-support"
        if first in {"learn", "guides", "guide", "tutorial", "tutorials"}:
            return host, "learn-guides"
        return host, first

    return host, "root"


def smart_group_title(host: str, group: str) -> str:
    return f"{host} / {group}"


def smart_sort_key(item: DiscoveryResult) -> tuple[int, int, str, str]:
    host, group = smart_group_key(item.url)

    group_rank = {
        "docs": 0,
        "api-reference": 1,
        "developers": 2,
        "help-support": 3,
        "learn-guides": 4,
        "blog": 5,
        "news": 6,
        "root": 7,
    }.get(group, 50)

    return -item.score, group_rank, host, item.url


def write_seed_txt(
    *,
    txt_path: Path,
    accepted: list[DiscoveryResult],
    review: list[DiscoveryResult],
    blocked: list[DiscoveryResult] | None = None,
) -> None:
    seen: set[str] = set()
    grouped: dict[tuple[str, str], list[DiscoveryResult]] = {}

    for item in sorted(accepted + review, key=smart_sort_key):
        if item.url in seen:
            continue
        seen.add(item.url)
        key = smart_group_key(item.url)
        grouped.setdefault(key, []).append(item)

    with txt_path.open("w", encoding="utf-8") as file:
        file.write("# DOCSYNC STRICT SMART QUEUE - PHASE 1 DISCOVERY OUTPUT\n")
        file.write("# This file is for human review before download.\n")
        file.write("# Keep URL lines you want to download.\n")
        file.write("# Delete unwanted URLs or comment them with '#'.\n")
        file.write("# Download order is top-to-bottom after you press 'y'.\n")
        file.write("# Phase 2 reads only uncommented URL lines from this TXT.\n")
        file.write("\n")

        for group_name, items in grouped.items():
            host, group = group_name
            file.write(f"# GROUP: {smart_group_title(host, group)}\n")
            file.write("# ----------------------------------------\n")
            for item in items:
                file.write(f"{item.url}\n")
            file.write("\n")

        blocked_items = blocked or []
        if blocked_items:
            file.write("# BLOCKED CANDIDATES - disabled by default\n")
            file.write("# Remove '# ' from a URL line if you want to include it.\n")
            file.write("# -------------------------------------------------------\n")
            for item in blocked_items[:250]:
                file.write(
                    f"# {item.url}    # reason: {item.reason} score={item.score}\n"
                )


def print_review(
    *,
    accepted: list[DiscoveryResult],
    blocked: list[DiscoveryResult],
    review: list[DiscoveryResult],
    txt_path: Path,
) -> None:
    print()
    print("Smart Site Analysis")
    print("===================")
    print(f"Seed txt: {txt_path}")
    print()

    print("ACCEPTED - written to txt")
    print("-------------------------")
    if accepted:
        for index, item in enumerate(accepted, start=1):
            print(f"{index:02d}. score={item.score:<3} {item.url}")
            print(f"    reason: {item.reason}")
    else:
        print("None")

    print()
    print("REVIEW - also written to txt")
    print("----------------------------")
    if review:
        for index, item in enumerate(review[:80], start=1):
            print(f"{index:02d}. score={item.score:<3} {item.url}")
            print(f"    reason: {item.reason}")
    else:
        print("None")

    print()
    print("BLOCKED - ignored by smart rules")
    print("--------------------------------")
    if blocked:
        for index, item in enumerate(blocked[:80], start=1):
            print(f"{index:02d}. {item.url}")
            print(f"    reason: {item.reason}")
    else:
        print("None")

    print()
