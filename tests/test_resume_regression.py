"""Regression tests for persistent failed-request recovery."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from docsync.crawler import _restore_failed_requests


def test_resume_pending_request_is_not_reopened() -> None:
    queue = SimpleNamespace(
        get_request=AsyncMock(return_value=SimpleNamespace(handled_at=None)),
        reopen_request=AsyncMock(),
    )

    asyncio.run(
        _restore_failed_requests(
            queue,
            {"failed_keys": ["https://example.org/docs/pending"]},
        )
    )

    queue.get_request.assert_awaited_once_with("https://example.org/docs/pending")
    queue.reopen_request.assert_not_awaited()


def test_resume_handled_request_is_reopened() -> None:
    url = "https://example.org/docs/handled"
    queue = SimpleNamespace(
        get_request=AsyncMock(
            return_value=SimpleNamespace(handled_at=datetime.now(UTC))
        ),
        reopen_request=AsyncMock(return_value=object()),
    )

    asyncio.run(_restore_failed_requests(queue, {"failed_keys": [url]}))

    queue.get_request.assert_awaited_once_with(url)
    queue.reopen_request.assert_awaited_once_with(url)


def test_resume_missing_request_fails_explicitly() -> None:
    url = "https://example.org/docs/missing"
    queue = SimpleNamespace(
        get_request=AsyncMock(return_value=None),
        reopen_request=AsyncMock(),
    )

    with pytest.raises(RuntimeError, match="missing from persistent queue"):
        asyncio.run(_restore_failed_requests(queue, {"failed_keys": [url]}))

    queue.reopen_request.assert_not_awaited()


def test_resume_active_cooldown_is_preserved() -> None:
    url = "https://example.org/docs/blocked"
    retry_at = (datetime.now(UTC) + timedelta(hours=24)).isoformat()

    queue = SimpleNamespace(
        get_request=AsyncMock(),
        reopen_request=AsyncMock(),
    )

    asyncio.run(
        _restore_failed_requests(
            queue,
            {
                "failed_keys": [url],
                "failed_cooldowns": {url: retry_at},
            },
        )
    )

    queue.get_request.assert_not_awaited()
    queue.reopen_request.assert_not_awaited()


def test_resume_handled_reopen_failure_is_explicit() -> None:
    url = "https://example.org/docs/handled"
    queue = SimpleNamespace(
        get_request=AsyncMock(
            return_value=SimpleNamespace(handled_at=datetime.now(UTC))
        ),
        reopen_request=AsyncMock(return_value=None),
    )

    with pytest.raises(RuntimeError, match="Cannot reopen handled request"):
        asyncio.run(_restore_failed_requests(queue, {"failed_keys": [url]}))


def test_resume_with_persistent_crawlee_queue(tmp_path) -> None:
    """Pending and handled requests survive persistent queue reopening."""
    from crawlee import Request
    from crawlee.configuration import Configuration
    from crawlee.storage_clients import FileSystemStorageClient
    from crawlee.storages import RequestQueue

    async def scenario() -> None:
        storage_dir = tmp_path / "storage"
        configuration = Configuration(
            storage_dir=str(storage_dir),
            purge_on_start=False,
        )
        storage_client = FileSystemStorageClient()

        queue = await RequestQueue.open(
            alias="throttled-example.org",
            configuration=configuration,
            storage_client=storage_client,
        )

        pending_url = "https://example.org/docs/pending"
        handled_url = "https://example.org/docs/handled"

        await queue.add_request(Request.from_url(pending_url))
        await queue.add_request(Request.from_url(handled_url))

        # Crawlee requires a request to be in progress before marking it handled.
        first_request = await queue.fetch_next_request()
        assert first_request is not None
        assert first_request.unique_key == pending_url

        second_request = await queue.fetch_next_request()
        assert second_request is not None
        assert second_request.unique_key == handled_url

        await queue.mark_request_as_handled(second_request)

        assert (await queue.get_request(pending_url)).handled_at is None
        assert (await queue.get_request(handled_url)).handled_at is not None

        await _restore_failed_requests(
            queue,
            {"failed_keys": [pending_url, handled_url]},
        )

        pending = await queue.get_request(pending_url)
        reopened = await queue.get_request(handled_url)

        assert pending is not None
        assert pending.handled_at is None
        assert reopened is not None
        assert reopened.handled_at is None

    asyncio.run(scenario())
