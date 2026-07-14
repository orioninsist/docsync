"""UTC time utilities owned exclusively by the crawler package."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> str:
    """Return the current UTC timestamp in ISO 8601 seconds precision."""
    return datetime.now(UTC).isoformat(timespec="seconds")
