"""Behavioral tests for deterministic crawl-delay throttling."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from docsync.crawl_delay import CrawlDelayThrottle


@dataclass(slots=True)
class FakeTime:
    """Controllable monotonic clock and asynchronous sleeper."""

    current: float = 0.0
    sleeps: list[float] = field(default_factory=list)

    def monotonic(self) -> float:
        """Return the controlled monotonic timestamp."""

        return self.current

    async def sleep(self, seconds: float) -> None:
        """Record and advance through an asynchronous sleep."""

        assert seconds >= 0
        self.sleeps.append(seconds)
        self.current += seconds


def test_first_request_starts_immediately() -> None:
    async def scenario() -> None:
        fake_time = FakeTime(current=10.0)
        throttle = CrawlDelayThrottle(
            delay_seconds=2.5,
            clock=fake_time.monotonic,
            sleep=fake_time.sleep,
        )

        await throttle.wait()

        assert fake_time.sleeps == []
        assert throttle.last_started_at == pytest.approx(10.0)

    asyncio.run(scenario())


def test_second_request_waits_for_remaining_delay() -> None:
    async def scenario() -> None:
        fake_time = FakeTime(current=10.0)
        throttle = CrawlDelayThrottle(
            delay_seconds=3.0,
            clock=fake_time.monotonic,
            sleep=fake_time.sleep,
        )

        await throttle.wait()
        fake_time.current = 11.25
        await throttle.wait()

        assert fake_time.sleeps == [pytest.approx(1.75)]
        assert throttle.last_started_at == pytest.approx(13.0)

    asyncio.run(scenario())


def test_elapsed_delay_does_not_sleep() -> None:
    async def scenario() -> None:
        fake_time = FakeTime(current=5.0)
        throttle = CrawlDelayThrottle(
            delay_seconds=2.0,
            clock=fake_time.monotonic,
            sleep=fake_time.sleep,
        )

        await throttle.wait()
        fake_time.current = 8.0
        await throttle.wait()

        assert fake_time.sleeps == []
        assert throttle.last_started_at == pytest.approx(8.0)

    asyncio.run(scenario())


def test_zero_delay_never_sleeps() -> None:
    async def scenario() -> None:
        fake_time = FakeTime(current=1.0)
        throttle = CrawlDelayThrottle(
            delay_seconds=0.0,
            clock=fake_time.monotonic,
            sleep=fake_time.sleep,
        )

        await throttle.wait()
        await throttle.wait()
        await throttle.wait()

        assert fake_time.sleeps == []

    asyncio.run(scenario())


def test_negative_delay_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="delay_seconds must be greater than or equal to zero",
    ):
        CrawlDelayThrottle(delay_seconds=-0.01)


def test_context_manager_waits_before_entering() -> None:
    async def scenario() -> None:
        fake_time = FakeTime(current=20.0)
        throttle = CrawlDelayThrottle(
            delay_seconds=4.0,
            clock=fake_time.monotonic,
            sleep=fake_time.sleep,
        )

        async with throttle:
            assert throttle.last_started_at == pytest.approx(20.0)

        fake_time.current = 21.0

        async with throttle:
            assert throttle.last_started_at == pytest.approx(24.0)

        assert fake_time.sleeps == [pytest.approx(3.0)]

    asyncio.run(scenario())


def test_concurrent_waiters_are_serialized() -> None:
    async def scenario() -> None:
        fake_time = FakeTime(current=100.0)
        throttle = CrawlDelayThrottle(
            delay_seconds=1.5,
            clock=fake_time.monotonic,
            sleep=fake_time.sleep,
        )

        await asyncio.gather(
            throttle.wait(),
            throttle.wait(),
            throttle.wait(),
        )

        assert fake_time.sleeps == [
            pytest.approx(1.5),
            pytest.approx(1.5),
        ]
        assert throttle.last_started_at == pytest.approx(103.0)

    asyncio.run(scenario())


def test_partial_elapsed_time_is_respected_concurrently() -> None:
    async def scenario() -> None:
        fake_time = FakeTime(current=50.0)
        throttle = CrawlDelayThrottle(
            delay_seconds=2.0,
            clock=fake_time.monotonic,
            sleep=fake_time.sleep,
        )

        await throttle.wait()
        fake_time.current = 50.5

        await asyncio.gather(
            throttle.wait(),
            throttle.wait(),
        )

        assert fake_time.sleeps == [
            pytest.approx(1.5),
            pytest.approx(2.0),
        ]
        assert throttle.last_started_at == pytest.approx(54.0)

    asyncio.run(scenario())
