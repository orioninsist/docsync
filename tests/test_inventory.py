from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

from crawlee import Request
from crawlee.crawlers import BeautifulSoupCrawler
from crawlee.http_clients import HttpCrawlingResult
from crawlee.http_clients._base import HttpClient, HttpResponse

from docsync.inventory import (
    SiteInventory,
    run_inventory,
)


class InventoryHttpClient(HttpClient):
    def __init__(
        self,
        responses: dict[
            str,
            tuple[
                int,
                dict[str, str],
                str,
                str | None,
            ],
        ],
    ) -> None:
        super().__init__()
        self._responses = responses

    def _response_for_url(self, url: str) -> tuple[int, dict[str, str], str, str]:
        status_code, headers, text, loaded_url = self._responses[url]

        return (
            status_code,
            headers,
            text,
            loaded_url or url,
        )

    @staticmethod
    def _make_response(
        *,
        status_code: int,
        headers: dict[str, str],
        text: str,
    ) -> HttpResponse:
        response = MagicMock(spec=HttpResponse)
        response.status_code = status_code
        response.headers = headers

        async def read() -> bytes:
            return text.encode()

        response.read = read

        return response

    async def crawl(
        self,
        request: Request,
        **_: Any,
    ) -> HttpCrawlingResult:
        status_code, headers, text, loaded_url = self._response_for_url(request.url)
        request.loaded_url = loaded_url

        return HttpCrawlingResult(
            http_response=self._make_response(
                status_code=status_code,
                headers=headers,
                text=text,
            )
        )

    async def send_request(
        self,
        url: str,
        **_: Any,
    ) -> HttpResponse:
        status_code, headers, text, _loaded_url = self._response_for_url(url)

        return self._make_response(
            status_code=status_code,
            headers=headers,
            text=text,
        )

    @asynccontextmanager
    async def stream(
        self,
        url: str,
        **_: Any,
    ) -> AsyncIterator[HttpResponse]:
        yield await self.send_request(url)

    async def cleanup(self) -> None:
        return None


def install_inventory_http_client(
    monkeypatch,
    responses: dict[
        str,
        tuple[
            int,
            dict[str, str],
            str,
            str | None,
        ],
    ],
) -> None:
    fake_client = InventoryHttpClient(responses)

    from docsync import inventory

    real_build_http_crawler = inventory.build_http_crawler

    def build_crawler(**kwargs: Any) -> BeautifulSoupCrawler:
        return cast(
            BeautifulSoupCrawler,
            real_build_http_crawler(
                **kwargs,
                http_client=fake_client,
            ),
        )

    monkeypatch.setattr(
        "docsync.inventory.build_http_crawler",
        build_crawler,
    )


def test_inventory_render_contains_required_fields() -> None:
    report = SiteInventory(
        seed_url="https://example.com/docs",
        sitemap_urls=10,
        discovered_urls=12,
        english_urls=9,
        non_english_urls=1,
        robots_blocked=1,
        duplicate_urls=3,
        redirects=2,
        reachable_pages=10,
        not_found_pages=1,
        timeouts=1,
        discovery_complete=True,
    )

    rendered = report.render()

    assert "SITE INVENTORY" in rendered
    assert "Sitemap URLs:        10" in rendered
    assert "Discovered URLs:     12" in rendered
    assert "English URLs:        9" in rendered
    assert "Non-English URLs:    1" in rendered
    assert "Discovery complete:  YES" in rendered


def test_inventory_discovers_links_and_writes_json(
    monkeypatch,
    tmp_path: Path,
    caplog,
) -> None:
    response_data = {
        "https://example.com/robots.txt": (
            200,
            {"content-type": "text/plain"},
            "User-agent: *\nAllow: /\n",
        ),
        "https://example.com/docs": (
            200,
            {"content-type": "text/html", "content-language": "en"},
            (
                '<html lang="en"><body>'
                "<p>English documentation landing page.</p>"
                '<a href="/docs/child">Child</a>'
                "</body></html>"
            ),
        ),
        "https://example.com/docs/child": (
            200,
            {"content-type": "text/html", "content-language": "fr"},
            '<html lang="fr"><body><p>Contenu français de documentation.</p></body></html>',
        ),
    }

    install_inventory_http_client(
        monkeypatch,
        {
            url: (status, headers, text, None)
            for url, (status, headers, text) in response_data.items()
        },
    )

    from docsync import inventory

    class FakeSitemapLoader:
        async def get_total_count(self) -> int:
            return 0

        async def is_finished(self) -> bool:
            return True

        async def is_empty(self) -> bool:
            return True

        async def close(self) -> None:
            return None

    monkeypatch.setattr(
        inventory,
        "build_sitemap_request_loader",
        lambda **_: FakeSitemapLoader(),
    )
    monkeypatch.setattr(
        inventory.ImpitHttpClient,
        "cleanup",
        lambda self: asyncio.sleep(0),
    )

    caplog.set_level(logging.WARNING)

    report = asyncio.run(
        run_inventory(
            start_url="https://example.com/docs",
            state_dir=tmp_path,
            max_requests=10,
            max_concurrency=2,
            requests_per_minute=60_000,
            request_timeout_seconds=5,
        )
    )

    assert report.sitemap_urls == 0
    assert report.discovered_urls == 2
    assert report.processed_urls == 2
    assert report.english_urls == 1
    assert report.non_english_urls == 1
    assert report.reachable_pages == 2
    assert report.remaining_urls == 0
    assert report.discovery_complete is True
    assert "not using `ThrottlingRequestManager`" not in caplog.text

    report_path = tmp_path / "site-inventory.json"
    assert report_path.is_file()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["seed_url"] == "https://example.com/docs"
    assert payload["english_urls"] == 1
    assert payload["discovery_complete"] is True


