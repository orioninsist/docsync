"""Deterministic asynchronous crawl-delay throttling."""

from __future__ import annotations

import asyncio
import inspect
import math
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol


class MonotonicClock(Protocol):
    """Callable returning monotonically increasing seconds."""

    def __call__(self) -> float:
        """Return the current monotonic timestamp."""


type SleepResult = Awaitable[None] | None
type SleepFunction = Callable[[float], SleepResult]


CRAWL_DELAY_ENVIRONMENT_VARIABLE = "DOCSYNC_CRAWL_DELAY_SECONDS"


def crawl_delay_seconds_from_environment() -> float:
    """Read and validate the configured crawl delay."""

    raw_value = os.environ.get(CRAWL_DELAY_ENVIRONMENT_VARIABLE, "0").strip()

    try:
        delay_seconds = float(raw_value)
    except ValueError as error:
        raise ValueError(
            f"{CRAWL_DELAY_ENVIRONMENT_VARIABLE} must be a finite non-negative number"
        ) from error

    if not math.isfinite(delay_seconds) or delay_seconds < 0:
        raise ValueError(
            f"{CRAWL_DELAY_ENVIRONMENT_VARIABLE} must be a finite non-negative number"
        )

    return delay_seconds


@dataclass(slots=True)
class CrawlDelayThrottle:
    """Serialize request starts and enforce a minimum delay between them.

    The throttle controls request start times rather than request completion
    times. A single instance must be shared by all request handlers belonging
    to the same crawl or origin.
    """

    delay_seconds: float
    clock: MonotonicClock = time.monotonic
    sleep: SleepFunction = asyncio.sleep
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _last_started_at: float | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.delay_seconds < 0:
            raise ValueError("delay_seconds must be greater than or equal to zero")

    async def wait(self) -> None:
        """Wait until the next request may start."""

        async with self._lock:
            now = self.clock()

            if self._last_started_at is not None:
                elapsed = max(0.0, now - self._last_started_at)
                remaining = max(0.0, self.delay_seconds - elapsed)

                if remaining > 0:
                    result = self.sleep(remaining)
                    if inspect.isawaitable(result):
                        await result

                    now = self.clock()

            self._last_started_at = now

    async def __aenter__(self) -> CrawlDelayThrottle:
        await self.wait()
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        return None

    @property
    def last_started_at(self) -> float | None:
        """Return the last recorded request-start timestamp."""

        return self._last_started_at
