from __future__ import annotations

import asyncio
import subprocess
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from docsync.crawler import run_crawler


class SitemapFixture(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        with self.server.request_lock:
            self.server.request_paths.append(self.path)

        origin = f"http://127.0.0.1:{self.server.server_port}"

        if self.path == "/robots.txt":
            body = f"User-agent: *\nAllow: /\nSitemap: {origin}/index.xml\n"
            content_type = "text/plain"
        elif self.path == "/index.xml":
            body = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f'<sitemap><loc>{origin}/nested.xml</loc></sitemap>'
                '</sitemapindex>'
            )
            content_type = "application/xml"
        elif self.path == "/nested.xml":
            urls = [
                "/docs/one",
                "/docs/two",
                "/docs/foreign?hl=fr",
                "/outside/three",
            ]
            entries = "".join(
                f"<url><loc>{origin}{url}</loc></url>" for url in urls
            )
            body = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                + entries
                + "</urlset>"
            )
            content_type = "application/xml"
        elif self.path in {"/docs", "/docs/one", "/docs/two"}:
            body = (
                '<html lang="en"><main>'
                f"<h1>{self.path}</h1><p>Fixture content.</p>"
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


def test_native_sitemap_discovery_parity(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), SitemapFixture)
    server.request_paths = []
    server.request_lock = threading.Lock()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        start_url = f"http://127.0.0.1:{server.server_port}/docs"

        python_output = tmp_path / "python-output"
        typescript_output = tmp_path / "typescript-output"

        asyncio.run(
            run_crawler(
                start_url=start_url,
                output_dir=python_output,
                state_dir=tmp_path / "python-state",
                language="en",
                max_concurrency=1,
                requests_per_minute=600,
            )
        )

        with server.request_lock:
            python_requests = Counter(server.request_paths)
            server.request_paths.clear()

        subprocess.run(
            [
                "npm",
                "run",
                "docsync",
                "--",
                start_url,
                "--language",
                "en",
                "--output-dir",
                str(typescript_output),
                "--state-dir",
                str(tmp_path / "typescript-state"),
            ],
            cwd=Path(__file__).parents[1] / "typescript",
            check=True,
            timeout=120,
        )

        def documents(folder: Path) -> list[str]:
            return sorted(
                path.read_text(encoding="utf-8")
                for path in folder.glob("*.md")
            )

        python_docs = documents(python_output)
        typescript_docs = documents(typescript_output)

        with server.request_lock:
            typescript_requests = Counter(server.request_paths)

        assert len(python_docs) == 3
        assert python_docs == typescript_docs

        for engine, requests in (
            ("python", python_requests),
            ("typescript", typescript_requests),
        ):
            print(f"{engine} HTTP requests: {dict(requests)}")
            assert requests["/docs/one"] >= 1
            assert requests["/docs/two"] >= 1
            assert requests["/outside/three"] == 0
            # Native sitemap discovery may fetch a URL before the
            # request handler rejects its non-selected language.
            if engine == "python":
                assert requests["/docs/foreign?hl=fr"] == 0

    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
