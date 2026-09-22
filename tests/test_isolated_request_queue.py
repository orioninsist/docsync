"""Regression contracts for persistent Crawlee request storage."""

from __future__ import annotations

import asyncio
from pathlib import Path

from docsync.crawler_runtime import build_crawlee_runtime


def build_runtime(storage_dir: Path):
    return asyncio.run(
        build_crawlee_runtime(
            hostname="example.com",
            storage_dir=storage_dir,
            max_concurrency=2,
            requests_per_minute=20,
            request_timeout_seconds=60,
        )
    )


def test_throttled_queue_survives_simulated_restart(tmp_path: Path) -> None:
    storage_dir = tmp_path / "crawlee"

    async def scenario() -> None:
        runtime = await build_crawlee_runtime(
            hostname="example.com",
            storage_dir=storage_dir,
            max_concurrency=1,
            requests_per_minute=20,
            request_timeout_seconds=60,
        )
        urls = [
            "https://example.com/docs/one",
            "https://example.com/docs/two",
            "https://example.com/docs/three",
        ]
        await runtime.request_manager.add_requests(urls)

        first = await runtime.request_manager.fetch_next_request()
        assert first is not None
        await runtime.request_manager.mark_request_as_handled(first)

        restarted = await build_crawlee_runtime(
            hostname="example.com",
            storage_dir=storage_dir,
            max_concurrency=1,
            requests_per_minute=20,
            request_timeout_seconds=60,
        )

        assert await restarted.request_manager.is_finished() is False
        assert await restarted.request_manager.get_total_count() == 3
        assert await restarted.request_manager.get_handled_count() == 1

        remaining = set()
        while request := await restarted.request_manager.fetch_next_request():
            remaining.add(request.url)
            await restarted.request_manager.mark_request_as_handled(request)

        assert remaining == set(urls) - {first.url}
        assert await restarted.request_manager.is_finished() is True

        await restarted.request_manager.drop()

    asyncio.run(scenario())
