"""Canonical Playwright rendering and resource-blocking tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from docsync.playwright_rendering import (
    BLOCKED_RESOURCE_TYPES,
    DEFAULT_BROWSER_ARGUMENTS,
    DEFAULT_NETWORK_IDLE_TIMEOUT_MILLISECONDS,
    PlaywrightRenderingConfig,
    handle_route,
    install_resource_blocking,
    merge_playwright_options,
    normalized_blocked_resource_types,
    render_page_html,
    should_block_resource,
)


@dataclass
class FakeRequest:
    resource_type: str


@dataclass
class FakeRoute:
    resource_type: str
    aborted: int = 0
    continued: int = 0

    @property
    def request(self) -> FakeRequest:
        return FakeRequest(
            resource_type=self.resource_type,
        )

    async def abort(self) -> None:
        self.aborted += 1

    async def continue_(self) -> None:
        self.continued += 1


@dataclass
class FakeLogger:
    debug_calls: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)

    def debug(
        self,
        message: str,
        *args: object,
    ) -> None:
        self.debug_calls.append(
            (
                message,
                args,
            )
        )


@dataclass
class FakePage:
    html: str = "<html><body>rendered</body></html>"
    fail_network_idle: bool = False
    route_pattern: str | None = None
    route_handler: Any = None
    wait_calls: list[tuple[str, float | None]] = field(default_factory=list)
    content_calls: int = 0

    async def route(
        self,
        url: str,
        handler: Any,
    ) -> None:
        self.route_pattern = url
        self.route_handler = handler

    async def wait_for_load_state(
        self,
        state: str,
        *,
        timeout: float | None = None,
    ) -> None:
        self.wait_calls.append(
            (
                state,
                timeout,
            )
        )

        if state == "networkidle" and self.fail_network_idle:
            raise TimeoutError("simulated network-idle timeout")

    async def content(self) -> str:
        self.content_calls += 1
        return self.html


@pytest.mark.parametrize(
    "resource_type",
    [
        "font",
        "image",
        "media",
        "websocket",
        " FONT ",
        "Image",
    ],
)
def test_should_block_legacy_resource_types(
    resource_type: str,
) -> None:
    assert should_block_resource(resource_type) is True


@pytest.mark.parametrize(
    "resource_type",
    [
        "document",
        "script",
        "stylesheet",
        "xhr",
        "fetch",
        "",
        " ",
    ],
)
def test_should_continue_required_resource_types(
    resource_type: str,
) -> None:
    assert should_block_resource(resource_type) is False


def test_default_blocking_contract_matches_legacy_runtime() -> None:
    assert {
        "font",
        "image",
        "media",
        "websocket",
    } == BLOCKED_RESOURCE_TYPES


def test_default_browser_arguments_match_legacy_runtime() -> None:
    assert DEFAULT_BROWSER_ARGUMENTS == (
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-sync",
        "--no-first-run",
    )


def test_blocked_route_is_aborted_without_continue() -> None:
    async def scenario() -> None:
        route = FakeRoute(resource_type="image")

        await handle_route(route)

        assert route.aborted == 1
        assert route.continued == 0

    asyncio.run(scenario())


def test_allowed_route_is_continued_without_abort() -> None:
    async def scenario() -> None:
        route = FakeRoute(resource_type="script")

        await handle_route(route)

        assert route.aborted == 0
        assert route.continued == 1

    asyncio.run(scenario())


def test_resource_blocking_installs_all_request_route() -> None:
    async def scenario() -> None:
        page = FakePage()

        await install_resource_blocking(page)

        assert page.route_pattern == "**/*"
        assert page.route_handler is not None

        blocked_route = FakeRoute(resource_type="font")
        allowed_route = FakeRoute(resource_type="stylesheet")

        await page.route_handler(blocked_route)
        await page.route_handler(allowed_route)

        assert blocked_route.aborted == 1
        assert blocked_route.continued == 0
        assert allowed_route.aborted == 0
        assert allowed_route.continued == 1

    asyncio.run(scenario())


def test_custom_resource_blocking_policy_is_supported() -> None:
    async def scenario() -> None:
        page = FakePage()

        await install_resource_blocking(
            page,
            blocked_resource_types=frozenset(
                {
                    "stylesheet",
                }
            ),
        )

        stylesheet = FakeRoute(resource_type="stylesheet")
        image = FakeRoute(resource_type="image")

        await page.route_handler(stylesheet)
        await page.route_handler(image)

        assert stylesheet.aborted == 1
        assert image.continued == 1

    asyncio.run(scenario())


def test_render_waits_for_dom_and_network_idle() -> None:
    async def scenario() -> None:
        page = FakePage()
        logger = FakeLogger()

        html = await render_page_html(
            page,
            url="https://example.com/docs",
            logger=logger,
            request_timeout_seconds=30,
        )

        assert html == page.html
        assert page.wait_calls == [
            (
                "domcontentloaded",
                30_000,
            ),
            (
                "networkidle",
                DEFAULT_NETWORK_IDLE_TIMEOUT_MILLISECONDS,
            ),
        ]
        assert page.content_calls == 1
        assert logger.debug_calls == []

    asyncio.run(scenario())


def test_network_idle_timeout_is_non_fatal() -> None:
    async def scenario() -> None:
        page = FakePage(
            html="<html><body>late content</body></html>",
            fail_network_idle=True,
        )
        logger = FakeLogger()

        html = await render_page_html(
            page,
            url="https://example.com/streaming",
            logger=logger,
            request_timeout_seconds=20,
            network_idle_timeout_milliseconds=5_000,
        )

        assert html == page.html
        assert page.wait_calls == [
            (
                "domcontentloaded",
                20_000,
            ),
            (
                "networkidle",
                5_000,
            ),
        ]
        assert len(logger.debug_calls) == 1

        message, arguments = logger.debug_calls[0]

        assert message == "Network did not become idle: url=%s error=%s"
        assert arguments[0] == "https://example.com/streaming"
        assert isinstance(arguments[1], TimeoutError)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    (
        "request_timeout_seconds",
        "network_idle_timeout_milliseconds",
        "expected_message",
    ),
    [
        (
            0,
            10_000,
            "request_timeout_seconds must be greater than zero",
        ),
        (
            -1,
            10_000,
            "request_timeout_seconds must be greater than zero",
        ),
        (
            30,
            0,
            "network_idle_timeout_milliseconds must be greater than zero",
        ),
        (
            30,
            -1,
            "network_idle_timeout_milliseconds must be greater than zero",
        ),
    ],
)
def test_render_timeout_configuration_is_validated(
    request_timeout_seconds: int,
    network_idle_timeout_milliseconds: int,
    expected_message: str,
) -> None:
    async def scenario() -> None:
        with pytest.raises(
            ValueError,
            match=expected_message,
        ):
            await render_page_html(
                FakePage(),
                url="https://example.com/",
                logger=FakeLogger(),
                request_timeout_seconds=request_timeout_seconds,
                network_idle_timeout_milliseconds=(network_idle_timeout_milliseconds),
            )

    asyncio.run(scenario())


def test_rendering_config_preserves_legacy_browser_options() -> None:
    config = PlaywrightRenderingConfig(
        headless=False,
    )

    assert config.headless is False
    assert config.browser_type == "chromium"
    assert config.request_timeout_seconds == 60
    assert (
        config.network_idle_timeout_milliseconds
        == DEFAULT_NETWORK_IDLE_TIMEOUT_MILLISECONDS
    )
    assert config.blocked_resource_types == BLOCKED_RESOURCE_TYPES
    assert config.browser_arguments == DEFAULT_BROWSER_ARGUMENTS
    assert config.browser_launch_options == {
        "args": list(DEFAULT_BROWSER_ARGUMENTS),
    }
    assert config.crawler_options() == {
        "headless": False,
        "browser_type": "chromium",
        "browser_launch_options": {
            "args": list(DEFAULT_BROWSER_ARGUMENTS),
        },
    }


def test_rendering_config_normalizes_values() -> None:
    config = PlaywrightRenderingConfig(
        browser_type=" CHROMIUM ",
        blocked_resource_types=frozenset(
            {
                " IMAGE ",
                "Font",
                "",
            }
        ),
        browser_arguments=(
            " --no-first-run ",
            "",
        ),
    )

    assert config.browser_type == "chromium"
    assert config.blocked_resource_types == {
        "image",
        "font",
    }
    assert config.browser_arguments == ("--no-first-run",)


@pytest.mark.parametrize(
    (
        "keyword_arguments",
        "expected_message",
    ),
    [
        (
            {
                "browser_type": "opera",
            },
            "browser_type must be chromium, firefox, or webkit",
        ),
        (
            {
                "request_timeout_seconds": 0,
            },
            "request_timeout_seconds must be greater than zero",
        ),
        (
            {
                "network_idle_timeout_milliseconds": 0,
            },
            "network_idle_timeout_milliseconds must be greater than zero",
        ),
    ],
)
def test_rendering_config_rejects_invalid_values(
    keyword_arguments: dict[str, object],
    expected_message: str,
) -> None:
    with pytest.raises(
        ValueError,
        match=expected_message,
    ):
        PlaywrightRenderingConfig(
            **keyword_arguments,
        )


def test_report_configuration_is_json_compatible() -> None:
    config = PlaywrightRenderingConfig(
        headless=False,
        blocked_resource_types=frozenset(
            {
                "image",
                "font",
            }
        ),
    )

    assert config.report_configuration() == {
        "headless": False,
        "browser_type": "chromium",
        "request_timeout_seconds": 60,
        "network_idle_timeout_milliseconds": 10_000,
        "blocked_resource_types": [
            "font",
            "image",
        ],
        "browser_arguments": list(DEFAULT_BROWSER_ARGUMENTS),
    }


def test_merge_playwright_options_preserves_base_options() -> None:
    config = PlaywrightRenderingConfig(
        headless=True,
    )

    merged = merge_playwright_options(
        base_options={
            "max_requests_per_crawl": 10,
            "max_request_retries": 0,
        },
        rendering_config=config,
    )

    assert merged == {
        "max_requests_per_crawl": 10,
        "max_request_retries": 0,
        "headless": True,
        "browser_type": "chromium",
        "browser_launch_options": {
            "args": list(DEFAULT_BROWSER_ARGUMENTS),
        },
    }


def test_normalized_blocked_resource_types() -> None:
    assert normalized_blocked_resource_types(
        [
            " IMAGE ",
            "Font",
            "",
            "image",
        ]
    ) == {
        "image",
        "font",
    }
