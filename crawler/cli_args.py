from __future__ import annotations

import argparse
from dataclasses import dataclass


class CliNamespace(argparse.Namespace):
    target: str = ""
    sites: list[str] = []
    workspace: str | None = None
    limit: int = 80
    yes: bool = False


@dataclass(frozen=True, slots=True)
class CliArgs:
    target: str
    sites: list[str]
    workspace: str | None
    limit: int
    yes: bool


def parse_args() -> CliArgs:
    parser = argparse.ArgumentParser(
        description=(
            "Documentation site crawler that exports English pages to Markdown."
        )
    )
    _ = parser.add_argument("target")
    _ = parser.add_argument("sites", nargs="*")
    _ = parser.add_argument(
        "--workspace",
        help="Optional workspace name used when resolving a URL or TXT target.",
    )
    _ = parser.add_argument("--limit", type=int, default=80)
    _ = parser.add_argument("--yes", action="store_true")

    namespace = parser.parse_args(namespace=CliNamespace())

    return CliArgs(
        target=namespace.target,
        sites=namespace.sites,
        workspace=namespace.workspace,
        limit=namespace.limit,
        yes=namespace.yes,
    )
