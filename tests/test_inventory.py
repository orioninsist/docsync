from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from docsync.inventory import (
    SiteInventory,
    run_inventory,
)
from docsync.sitemap import SitemapDiscoveryResult


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
) -> None:
    async def fake_sitemap_discovery(
        **_: object,
    ) -> SitemapDiscoveryResult:
        return SitemapDiscoveryResult(
            urls=[
                "https://example.com/docs/from-sitemap",
            ],
            sitemap_files_checked=2,
            sitemap_files_found=1,
        )

    response_data = {
        "https://example.com/robots.txt": (
            200,
            {
                "content-type": "text/plain",
            },
            "User-agent: *\nAllow: /\n",
        ),
        "https://example.com/docs": (
            200,
            {
                "content-type": "text/html",
                "content-language": "en",
            },
            (
                '<html lang="en"><body>'
                "<p>English documentation landing page.</p>"
                '<a href="/docs/child">Child</a>'
                "</body></html>"
            ),
        ),
        "https://example.com/docs/from-sitemap": (
            200,
            {
                "content-type": "text/html",
                "content-language": "en",
            },
            (
                '<html lang="en"><body>'
                "<p>English documentation discovered from sitemap.</p>"
                "</body></html>"
            ),
        ),
        "https://example.com/docs/child": (
            200,
            {
                "content-type": "text/html",
                "content-language": "fr",
            },
            (
                '<html lang="fr"><body>'
                "<p>Contenu français de documentation.</p>"
                "</body></html>"
            ),
        ),
    }

    async def fake_get(
        _client: httpx.AsyncClient,
        url: str,
        **_: object,
    ) -> httpx.Response:
        status_code, headers, text = response_data[url]

        return httpx.Response(
            status_code,
            headers=headers,
            text=text,
            request=httpx.Request(
                "GET",
                url,
            ),
        )

    monkeypatch.setattr(
        "docsync.inventory.discover_sitemap_urls",
        fake_sitemap_discovery,
    )
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        fake_get,
    )

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

    assert report.sitemap_urls == 1
    assert report.sitemap_files_checked == 2
    assert report.sitemap_files_found == 1
    assert report.discovered_urls == 3
    assert report.processed_urls == 3
    assert report.english_urls == 2
    assert report.non_english_urls == 1
    assert report.reachable_pages == 3
    assert report.remaining_urls == 0
    assert report.discovery_complete is True

    report_path = tmp_path / "site-inventory.json"

    assert report_path.is_file()

    payload = json.loads(
        report_path.read_text(
            encoding="utf-8",
        )
    )

    assert payload["seed_url"] == "https://example.com/docs"
    assert payload["english_urls"] == 2
    assert payload["discovery_complete"] is True


def test_inventory_reports_incomplete_when_request_limit_is_reached(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def fake_sitemap_discovery(
        **_: object,
    ) -> SitemapDiscoveryResult:
        return SitemapDiscoveryResult(
            urls=[
                "https://example.com/docs/a",
                "https://example.com/docs/b",
            ]
        )

    response_data = {
        "https://example.com/robots.txt": (
            200,
            {
                "content-type": "text/plain",
            },
            "User-agent: *\nAllow: /\n",
        ),
        "https://example.com/docs": (
            200,
            {
                "content-type": "text/html",
                "content-language": "en",
            },
            '<html lang="en"><body><p>Documentation.</p></body></html>',
        ),
    }

    async def fake_get(
        _client: httpx.AsyncClient,
        url: str,
        **_: object,
    ) -> httpx.Response:
        status_code, headers, text = response_data[url]

        return httpx.Response(
            status_code,
            headers=headers,
            text=text,
            request=httpx.Request(
                "GET",
                url,
            ),
        )

    monkeypatch.setattr(
        "docsync.inventory.discover_sitemap_urls",
        fake_sitemap_discovery,
    )
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        fake_get,
    )

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


def test_inventory_preserves_directory_seed_slash(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def fake_sitemap_discovery(
        **_: object,
    ) -> SitemapDiscoveryResult:
        return SitemapDiscoveryResult()

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

    async def fake_get(
        _client: httpx.AsyncClient,
        url: str,
        **_: object,
    ) -> httpx.Response:
        status_code, headers, text = responses[url]

        return httpx.Response(
            status_code,
            headers=headers,
            text=text,
            request=httpx.Request(
                "GET",
                url,
            ),
        )

    monkeypatch.setattr(
        "docsync.inventory.discover_sitemap_urls",
        fake_sitemap_discovery,
    )
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        fake_get,
    )

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
