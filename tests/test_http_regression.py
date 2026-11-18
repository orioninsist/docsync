"""Real HTTP regression tests for DocsSync's Python crawler."""

from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import pairwise
from pathlib import Path

from docsync.crawler import run_crawler


class SitemapRegressionHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        with self.server.request_lock:
            self.server.request_paths.append(self.path)

        origin = f"http://127.0.0.1:{self.server.server_port}"

        if self.path == "/robots.txt":
            body = f"User-agent: *\nAllow: /\nSitemap: {origin}/sitemap.xml\n"
            content_type = "text/plain"

        elif self.path == "/sitemap.xml":
            entries = "".join(
                f"<url><loc>{origin}/docs/page-{i}</loc></url>" for i in range(1, 11)
            )
            body = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                + entries
                + "</urlset>"
            )
            content_type = "application/xml"

        elif self.path == "/docs" or self.path.startswith("/docs/page-"):
            body = (
                '<html lang="en"><main>'
                f"<h1>{self.path}</h1>"
                "<p>DocsSync HTTP regression fixture.</p>"
                "</main></html>"
            )
            content_type = "text/html"

        else:
            self.send_response(404)
            self.end_headers()
            return

        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        pass


def test_python_crawls_every_sitemap_document(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        SitemapRegressionHandler,
    )
    server.request_lock = threading.Lock()
    server.request_paths = []

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )
    thread.start()

    try:
        origin = f"http://127.0.0.1:{server.server_port}"

        result = asyncio.run(
            run_crawler(
                start_url=f"{origin}/docs",
                output_dir=tmp_path / "output",
                state_dir=tmp_path / "state",
                language="en",
                max_concurrency=1,
                requests_per_minute=600,
                discover_sitemap=True,
            )
        )

        with server.request_lock:
            requested = set(server.request_paths)

        expected = {f"/docs/page-{i}" for i in range(1, 11)}

        missing = expected - requested

        print("\nSITEMAP REGRESSION")
        print("Expected:", len(expected))
        print("Visited:", len(expected & requested))
        print("Missing:", sorted(missing))
        print("Crawler result:", result)

        assert not missing, f"Sitemap documents were not crawled: {sorted(missing)}"

        markdown_files = list((tmp_path / "output").rglob("*.md"))

        assert len(markdown_files) >= 11, (
            "Expected the start page and all 10 sitemap documents "
            f"to be saved, found {len(markdown_files)} Markdown files."
        )

    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_first_crawl_delay_interval(tmp_path: Path) -> None:
    """The first two page requests must respect robots Crawl-delay."""
    import time

    class DelayHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:

            if self.path.startswith("/docs"):
                with self.server.request_lock:
                    self.server.page_times.append((self.path, time.monotonic()))

            if self.path == "/robots.txt":
                body = "User-agent: *\nAllow: /\nCrawl-delay: 2\n"
                content_type = "text/plain"

            elif self.path in {"/docs", "/docs/one", "/docs/two"}:
                links = (
                    '<a href="/docs/one">One</a><a href="/docs/two">Two</a>'
                    if self.path == "/docs"
                    else ""
                )
                body = (
                    '<html lang="en"><main>'
                    f"<h1>{self.path}</h1>"
                    f"<p>Delay fixture.</p>{links}"
                    "</main></html>"
                )
                content_type = "text/html"

            else:
                self.send_response(404)
                self.end_headers()
                return

            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        DelayHandler,
    )
    server.request_lock = threading.Lock()
    server.page_times = []

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )
    thread.start()

    try:
        origin = f"http://127.0.0.1:{server.server_port}"

        asyncio.run(
            run_crawler(
                start_url=f"{origin}/docs",
                output_dir=tmp_path / "output",
                state_dir=tmp_path / "state",
                language="en",
                max_concurrency=1,
                requests_per_minute=600,
                discover_sitemap=False,
            )
        )

        with server.request_lock:
            visits = list(server.page_times)

        print("\nCRAWL-DELAY REGRESSION")
        print("Page visits:", [path for path, _ in visits])

        assert len(visits) >= 3, f"Expected at least 3 page requests, got {visits}"

        intervals = [later[1] - earlier[1] for earlier, later in pairwise(visits)]

        print("Intervals:", [round(x, 3) for x in intervals])

        assert intervals[0] >= 1.9, (
            f"First Crawl-delay interval was not respected: {intervals[0]:.3f}s"
        )

        assert all(interval >= 1.9 for interval in intervals), (
            f"Later Crawl-delay intervals were not respected: {intervals}"
        )

    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http_429_retry_after(tmp_path: Path) -> None:
    """A 429 Retry-After must delay the next request to the domain."""
    import time

    class RateLimitHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            now = time.monotonic()

            with self.server.request_lock:
                self.server.request_log.append((self.path, now))

                if self.path == "/docs/one":
                    self.server.one_attempts += 1
                    first_attempt = self.server.one_attempts == 1
                else:
                    first_attempt = False

            if self.path == "/robots.txt":
                status = 200
                body = b"User-agent: *\nAllow: /\n"
                content_type = "text/plain"

            elif self.path == "/docs":
                status = 200
                body = (
                    b'<html lang="en"><main>'
                    b"<h1>Rate limit test</h1>"
                    b'<a href="/docs/one">One</a>'
                    b'<a href="/docs/two">Two</a>'
                    b"</main></html>"
                )
                content_type = "text/html"

            elif self.path == "/docs/one" and first_attempt:
                status = 429
                body = b"Too Many Requests"
                content_type = "text/plain"

            elif self.path in {"/docs/one", "/docs/two"}:
                status = 200
                body = (
                    f'<html lang="en"><main><h1>{self.path}</h1>'
                    "<p>Rate limit fixture.</p></main></html>"
                ).encode()
                content_type = "text/html"

            else:
                self.send_response(404)
                self.end_headers()
                return

            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))

            if status == 429:
                self.send_header("Retry-After", "3")

            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        RateLimitHandler,
    )
    server.request_lock = threading.Lock()
    server.request_log = []
    server.one_attempts = 0

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )
    thread.start()

    try:
        origin = f"http://127.0.0.1:{server.server_port}"

        asyncio.run(
            run_crawler(
                start_url=f"{origin}/docs",
                output_dir=tmp_path / "output",
                state_dir=tmp_path / "state",
                language="en",
                max_concurrency=1,
                requests_per_minute=600,
                discover_sitemap=False,
            )
        )

        with server.request_lock:
            log = list(server.request_log)

        pages = [
            (path, timestamp) for path, timestamp in log if path.startswith("/docs")
        ]

        print("\nHTTP 429 REGRESSION")
        print("Page request sequence:", [p for p, _ in pages])

        first_429 = next(timestamp for path, timestamp in pages if path == "/docs/one")

        following = [
            (path, timestamp) for path, timestamp in pages if timestamp > first_429
        ]

        assert following, "No subsequent page request after HTTP 429"

        delay = following[0][1] - first_429

        print("Delay after first 429:", round(delay, 3), "seconds")
        print("Next request:", following[0][0])

        assert delay >= 2.9, f"Retry-After: 3 was not respected: {delay:.3f}s"

    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_sitemap_requests_respect_crawl_delay(tmp_path: Path) -> None:
    """Sitemap-only page requests must respect robots Crawl-delay."""
    import time

    class SitemapDelayHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            origin = f"http://127.0.0.1:{self.server.server_port}"

            if self.path.startswith("/docs"):
                with self.server.request_lock:
                    self.server.page_times.append((self.path, time.monotonic()))

            if self.path == "/robots.txt":
                body = (
                    "User-agent: *\n"
                    "Allow: /\n"
                    "Crawl-delay: 2\n"
                    f"Sitemap: {origin}/sitemap.xml\n"
                )
                content_type = "text/plain"

            elif self.path == "/sitemap.xml":
                entries = "".join(
                    f"<url><loc>{origin}/docs/page-{i}</loc></url>" for i in range(1, 6)
                )
                body = (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    + entries
                    + "</urlset>"
                )
                content_type = "application/xml"

            elif self.path == "/docs" or self.path.startswith("/docs/page-"):
                body = (
                    '<html lang="en"><main>'
                    f"<h1>{self.path}</h1>"
                    "<p>Sitemap-only timing fixture.</p>"
                    "</main></html>"
                )
                content_type = "text/html"

            else:
                self.send_response(404)
                self.end_headers()
                return

            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        SitemapDelayHandler,
    )
    server.request_lock = threading.Lock()
    server.page_times = []

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )
    thread.start()

    try:
        origin = f"http://127.0.0.1:{server.server_port}"

        result = asyncio.run(
            run_crawler(
                start_url=f"{origin}/docs",
                output_dir=tmp_path / "output",
                state_dir=tmp_path / "state",
                language="en",
                max_concurrency=1,
                requests_per_minute=600,
                discover_sitemap=True,
            )
        )

        with server.request_lock:
            visits = list(server.page_times)

        print("\nSITEMAP CRAWL-DELAY REGRESSION")
        print("Page visits:", [path for path, _ in visits])
        print("Crawler result:", result)

        expected = {f"/docs/page-{i}" for i in range(1, 6)}
        actual = {path for path, _ in visits}

        assert expected <= actual, f"Missing sitemap pages: {sorted(expected - actual)}"

        intervals = [later[1] - earlier[1] for earlier, later in pairwise(visits)]

        print(
            "Intervals:",
            [round(interval, 3) for interval in intervals],
        )

        assert intervals, "Not enough page requests to measure delay"

        assert all(interval >= 1.9 for interval in intervals), (
            "Sitemap requests bypassed Crawl-delay: "
            f"{[round(interval, 3) for interval in intervals]}"
        )

    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http_403_does_not_mark_crawl_complete(tmp_path: Path) -> None:
    """A blocked document must fail without marking the crawl complete."""
    import json

    class ForbiddenHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            with self.server.request_lock:
                self.server.request_paths.append(self.path)

            if self.path == "/robots.txt":
                body = b"User-agent: *\\nAllow: /\\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
            elif self.path == "/docs":
                body = (
                    b'<html lang="en"><main><h1>Docs</h1>'
                    b'<a href="/docs/blocked">Blocked</a>'
                    b"</main></html>"
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
            elif self.path == "/docs/blocked":
                body = b"Forbidden"
                self.send_response(403)
                self.send_header("Content-Type", "text/plain")
            else:
                self.send_response(404)
                self.end_headers()
                return

            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), ForbiddenHandler)
    server.request_lock = threading.Lock()
    server.request_paths = []

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )
    thread.start()

    try:
        origin = f"http://127.0.0.1:{server.server_port}"
        state_dir = tmp_path / "state"

        asyncio.run(
            run_crawler(
                start_url=f"{origin}/docs",
                output_dir=tmp_path / "output",
                state_dir=state_dir,
                language="en",
                max_concurrency=1,
                requests_per_minute=600,
                discover_sitemap=False,
            )
        )

        with server.request_lock:
            blocked_attempts = server.request_paths.count("/docs/blocked")

        checkpoint_file = state_dir / "crawl" / "python" / "checkpoint.json"
        checkpoint = json.loads(checkpoint_file.read_text(encoding="utf-8"))

        assert blocked_attempts == 1, (
            f"Expected one blocked request, got {blocked_attempts}"
        )
        assert checkpoint["status"] != "complete", (
            "HTTP 403 must not produce a complete checkpoint"
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http_403_recovers_on_resume(tmp_path: Path) -> None:
    """A previously blocked page must be recoverable on the next run."""
    import json

    class RecoveringHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            with self.server.request_lock:
                self.server.request_paths.append(self.path)
                blocked = self.server.blocked

            if self.path == "/robots.txt":
                status = 200
                body = b"User-agent: *\nAllow: /\n"
                content_type = "text/plain"
            elif self.path == "/docs":
                status = 200
                body = (
                    b'<html lang="en"><main><h1>Docs</h1>'
                    b'<a href="/docs/blocked">Blocked</a>'
                    b"</main></html>"
                )
                content_type = "text/html"
            elif self.path == "/docs/blocked":
                status = 403 if blocked else 200
                body = (
                    b"Forbidden"
                    if blocked
                    else b'<html lang="en"><main><h1>Recovered</h1>'
                    b"<p>Recovered documentation content.</p>"
                    b"</main></html>"
                )
                content_type = "text/plain" if blocked else "text/html"
            else:
                self.send_response(404)
                self.end_headers()
                return

            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), RecoveringHandler)
    server.request_lock = threading.Lock()
    server.request_paths = []
    server.blocked = True

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        origin = f"http://127.0.0.1:{server.server_port}"
        output_dir = tmp_path / "output"
        state_dir = tmp_path / "state"
        checkpoint_file = state_dir / "crawl" / "python" / "checkpoint.json"

        options = {
            "start_url": f"{origin}/docs",
            "output_dir": output_dir,
            "state_dir": state_dir,
            "language": "en",
            "max_concurrency": 1,
            "requests_per_minute": 600,
            "discover_sitemap": False,
        }

        asyncio.run(run_crawler(**options))

        first_checkpoint = json.loads(checkpoint_file.read_text(encoding="utf-8"))
        assert first_checkpoint["status"] == "running"

        with server.request_lock:
            server.blocked = False

        asyncio.run(run_crawler(**options))

        second_checkpoint = json.loads(checkpoint_file.read_text(encoding="utf-8"))

        with server.request_lock:
            attempts = server.request_paths.count("/docs/blocked")

        markdown = "\n".join(
            p.read_text(encoding="utf-8") for p in output_dir.rglob("*.md")
        )

        assert attempts >= 2, (
            f"Blocked URL was not retried on resume: {attempts} attempts"
        )
        assert "Recovered documentation content" in markdown
        assert second_checkpoint["status"] == "complete"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
