"""Regression tests for robots.txt navigation timing."""

import asyncio
import time
from itertools import pairwise

from docsync.crawler import NavigationDelayGuard


async def _test_concurrent_navigation_starts_are_spaced() -> None:
    guard = NavigationDelayGuard()
    url = "https://example.com/docs"
    guard.set_delay(url, 0.15)

    async def navigate() -> float:
        await guard.wait(url)
        return time.monotonic()

    starts = sorted(await asyncio.gather(*(navigate() for _ in range(3))))
    intervals = [later - earlier for earlier, later in pairwise(starts)]

    assert all(interval >= 0.13 for interval in intervals)


async def _test_different_origins_are_independent() -> None:
    guard = NavigationDelayGuard()
    first = "https://example.com/docs"
    second = "https://other.example.com/docs"

    guard.set_delay(first, 0.2)
    guard.set_delay(second, 0.2)

    await guard.wait(first)
    start = time.monotonic()
    await guard.wait(second)

    assert time.monotonic() - start < 0.1


async def _test_no_crawl_delay_does_not_wait() -> None:
    guard = NavigationDelayGuard()

    start = time.monotonic()
    await guard.wait("https://example.com/docs")

    assert time.monotonic() - start < 0.1


async def _test_same_origin_different_paths_share_delay() -> None:
    guard = NavigationDelayGuard()
    guard.set_delay("https://example.com/first", 0.15)

    await guard.wait("https://example.com/first")
    start = time.monotonic()
    await guard.wait("https://example.com/second")

    assert time.monotonic() - start >= 0.13


def test_concurrent_navigation_starts_are_spaced() -> None:
    asyncio.run(_test_concurrent_navigation_starts_are_spaced())


def test_different_origins_are_independent() -> None:
    asyncio.run(_test_different_origins_are_independent())


def test_no_crawl_delay_does_not_wait() -> None:
    asyncio.run(_test_no_crawl_delay_does_not_wait())


def test_same_origin_different_paths_share_delay() -> None:
    asyncio.run(_test_same_origin_different_paths_share_delay())