def test_inventory_reports_incomplete_when_request_limit_is_reached(
    monkeypatch,
    tmp_path: Path,
) -> None:
    response_data = {
        "https://example.com/robots.txt": (
            200,
            {"content-type": "text/plain"},
            "User-agent: *\nAllow: /\n",
        ),
        "https://example.com/docs": (
            200,
            {"content-type": "text/html", "content-language": "en"},
            (
                '<html lang="en"><body><p>Documentation.</p>'
                '<a href="/docs/a">A</a><a href="/docs/b">B</a>'
                "</body></html>"
            ),
        ),
    }

    install_inventory_http_client(
        monkeypatch,
        {
            url: (status, headers, text, None)
            for url, (status, headers, text) in response_data.items()
        },
    )

    from docsync import inventory

    class FakeSitemapLoader:
        async def get_total_count(self) -> int:
            return 0

        async def is_finished(self) -> bool:
            return True

        async def is_empty(self) -> bool:
            return True

        async def close(self) -> None:
            return None

    monkeypatch.setattr(inventory, "build_sitemap_request_loader", lambda **_: FakeSitemapLoader())
    monkeypatch.setattr(inventory.ImpitHttpClient, "cleanup", lambda self: asyncio.sleep(0))

    report = asyncio.run(
        run_inventory(
            start_url="https://example.com/docs",
            state_dir=tmp_path,
            max_requests=1,
            max_concurrency=1,
            requests_per_minute=60_000,
            request_timeout_seconds=5,
        )
    )

    assert report.processed_urls == 1
    assert report.discovered_urls == 3
    assert report.remaining_urls == 2
    assert report.discovery_complete is False

    request_storage = tmp_path / "crawlee" / "inventory" / "example.com"
    assert request_storage.exists()
    assert any(request_storage.rglob("*"))


def test_inventory_preserves_directory_seed_slash(
    monkeypatch,
    tmp_path: Path,
) -> None:
    responses = {
        "https://example.com/robots.txt": (
            200,
            {
                "content-type": "text/plain",
            },
            "User-agent: *\nAllow: /\n",
        ),
        "https://example.com/docs/": (
            200,
            {
                "content-type": "text/html",
                "content-language": "en",
            },
            (
                '<html lang="en"><body>'
                "<main>"
                "<h1>English documentation</h1>"
                "<p>This English documentation page contains "
                "enough meaningful text for reliable language detection.</p>"
                '<a href="child.html">Child page</a>'
                "</main>"
                "</body></html>"
            ),
        ),
        "https://example.com/docs/child.html": (
            200,
            {
                "content-type": "text/html",
                "content-language": "en",
            },
            (
                '<html lang="en"><body>'
                "<main>"
                "<h1>English child documentation</h1>"
                "<p>This English child documentation page verifies "
                "directory-relative URL resolution.</p>"
                "</main>"
                "</body></html>"
            ),
        ),
    }

    install_inventory_http_client(
        monkeypatch,
        {
            url: (status, headers, text, None)
            for url, (status, headers, text) in responses.items()
        },
    )

    from docsync import inventory

    class FakeSitemapLoader:
        async def get_total_count(self) -> int:
            return 0

        async def is_finished(self) -> bool:
            return True

        async def is_empty(self) -> bool:
            return True

        async def close(self) -> None:
            return None

    monkeypatch.setattr(inventory, "build_sitemap_request_loader", lambda **_: FakeSitemapLoader())
    monkeypatch.setattr(inventory.ImpitHttpClient, "cleanup", lambda self: asyncio.sleep(0))

    report = asyncio.run(
        run_inventory(
            start_url="https://example.com/docs/",
            state_dir=tmp_path,
            max_requests=10,
            max_concurrency=1,
            requests_per_minute=60_000,
            request_timeout_seconds=5,
        )
    )

    assert report.seed_url == "https://example.com/docs/"
    assert report.discovered_urls == 2
    assert report.processed_urls == 2
    assert report.english_urls == 2
    assert report.non_english_urls == 0
    assert report.reachable_pages == 2
    assert report.remaining_urls == 0
    assert report.discovery_complete is True
