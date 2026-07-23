"""Inspect robots.txt permissions for a specific URL."""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urlparse

DEFAULT_USER_AGENT = (
    "DocsMarkdownCrawler/1.0 "
    "(compatible; respectful documentation crawler)"
)
DEFAULT_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class RobotsInspection:
    """Result of one robots.txt inspection."""

    target_url: str
    robots_url: str
    user_agent: str
    allowed: bool
    crawl_delay: float | int | None
    request_rate: urllib.robotparser.RequestRate | None
    sitemaps: list[str]
    relevant_rules: list[str]


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""

    parser = argparse.ArgumentParser(
        description=(
            "Check whether a URL may be fetched according to the site's robots.txt."
        ),
    )
    parser.add_argument(
        "url",
        help="Absolute HTTP or HTTPS URL to inspect.",
    )
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help=f"User-Agent used for robots evaluation. Default: {DEFAULT_USER_AGENT}",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Network timeout in seconds. Default: {DEFAULT_TIMEOUT_SECONDS}",
    )
    parser.add_argument(
        "--show-all",
        action="store_true",
        help="Print the complete robots.txt content.",
    )
    return parser


def normalize_target_url(raw_url: str) -> str:
    """Validate and normalize an absolute HTTP or HTTPS URL."""

    target_url = raw_url.strip()
    parsed = urlparse(target_url)

    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("URL scheme must be http or https.")

    if not parsed.netloc:
        raise ValueError("URL must include a hostname.")

    return target_url


def build_robots_url(target_url: str) -> str:
    """Build the robots.txt URL for the target host."""

    parsed = urlparse(target_url)
    return f"{parsed.scheme.lower()}://{parsed.netloc}/robots.txt"


