#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess  # nosec B404
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ETAG = '"docsync-incremental-v1"'


@dataclass
class PageRequest:
    if_none_match: str
    status: int
    body_bytes: int


@dataclass
class Result:
    status: str = "running"
    first_crawl_return_code: int | None = None
    second_crawl_return_code: int | None = None
    page_requests: list[PageRequest] = field(default_factory=list)
    first_crawl_body_bytes: int = 0
    second_crawl_body_bytes: int = 0
    markdown_files_after_first: int = 0
    markdown_files_after_second: int = 0
    state_etag: str = ""
    issues: list[str] = field(default_factory=list)


class IncrementalFixtureHandler(BaseHTTPRequestHandler):
    page_requests: ClassVar[list[PageRequest]] = []

    def log_message(self, format: str, *args: Any) -> None:
        return

    def send_payload(
        self,
        payload: bytes,
        *,
        content_type: str,
        status: int = 200,
        etag: str | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        if etag is not None:
            self.send_header("ETag", etag)
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path == "/robots.txt":
            self.send_payload(
                b"User-agent: *\nAllow: /\n",
                content_type="text/plain; charset=utf-8",
            )
            return

        if self.path == "/docs":
            validator = self.headers.get("If-None-Match", "")
            if validator == ETAG:
                self.__class__.page_requests.append(
                    PageRequest(
                        if_none_match=validator,
                        status=304,
                        body_bytes=0,
                    )
                )
                self.send_payload(
                    b"",
                    content_type="text/html; charset=utf-8",
                    status=304,
                    etag=ETAG,
                )
                return

            payload = b"""<html lang="en"><head><title>Incremental Docs</title></head>
<body><main><h1>Incremental Docs</h1>
<p>This fixture contains enough stable English documentation text to produce Markdown.</p>
</main></body></html>"""
            self.__class__.page_requests.append(
                PageRequest(
                    if_none_match=validator,
                    status=200,
                    body_bytes=len(payload),
                )
            )
            self.send_payload(
                payload,
                content_type="text/html; charset=utf-8",
                etag=ETAG,
            )
            return

        self.send_payload(
            b"<html><body><h1>Not Found</h1></body></html>",
            content_type="text/html; charset=utf-8",
            status=404,
        )


def run_crawler(
    url: str, *, output_dir: Path, state_dir: Path, log_dir: Path
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "DOCSYNC_TEST_MODE": "1",
            "DOCSYNC_OUTPUT_DIR": str(output_dir),
            "DOCSYNC_STATE_DIR": str(state_dir),
            "DOCSYNC_LOG_DIR": str(log_dir),
            "DOCSYNC_MODE": "http",
            "DOCSYNC_LANGUAGE": "en",
            "DOCSYNC_REFRESH_HOURS": "0",
            "DOCSYNC_MAX_CONCURRENCY": "1",
            "DOCSYNC_MAX_REQUESTS": "10",
            "DOCSYNC_REQUESTS_PER_MINUTE": "60",
        }
    )
    return subprocess.run(  # nosec B603
        [sys.executable, str(PROJECT_ROOT / "main.py"), url],
        cwd=PROJECT_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )


def markdown_count(output_dir: Path) -> int:
    return len(list(output_dir.rglob("*.md"))) if output_dir.exists() else 0


def main() -> int:
    result = Result()
    IncrementalFixtureHandler.page_requests = []

    server = ThreadingHTTPServer(("127.0.0.1", 0), IncrementalFixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host = str(server.server_address[0])
    port = int(server.server_address[1])
    url = f"http://{host}:{port}/docs"

    try:
        with tempfile.TemporaryDirectory(prefix="docsync-incremental-") as temp:
            root = Path(temp)
            output_dir = root / "markdown"
            state_dir = root / "state"
            log_dir = root / "logs"

            first = run_crawler(
                url,
                output_dir=output_dir,
                state_dir=state_dir,
                log_dir=log_dir,
            )
            result.first_crawl_return_code = first.returncode
            result.markdown_files_after_first = markdown_count(output_dir)

            first_records = list(IncrementalFixtureHandler.page_requests)
            result.first_crawl_body_bytes = sum(
                record.body_bytes for record in first_records
            )

            second = run_crawler(
                url,
                output_dir=output_dir,
                state_dir=state_dir,
                log_dir=log_dir,
            )
            result.second_crawl_return_code = second.returncode
            result.markdown_files_after_second = markdown_count(output_dir)

            all_records = list(IncrementalFixtureHandler.page_requests)
            second_records = all_records[len(first_records) :]
            result.second_crawl_body_bytes = sum(
                record.body_bytes for record in second_records
            )
            result.page_requests = all_records

            state_path = state_dir / "url_state.json"
            if state_path.exists():
                state = json.loads(state_path.read_text(encoding="utf-8"))
                result.state_etag = state.get(url, {}).get("etag", "")

            if first.returncode != 0:
                result.issues.append("First crawl returned non-zero.")
            if second.returncode != 0:
                result.issues.append("Second crawl returned non-zero.")
            if not first_records or first_records[-1].status != 200:
                result.issues.append("First crawl did not fetch the page with 200.")
            if not second_records or second_records[-1].status != 304:
                result.issues.append(
                    "Second crawl did not revalidate the page with 304."
                )
            if not second_records or second_records[-1].if_none_match != ETAG:
                result.issues.append("Second crawl did not send the saved ETag.")
            if result.first_crawl_body_bytes <= 0:
                result.issues.append("First crawl transferred no page body.")
            if result.second_crawl_body_bytes != 0:
                result.issues.append("Second crawl transferred a page body.")
            if result.markdown_files_after_first != 1:
                result.issues.append(
                    "First crawl did not create exactly one Markdown file."
                )
            if result.markdown_files_after_second != result.markdown_files_after_first:
                result.issues.append("Second crawl changed the Markdown file count.")
            if result.state_etag != ETAG:
                result.issues.append("ETag was not persisted in URL state.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    result.status = "passed" if not result.issues else "failed"

    print("DOCSYNC INCREMENTAL TWO-CRAWL TEST")
    print("==================================")
    print(f"Status: {result.status}")
    print(f"First crawl return code: {result.first_crawl_return_code}")
    print(f"Second crawl return code: {result.second_crawl_return_code}")
    print(f"First crawl body bytes: {result.first_crawl_body_bytes}")
    print(f"Second crawl body bytes: {result.second_crawl_body_bytes}")
    print(f"Markdown files after first: {result.markdown_files_after_first}")
    print(f"Markdown files after second: {result.markdown_files_after_second}")
    print(f"Persisted ETag: {result.state_etag}")
    print("Page requests:")
    for index, record in enumerate(result.page_requests, start=1):
        print(
            f"  {index}. status={record.status} "
            f"if-none-match={record.if_none_match!r} "
            f"body_bytes={record.body_bytes}"
        )

    if result.issues:
        print("Issues:")
        for issue in result.issues:
            print(f"- {issue}")

    return 0 if not result.issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
