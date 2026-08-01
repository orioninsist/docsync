#!/usr/bin/env python3
from __future__ import annotations

import itertools
import json
import os
import subprocess  # nosec B404 - subprocess module is required for controlled local tooling
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGS_ROOT = PROJECT_ROOT / "logs" / "safe_crawl_test"


@dataclass
class RequestRecord:
    timestamp: float
    path: str
    user_agent: str


@dataclass
class TestResult:
    started_at: str
    finished_at: str | None = None
    status: str = "running"
    crawler_return_code: int | None = None
    elapsed_seconds: float | None = None
    request_count: int = 0
    minimum_request_gap_seconds: float | None = None
    robots_requested: bool = False
    blocked_path_requested: bool = False
    duplicate_requests: int = 0
    markdown_files_before: int = 0
    markdown_files_after: int = 0
    markdown_files_created: int = 0
    logs_latest_exists: bool = False
    test_mode_used: bool = True
    issues: list[str] = field(default_factory=list)
    stdout_tail: str = ""
    stderr_tail: str = ""


class SafeFixtureHandler(BaseHTTPRequestHandler):
    records: ClassVar[list[RequestRecord]] = []

    def log_message(
        self,
        format: str,
        *args: Any,
    ) -> None:
        return

    def record(self) -> None:
        self.__class__.records.append(
            RequestRecord(
                timestamp=time.monotonic(),
                path=self.path,
                user_agent=self.headers.get(
                    "User-Agent",
                    "",
                ),
            )
        )

    def send_payload(
        self,
        payload: bytes,
        *,
        content_type: str,
        status: int = 200,
    ) -> None:
        self.send_response(status)
        self.send_header(
            "Content-Type",
            content_type,
        )
        self.send_header(
            "Content-Length",
            str(len(payload)),
        )
        self.end_headers()
        self.wfile.write(payload)

    def send_html(
        self,
        body: str,
        *,
        status: int = 200,
    ) -> None:
        self.send_payload(
            body.encode("utf-8"),
            content_type=("text/html; charset=utf-8"),
            status=status,
        )

    def do_GET(self) -> None:
        self.record()

        if self.path == "/robots.txt":
            self.send_payload(
                (b"User-agent: *\nAllow: /\nDisallow: /blocked\nCrawl-delay: 1\n"),
                content_type=("text/plain; charset=utf-8"),
            )
            return

        if self.path in {"/", "/docs"}:
            self.send_html(
                """
                <html lang="en">
                  <head>
                    <title>Docs Home</title>
                  </head>
                  <body>
                    <main>
                      <h1>Documentation Home</h1>
                      <p>Safe local crawler fixture.</p>
                      <a href="/page-one">Page One</a>
                      <a href="/page-two">Page Two</a>
                      <a href="/duplicate">Duplicate</a>
                      <a href="/blocked">Blocked</a>
                    </main>
                  </body>
                </html>
                """
            )
            return

        if self.path == "/page-one":
            self.send_html(
                """
                <html lang="en">
                  <head>
                    <title>Page One</title>
                  </head>
                  <body>
                    <main>
                      <h1>Page One</h1>
                      <p>Unique page content.</p>
                    </main>
                  </body>
                </html>
                """
            )
            return

        if self.path in {
            "/page-two",
            "/duplicate",
        }:
            self.send_html(
                """
                <html lang="en">
                  <head>
                    <title>Duplicate Content</title>
                  </head>
                  <body>
                    <main>
                      <h1>Duplicate Content</h1>
                      <p>
                        This exact content is
                        intentionally repeated.
                      </p>
                    </main>
                  </body>
                </html>
                """
            )
            return

        if self.path == "/blocked":
            self.send_html(
                """
                <html lang="en">
                  <body>
                    <h1>
                      This must never be downloaded
                    </h1>
                  </body>
                </html>
                """
            )
            return

        self.send_html(
            ("<html><body><h1>Not Found</h1></body></html>"),
            status=404,
        )


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def markdown_files() -> set[Path]:
    output = PROJECT_ROOT / "output"

    if not output.exists():
        return set()

    return {path.resolve() for path in output.rglob("*.md")}


def crawler_page_records(
    records: list[RequestRecord],
) -> list[RequestRecord]:
    non_robots = [record for record in records if record.path != "/robots.txt"]

    if non_robots:
        return non_robots[1:]

    return []


def calculate_minimum_gap(
    records: list[RequestRecord],
) -> float | None:
    crawler_records = crawler_page_records(records)

    if len(crawler_records) < 2:
        return None

    gaps = [
        second.timestamp - first.timestamp
        for first, second in itertools.pairwise(crawler_records)
    ]

    return min(gaps)