def download_robots_txt(
    robots_url: str,
    *,
    user_agent: str,
    timeout: float,
) -> str:
    """Download robots.txt and return decoded text."""

    request = urllib.request.Request(
        robots_url,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/plain,*/*;q=0.1",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status_code = response.getcode()

            if status_code != 200:
                raise RuntimeError(
                    f"robots.txt returned unexpected HTTP status: {status_code}"
                )

            return response.read().decode("utf-8", errors="replace")

    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise RuntimeError(
                f"robots.txt access was denied with HTTP {exc.code}."
            ) from exc

        if exc.code == 404:
            raise FileNotFoundError(
                "robots.txt was not found. Standard behavior allows crawling, "
                "but verify the site's terms separately."
            ) from exc

        raise RuntimeError(
            f"robots.txt request failed with HTTP {exc.code}: {exc.reason}"
        ) from exc

    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach robots.txt: {exc.reason}"
        ) from exc

    except TimeoutError as exc:
        raise RuntimeError(
            f"robots.txt request timed out after {timeout} seconds."
        ) from exc


def parse_relevant_rules(
    robots_text: str,
    *,
    user_agent: str,
) -> list[str]:
    """Return rules from groups relevant to the configured User-Agent."""

    normalized_agent = user_agent.lower()
    groups: list[tuple[list[str], list[str]]] = []
    current_agents: list[str] = []
    current_rules: list[str] = []
    reading_agents = False

    def commit_group() -> None:
        nonlocal current_agents, current_rules

        if current_agents:
            groups.append((current_agents, current_rules))

        current_agents = []
        current_rules = []

    for raw_line in robots_text.splitlines():
        line = raw_line.split("#", 1)[0].strip()

        if not line or ":" not in line:
            continue

        field, value = line.split(":", 1)
        field = field.strip().lower()
        value = value.strip()

        if field == "user-agent":
            if current_rules:
                commit_group()

            current_agents.append(value.lower())
            reading_agents = True
            continue

        if field in {"allow", "disallow", "crawl-delay"}:
            if not current_agents:
                continue

            reading_agents = False
            current_rules.append(f"{field.title()}: {value}")
            continue

        if field == "sitemap":
            continue

        if not reading_agents and current_agents:
            continue

    commit_group()

    exact_rules: list[str] = []
    wildcard_rules: list[str] = []

    for agents, rules in groups:
        if any(
            agent != "*" and agent in normalized_agent
            for agent in agents
        ):
            exact_rules.extend(rules)

        if "*" in agents:
            wildcard_rules.extend(rules)

    selected_rules = exact_rules if exact_rules else wildcard_rules
    return list(dict.fromkeys(selected_rules))


def inspect_robots(
    target_url: str,
    *,
    user_agent: str,
    timeout: float,
) -> tuple[RobotsInspection, str]:
    """Download, parse, and evaluate robots.txt."""

    robots_url = build_robots_url(target_url)
    robots_text = download_robots_txt(
        robots_url,
        user_agent=user_agent,
        timeout=timeout,
    )

    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)
    parser.parse(robots_text.splitlines())

    inspection = RobotsInspection(
        target_url=target_url,
        robots_url=robots_url,
        user_agent=user_agent,
        allowed=parser.can_fetch(user_agent, target_url),
        crawl_delay=parser.crawl_delay(user_agent),
        request_rate=parser.request_rate(user_agent),
        sitemaps=parser.site_maps() or [],
        relevant_rules=parse_relevant_rules(
            robots_text,
            user_agent=user_agent,
        ),
    )

    return inspection, robots_text


def print_inspection(inspection: RobotsInspection) -> None:
    """Print a readable robots.txt inspection report."""

    status = "ALLOWED" if inspection.allowed else "BLOCKED"
    symbol = "YES" if inspection.allowed else "NO"

    print("=" * 80)
    print("ROBOTS CHECK")
    print("=" * 80)
    print(f"Target URL : {inspection.target_url}")
    print(f"Robots URL : {inspection.robots_url}")
    print(f"User-Agent : {inspection.user_agent}")
    print(f"Can fetch  : {symbol}")
    print(f"Status     : {status}")

    if inspection.crawl_delay is None:
        print("Crawl delay: Not specified")
    else:
        print(f"Crawl delay: {inspection.crawl_delay} seconds")

    if inspection.request_rate is None:
        print("Request rate: Not specified")
    else:
        print(
            "Request rate: "
            f"{inspection.request_rate.requests} requests / "
            f"{inspection.request_rate.seconds} seconds"
        )

    print()
    print("Relevant rules")
    print("--------------")

    if inspection.relevant_rules:
        for rule in inspection.relevant_rules:
            print(rule)
    else:
        print("No explicit Allow, Disallow, or Crawl-delay rule found.")

    print()
    print("Sitemaps")
    print("--------")

    if inspection.sitemaps:
        for sitemap_url in inspection.sitemaps:
            print(sitemap_url)
    else:
        print("No sitemap declared.")

    print()
    print("RESULT")
    print("------")

    if inspection.allowed:
        print("SUCCESS: robots.txt permits this URL for the selected User-Agent.")
    else:
        print("BLOCKED: robots.txt does not permit this URL.")
        print("Use git clone, an official API, or another permitted source.")
        print("Do not bypass the robots.txt restriction.")


def main() -> int:
    """Run the command-line application."""

    parser = build_parser()
    args = parser.parse_args()

    try:
        target_url = normalize_target_url(args.url)
        inspection, robots_text = inspect_robots(
            target_url,
            user_agent=args.user_agent,
            timeout=args.timeout,
        )

        print_inspection(inspection)

        if args.show_all:
            print()
            print("Complete robots.txt")
            print("-------------------")
            print(robots_text.rstrip())

        return 0 if inspection.allowed else 2

    except FileNotFoundError as exc:
        print(f"WARNING: {exc}", file=sys.stderr)
        print(
            "RESULT: robots.txt is absent; crawling is generally allowed "
            "by the robots protocol.",
        )
        return 0

    except ValueError as exc:
        print(f"ERROR: Invalid input: {exc}", file=sys.stderr)
        return 2

    except KeyboardInterrupt:
        print("\nERROR: Operation interrupted by user.", file=sys.stderr)
        return 130

    except Exception as exc:
        print(
            f"ERROR: Robots inspection failed: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
