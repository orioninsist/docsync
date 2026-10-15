from __future__ import annotations

import asyncio
from collections import deque

from crawlee import Request
from crawlee.request_loaders import RequestManagerTandem, SitemapRequestLoader


class InMemoryRequestManager:
    def __init__(self) -> None:
        self.pending: deque[Request] = deque()
        self.in_progress: set[str] = set()

    async def add_request(
        self, request: str | Request, *, forefront: bool = False
    ) -> None:
        if isinstance(request, str):
            request = Request.from_url(request)
        if forefront:
            self.pending.appendleft(request)
        else:
            self.pending.append(request)

    async def fetch_next_request(self) -> Request | None:
        if not self.pending:
            return None
        request = self.pending.popleft()
        self.in_progress.add(request.url)
        return request

    async def mark_request_as_handled(self, request: Request) -> None:
        self.in_progress.discard(request.url)

    async def is_finished(self) -> bool:
        return not self.pending and not self.in_progress


class InMemorySitemapLoader:
    def __init__(self, urls: list[str]) -> None:
        self.pending = deque(Request.from_url(url) for url in urls)
        self.in_progress: set[str] = set()

    async def fetch_next_request(self) -> Request | None:
        if not self.pending:
            return None
        request = self.pending.popleft()
        self.in_progress.add(request.url)
        return request

    async def mark_request_as_handled(self, request: Request) -> None:
        self.in_progress.discard(request.url)

    async def is_finished(self) -> bool:
        return not self.pending and not self.in_progress


def test_native_tandem_transfers_sitemap_requests() -> None:
    asyncio.run(_check_native_tandem_transfers_sitemap_requests())


async def _check_native_tandem_transfers_sitemap_requests() -> None:
    loader = InMemorySitemapLoader(
        [
            "https://example.com/docs/a",
            "https://example.com/docs/b",
        ]
    )
    manager = InMemoryRequestManager()
    tandem = RequestManagerTandem(loader, manager)

    seen: set[str] = set()

    for _ in range(5):
        if await tandem.is_finished():
            break

        request = await tandem.fetch_next_request()
        if request is None:
            await asyncio.sleep(0)
            continue

        seen.add(request.url)
        await tandem.mark_request_as_handled(request)

    assert seen == {
        "https://example.com/docs/a",
        "https://example.com/docs/b",
    }
    assert await tandem.is_finished()


def test_native_sitemap_loader_supports_request_filtering() -> None:
    import inspect

    parameters = inspect.signature(SitemapRequestLoader).parameters
    assert "transform_request_function" in parameters
    assert "enqueue_strategy" in parameters
    assert "sitemap_urls" in parameters


def test_real_sitemap_loader_discovers_and_filters_urls() -> None:
    asyncio.run(_check_real_sitemap_loader())


async def _check_real_sitemap_loader() -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    from crawlee.http_clients import ImpitHttpClient
    from crawlee.request_loaders import SitemapRequestLoader
    from crawlee.request_loaders._request_manager_tandem import RequestManagerTandem

    class SitemapHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            host = f"http://127.0.0.1:{self.server.server_port}"
            body = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>{host}/docs/en/one</loc></url>
<url><loc>{host}/docs/en/two</loc></url>
<url><loc>{host}/docs/fr/three</loc></url>
</urlset>""".encode()

            self.send_response(200)
            self.send_header("Content-Type", "application/xml")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), SitemapHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        origin = f"http://127.0.0.1:{server.server_port}"

        def transform(options):
            if "/docs/en/" not in options["url"]:
                return "skip"
            return options

        async with (
            ImpitHttpClient() as client,
            SitemapRequestLoader(
                sitemap_urls=[f"{origin}/sitemap.xml"],
                http_client=client,
                enqueue_strategy="same-hostname",
                transform_request_function=transform,
            ) as loader,
        ):
            manager = InMemoryRequestManager()
            tandem = RequestManagerTandem(loader, manager)
            seen: set[str] = set()

            async def consume() -> None:
                while not await tandem.is_finished():
                    request = await tandem.fetch_next_request()
                    if request is None:
                        await asyncio.sleep(0.05)
                        continue
                    seen.add(request.url)
                    await tandem.mark_request_as_handled(request)

            await asyncio.wait_for(consume(), timeout=15)

            assert seen == {
                f"{origin}/docs/en/one",
                f"{origin}/docs/en/two",
            }
            assert await tandem.is_finished()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
