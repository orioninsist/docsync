"""Benchmark repeated DocsSync Playwright fallback startup cost.

This is intentionally opt-in and is not part of the normal test suite. It measures
wall-clock cost of repeated calls to the production render_url_with_crawlee()
fallback so browser startup/lifecycle overhead can be measured before changing
behavior.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import asdict, dataclass

from docsync.playwright_rendering import render_url_with_crawlee


@dataclass(frozen=True, slots=True)
class Sample:
    iteration: int
    seconds: float
    html_bytes: int
    links: int


async def _run(*, url: str, iterations: int, browser_type: str) -> list[Sample]:
    samples: list[Sample] = []

    for iteration in range(1, iterations + 1):
        started = time.perf_counter()
        try:
            html, links = await render_url_with_crawlee(
                url,
                headless=True,
                browser_type=browser_type,
                request_timeout_seconds=60,
            )
        except RuntimeError as error:
            elapsed = time.perf_counter() - started
            raise RuntimeError(
                "Browser fallback benchmark could not complete repeated "
                f"production calls: iteration={iteration} elapsed={elapsed:.3f}s "
                f"url={url}. The production fallback is currently not reusable "
                "across sequential invocations in this process."
            ) from error

        samples.append(
            Sample(
                iteration=iteration,
                seconds=time.perf_counter() - started,
                html_bytes=len(html.encode("utf-8")),
                links=len(links),
            )
        )

    return samples


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument(
        "--browser-type",
        choices=("chromium", "firefox", "webkit"),
        default="chromium",
    )
    args = parser.parse_args()

    if args.iterations <= 0:
        parser.error("--iterations must be greater than zero")

    samples = asyncio.run(
        _run(
            url=args.url,
            iterations=args.iterations,
            browser_type=args.browser_type,
        )
    )
    durations = [sample.seconds for sample in samples]
    payload = {
        "mode": "production-per-call-crawler",
        "url": args.url,
        "browser_type": args.browser_type,
        "iterations": args.iterations,
        "total_seconds": sum(durations),
        "mean_seconds": statistics.fmean(durations),
        "median_seconds": statistics.median(durations),
        "min_seconds": min(durations),
        "max_seconds": max(durations),
        "samples": [asdict(sample) for sample in samples],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