def calculate_duplicate_requests(
    records: list[RequestRecord],
) -> int:
    crawler_records = crawler_page_records(records)

    counts: dict[str, int] = {}

    for record in crawler_records:
        counts[record.path] = counts.get(record.path, 0) + 1

    return sum(max(count - 1, 0) for count in counts.values())


def run_crawler(
    url: str,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    environment["DOCSYNC_TEST_MODE"] = "1"

    return subprocess.run(  # nosec B603 - argument list is constructed internally without shell execution
        [
            sys.executable,
            str(PROJECT_ROOT / "main.py"),
            url,
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=240,
    )


def write_report(
    result: TestResult,
) -> Path:
    LOGS_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")

    report_path = LOGS_ROOT / (f"safe_test_{timestamp}.json")

    report_path.write_text(
        json.dumps(
            asdict(result),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    (LOGS_ROOT / "LATEST").write_text(
        str(report_path.resolve()) + "\n",
        encoding="utf-8",
    )

    return report_path


def main() -> int:
    started = time.monotonic()

    result = TestResult(
        started_at=utc_now(),
    )

    SafeFixtureHandler.records = []

    before = markdown_files()
    result.markdown_files_before = len(before)

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        SafeFixtureHandler,
    )

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )

    thread.start()

    raw_host = server.server_address[0]
    host = raw_host.decode() if isinstance(raw_host, bytes) else str(raw_host)
    port = int(server.server_address[1])
    url = f"http://{host}:{port}/docs"

    try:
        completed = run_crawler(url)
    except subprocess.TimeoutExpired as error:
        result.crawler_return_code = 124
        result.issues.append("Crawler exceeded the 240-second local test timeout.")
        result.stdout_tail = (
            (error.stdout or "")[-6000:] if isinstance(error.stdout, str) else ""
        )
        result.stderr_tail = (
            (error.stderr or "")[-6000:] if isinstance(error.stderr, str) else ""
        )
    else:
        result.crawler_return_code = completed.returncode
        result.stdout_tail = completed.stdout[-6000:]
        result.stderr_tail = completed.stderr[-6000:]

        if completed.returncode != 0:
            result.issues.append(
                "Crawler returned a non-zero exit "
                "code during local safety test: "
                f"{completed.returncode}"
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    records = list(SafeFixtureHandler.records)

    result.request_count = len(records)

    result.robots_requested = any(record.path == "/robots.txt" for record in records)

    result.blocked_path_requested = any(record.path == "/blocked" for record in records)

    result.duplicate_requests = calculate_duplicate_requests(records)

    result.minimum_request_gap_seconds = calculate_minimum_gap(records)

    after = markdown_files()

    result.markdown_files_after = len(after)

    result.markdown_files_created = len(after - before)

    result.logs_latest_exists = (PROJECT_ROOT / "logs" / "LATEST").exists()

    if not result.robots_requested:
        result.issues.append("robots.txt was not requested.")

    if result.blocked_path_requested:
        result.issues.append("A robots.txt-disallowed path was requested.")

    if result.duplicate_requests > 0:
        result.issues.append("The same crawler URL was requested more than once.")

    if (
        result.minimum_request_gap_seconds is not None
        and result.minimum_request_gap_seconds < 0.85
    ):
        result.issues.append(
            "Observed crawler request spacing was "
            "below the local crawl-delay threshold."
        )

    if not result.logs_latest_exists:
        result.issues.append("logs/LATEST was not generated.")

    result.finished_at = utc_now()

    result.elapsed_seconds = round(
        time.monotonic() - started,
        3,
    )

    result.status = "passed" if not result.issues else "failed"

    report_path = write_report(result)

    print("DOCSYNC SAFE CRAWL TEST")
    print("=======================")
    print(f"Status: {result.status}")
    print(f"Crawler return code: {result.crawler_return_code}")
    print(f"Requests received: {result.request_count}")
    print(f"robots.txt requested: {result.robots_requested}")
    print(f"Blocked path requested: {result.blocked_path_requested}")
    print(f"Duplicate crawler URL requests: {result.duplicate_requests}")
    print(f"Minimum crawler request gap: {result.minimum_request_gap_seconds}")
    print(f"Markdown files created: {result.markdown_files_created}")
    print(f"logs/LATEST exists: {result.logs_latest_exists}")
    print(f"Explicit local test mode: {result.test_mode_used}")
    print(f"Report: {report_path}")

    if result.issues:
        print()
        print("Issues:")

        for issue in result.issues:
            print(f"- {issue}")

        print()
        print("Crawler stdout tail:")
        print(result.stdout_tail)

        print()
        print("Crawler stderr tail:")
        print(result.stderr_tail)

    return 0 if not result.issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
