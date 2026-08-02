"""Behavioral tests for Crawlee ThrottlingRequestManager."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from crawlee.request_loaders import ThrottlingRequestManager


class FakeRequestManager:
    def __init__(self) -> None:
        self.requests: list[str] = []
        self.handled: list[str] = []

    async def add_request(
        self,
        request: str,
        *,
        forefront: bool = False,
    ) -> None:
        if forefront:
            self.requests.insert(0, request)
        else:
            self.requests.append(request)

    async def add_requests(
        self,
        requests: list[str],
        **kwargs: Any,
    ) -> None:
        self.requests.extend(requests)

    async def fetch_next_request(self) -> None:
        return None

    async def reclaim_request(
        self,
        request: Any,
        *,
        forefront: bool = False,
    ) -> None:
        return None

    async def mark_request_as_handled(
        self,
        request: Any,
    ) -> None:
        self.handled.append(request.url)

    async def get_handled_count(self) -> int:
        return len(self.handled)

    async def get_total_count(self) -> int:
        return len(self.requests)

    async def is_empty(self) -> bool:
        return not self.requests

    async def is_finished(self) -> bool:
        return not self.requests

    async def drop(self) -> None:
        self.requests.clear()

    async def purge(self) -> None:
        self.requests.clear()


async def fake_opener(**kwargs: Any) -> FakeRequestManager:
    return FakeRequestManager()


def test_configured_domain_uses_sub_manager() -> None:
    async def run_test() -> None:
        inner = FakeRequestManager()

        manager = ThrottlingRequestManager(
            inner=inner,
            domains=["example.com"],
            request_manager_opener=fake_opener,
        )

        await manager.add_request(
            "https://example.com/docs",
        )

        assert inner.requests == []
        assert "example.com" in manager._sub_managers
        assert manager._sub_managers["example.com"].requests == [
            "https://example.com/docs",
        ]

    asyncio.run(run_test())


def test_unconfigured_domain_uses_inner_manager() -> None:
    async def run_test() -> None:
        inner = FakeRequestManager()

        manager = ThrottlingRequestManager(
            inner=inner,
            domains=["example.com"],
            request_manager_opener=fake_opener,
        )

        await manager.add_request(
            "https://other.example/docs",
        )

        assert inner.requests == [
            "https://other.example/docs",
        ]

    asyncio.run(run_test())


def test_robots_crawl_delay_is_recorded() -> None:
    manager = ThrottlingRequestManager(
        inner=FakeRequestManager(),
        domains=["example.com"],
        request_manager_opener=fake_opener,
    )

    manager.set_crawl_delay(
        "https://example.com/docs",
        7,
    )

    state = manager._domain_states["example.com"]

    assert state.crawl_delay == timedelta(seconds=7)


def test_robots_crawl_delay_is_locked_after_first_value() -> None:
    manager = ThrottlingRequestManager(
        inner=FakeRequestManager(),
        domains=["example.com"],
        request_manager_opener=fake_opener,
    )

    manager.set_crawl_delay(
        "https://example.com/docs",
        7,
    )

    manager.set_crawl_delay(
        "https://example.com/docs",
        20,
    )

    state = manager._domain_states["example.com"]

    assert state.crawl_delay == timedelta(seconds=7)


def test_429_backoff_is_recorded() -> None:
    manager = ThrottlingRequestManager(
        inner=FakeRequestManager(),
        domains=["example.com"],
        request_manager_opener=fake_opener,
        base_delay=timedelta(seconds=2),
        max_delay=timedelta(seconds=60),
    )

    applied = manager.record_domain_delay(
        "https://example.com/docs",
    )

    state = manager._domain_states["example.com"]

    assert applied is True
    assert state.consecutive_429_count == 1
    assert state.throttled_until.year > 1


def test_retry_after_takes_priority_for_429() -> None:
    manager = ThrottlingRequestManager(
        inner=FakeRequestManager(),
        domains=["example.com"],
        request_manager_opener=fake_opener,
        base_delay=timedelta(seconds=2),
        max_delay=timedelta(seconds=60),
    )

    before = manager._domain_states["example.com"].throttled_until

    applied = manager.record_domain_delay(
        "https://example.com/docs",
        retry_after=timedelta(seconds=15),
    )

    after = manager._domain_states["example.com"].throttled_until

    assert applied is True
    assert after > before


def test_429_backoff_is_capped() -> None:
    manager = ThrottlingRequestManager(
        inner=FakeRequestManager(),
        domains=["example.com"],
        request_manager_opener=fake_opener,
        base_delay=timedelta(seconds=20),
        max_delay=timedelta(seconds=30),
    )

    manager.record_domain_delay(
        "https://example.com/docs",
    )

    manager.record_domain_delay(
        "https://example.com/docs",
    )

    state = manager._domain_states["example.com"]

    assert state.consecutive_429_count == 2
    assert state.throttled_until.year > 1


def test_success_resets_429_counter() -> None:
    manager = ThrottlingRequestManager(
        inner=FakeRequestManager(),
        domains=["example.com"],
        request_manager_opener=fake_opener,
    )

    manager.record_domain_delay(
        "https://example.com/docs",
    )

    manager.record_success(
        "https://example.com/docs",
    )

    state = manager._domain_states["example.com"]

    assert state.consecutive_429_count == 0


def test_unconfigured_domain_ignores_429_backoff() -> None:
    manager = ThrottlingRequestManager(
        inner=FakeRequestManager(),
        domains=["example.com"],
        request_manager_opener=fake_opener,
    )

    assert (
        manager.record_domain_delay(
            "https://other.example/docs",
        )
        is False
    )
