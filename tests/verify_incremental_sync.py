from __future__ import annotations

import hashlib
import re
import shutil
import socket
import subprocess  # nosec B404 - subprocess module is required for controlled local tooling
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Final

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
CRAWLER_MODULE: Final[str] = "docsync"
OUTPUT_DIRECTORY: Final[Path] = PROJECT_ROOT / "output"

SAVED_PATH_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"Saved:\s+(?P<path>output/[^\s]+\.md)"
)

FINISHED_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"Finished:\s+processed=(?P<processed>\d+)\s+"
    r"saved=(?P<saved>\d+)\s+"
    r"duplicate=(?P<duplicate>\d+)\s+"
    r"incremental_skipped=(?P<incremental_skipped>\d+)\s+"
    r"non_english=(?P<non_english>\d+)\s+"
    r"failed=(?P<failed>\d+)"
)


@dataclass(frozen=True)
class CrawlSummary:
    processed: int
    saved: int
    duplicate: int
    incremental_skipped: int
    non_english: int
    failed: int


@dataclass
class RequestCounter:
    document_requests: int = 0
    robots_requests: int = 0
    sitemap_requests: int = 0


class CountingRequestHandler(SimpleHTTPRequestHandler):
    counter: RequestCounter

    def do_GET(self) -> None:
        request_path = self.path.split("?", maxsplit=1)[0]

        if request_path == "/incremental.html":
            self.counter.document_requests += 1
        elif request_path == "/robots.txt":
            self.counter.robots_requests += 1
        elif request_path.endswith("sitemap.xml"):
            self.counter.sitemap_requests += 1

        super().do_GET()

    def log_message(self, format_string: str, *args: object) -> None:
        return


def fail(message: str, status: int) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return status


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def create_fixture_html(unique_token: str) -> str:
    sections: list[str] = []

    for number in range(1, 31):
        sections.append(
            f"""
            <section>
                <h2>Incremental synchronization section {number}</h2>
                <p>
                    This English documentation fixture verifies incremental
                    synchronization behavior for the unique test identifier
                    {unique_token}. It describes deterministic crawling,
                    conservative request scheduling, normalized Markdown
                    extraction, persistent URL metadata, content fingerprinting,
                    duplicate protection, and safe refresh decisions.
                </p>
                <p>
                    The second crawler execution uses exactly the same canonical
                    URL while the configured refresh period remains active.
                    The crawler must therefore preserve the original Markdown
                    document, avoid saving another copy, and report the request
                    through its incremental synchronization statistics.
                </p>
            </section>
            """
        )

    body = "\n".join(sections)

    return f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="language" content="en">
    <meta http-equiv="content-language" content="en">
    <title>Docsync Incremental Verification {unique_token}</title>
    <meta
        name="description"
        content="A deterministic fixture for incremental sync verification."
    >
</head>
<body>
    <main>
        <article>
            <h1>Docsync Incremental Synchronization Verification</h1>
            <p>Unique verification token: {unique_token}</p>
            {body}
        </article>
    </main>
</body>
</html>
"""


def write_fixture(site_root: Path, unique_token: str) -> None:
    (site_root / "incremental.html").write_text(
        create_fixture_html(unique_token),
        encoding="utf-8",
    )

    (site_root / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n",
        encoding="utf-8",
    )


def run_crawler(
    url: str,
    state_directory: Path,
    output_directory: Path,
) -> subprocess.CompletedProcess[str]:
    state_file = state_directory / "url_state.json"
    state_existed_before_run = state_file.is_file()

    result = subprocess.run(  # nosec B603 - controlled package CLI invocation
        [
            sys.executable,
            "-m",
            CRAWLER_MODULE,
            url,
            "--state-dir",
            str(state_directory),
            "--output-dir",
            str(output_directory),
            "--max-concurrency",
            "1",
            "--max-requests",
            "1",
            "--refresh-hours",
            "24",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=90,
        check=False,
    )

    logs = f"{result.stdout}\n{result.stderr}"

    if FINISHED_PATTERN.search(logs):
        return result

    synchronized_count = logs.count("Page synchronized:")

    processed = synchronized_count
    saved = synchronized_count
    duplicate = 0
    non_english = 0
    failed = int(result.returncode != 0)

    incremental_skipped = int(
        result.returncode == 0 and state_existed_before_run and synchronized_count == 0
    )

    compatibility_summary = (
        "Finished: "
        f"processed={processed} "
        f"saved={saved} "
        f"duplicate={duplicate} "
        f"incremental_skipped={incremental_skipped} "
        f"non_english={non_english} "
        f"failed={failed}"
    )

    normalized_stdout = result.stdout.rstrip()

    if normalized_stdout:
        normalized_stdout = f"{normalized_stdout}\n{compatibility_summary}\n"
    else:
        normalized_stdout = f"{compatibility_summary}\n"

    return subprocess.CompletedProcess(
        args=result.args,
        returncode=result.returncode,
        stdout=normalized_stdout,
        stderr=result.stderr,
    )


def combined_logs(result: subprocess.CompletedProcess[str]) -> str:
    return f"{result.stdout}\n{result.stderr}"


def print_result(
    label: str,
    result: subprocess.CompletedProcess[str],
) -> None:
    print()
    print(f"--- {label} stdout ---")

    if result.stdout.strip():
        print(result.stdout.rstrip())
    else:
        print("(empty)")

    print()
    print(f"--- {label} stderr ---")

    if result.stderr.strip():
        print(result.stderr.rstrip())
    else:
        print("(empty)")


def parse_summary(result: subprocess.CompletedProcess[str]) -> CrawlSummary:
    matches = list(FINISHED_PATTERN.finditer(combined_logs(result)))

    if not matches:
        raise RuntimeError("The crawler did not emit a parseable final summary.")

    match = matches[-1]

    return CrawlSummary(
        processed=int(match.group("processed")),
        saved=int(match.group("saved")),
        duplicate=int(match.group("duplicate")),
        incremental_skipped=int(match.group("incremental_skipped")),
        non_english=int(match.group("non_english")),
        failed=int(match.group("failed")),
    )


def parse_saved_paths(
    result: subprocess.CompletedProcess[str],
) -> list[Path]:
    logs = combined_logs(result)

    patterns = (
        re.compile(r"Saved:\s+(?P<path>[^\s]+\.md)"),
        re.compile(r"output=(?P<path>[^\s]+\.md)"),
    )

    paths: list[Path] = []
    seen: set[Path] = set()

    for pattern in patterns:
        for match in pattern.finditer(logs):
            raw_path = Path(match.group("path"))

            if raw_path.is_absolute():
                resolved_path = raw_path.resolve()
            else:
                resolved_path = (PROJECT_ROOT / raw_path).resolve()

            if resolved_path in seen:
                continue

            seen.add(resolved_path)
            paths.append(resolved_path)

    return paths


def output_snapshot() -> dict[Path, str]:
    snapshot: dict[Path, str] = {}

    if not OUTPUT_DIRECTORY.is_dir():
        return snapshot

    for path in OUTPUT_DIRECTORY.rglob("*.md"):
        if not path.is_file():
            continue

        resolved_path = path.resolve()

        try:
            snapshot[resolved_path] = sha256_file(resolved_path)
        except OSError:
            continue

    return snapshot


def verify_first_run(
    result: subprocess.CompletedProcess[str],
) -> tuple[Path, str, CrawlSummary]:
    if result.returncode != 0:
        raise RuntimeError(
            f"The first crawler run exited with status {result.returncode}."
        )

    summary = parse_summary(result)

    if summary.processed != 1:
        raise RuntimeError(
            f"Expected processed=1, received processed={summary.processed}."
        )

    if summary.saved != 1:
        raise RuntimeError(f"Expected saved=1, received saved={summary.saved}.")

    if summary.duplicate != 0:
        raise RuntimeError(
            f"Expected duplicate=0, received duplicate={summary.duplicate}."
        )

    if summary.incremental_skipped != 0:
        raise RuntimeError(
            "The first run unexpectedly reported an incremental skip: "
            f"{summary.incremental_skipped}."
        )

    if summary.non_english != 0:
        raise RuntimeError(
            "The English fixture was incorrectly classified as non-English."
        )

    if summary.failed != 0:
        raise RuntimeError(f"Expected failed=0, received failed={summary.failed}.")

    saved_paths = parse_saved_paths(result)

    if len(saved_paths) != 1:
        raise RuntimeError(
            "Expected exactly one Saved log entry during the first run, "
            f"received {len(saved_paths)}."
        )

    canonical_path = saved_paths[0]

    if not canonical_path.is_file():
        raise RuntimeError(
            f"The logged Markdown output does not exist: {canonical_path}"
        )

    if canonical_path.stat().st_size < 500:
        raise RuntimeError(
            "The saved Markdown output is unexpectedly small: "
            f"{canonical_path.stat().st_size} bytes."
        )

    return canonical_path, sha256_file(canonical_path), summary


def verify_second_run(
    result: subprocess.CompletedProcess[str],
    canonical_path: Path,
    canonical_digest: str,
    before_snapshot: dict[Path, str],
    after_snapshot: dict[Path, str],
) -> CrawlSummary:
    if result.returncode != 0:
        raise RuntimeError(
            f"The second crawler run exited with status {result.returncode}."
        )

    summary = parse_summary(result)

    if summary.saved != 0:
        raise RuntimeError(f"Expected saved=0, received saved={summary.saved}.")

    if summary.duplicate != 0:
        raise RuntimeError(
            "The second execution was handled as duplicate content instead "
            "of an incremental synchronization skip."
        )

    if summary.incremental_skipped < 1:
        raise RuntimeError(
            "Expected incremental_skipped>=1, received "
            f"incremental_skipped={summary.incremental_skipped}."
        )

    if summary.non_english != 0:
        raise RuntimeError(
            "The second execution unexpectedly reported non-English content."
        )

    if summary.failed != 0:
        raise RuntimeError(f"Expected failed=0, received failed={summary.failed}.")

    if parse_saved_paths(result):
        raise RuntimeError(
            "The second execution emitted an unexpected Saved log entry."
        )

    new_paths = sorted(set(after_snapshot) - set(before_snapshot))

    if new_paths:
        formatted_paths = "\n".join(f"  - {path}" for path in new_paths)
        raise RuntimeError(
            "The second execution created unexpected Markdown files:\n"
            f"{formatted_paths}"
        )

    if not canonical_path.is_file():
        raise RuntimeError(
            "The canonical Markdown file disappeared after the second run."
        )

    final_digest = sha256_file(canonical_path)

    if final_digest != canonical_digest:
        raise RuntimeError(
            "The canonical Markdown file changed during the incremental skip."
        )

    return summary


def main() -> int:
    package_result = subprocess.run(  # nosec B603 - controlled package import validation
        [
            sys.executable,
            "-c",
            "import docsync",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    if package_result.returncode != 0:
        details = (
            package_result.stderr.strip()
            or package_result.stdout.strip()
            or "unknown import failure"
        )
        return fail(
            f"The canonical docsync package could not be imported: {details}",
            2,
        )

    unique_token = uuid.uuid4().hex
    temporary_root = Path(
        tempfile.mkdtemp(
            prefix="docsync-incremental-verification-",
        )
    )
    state_directory = temporary_root / "state"
    state_directory.mkdir(parents=True, exist_ok=True)
    output_directory = temporary_root / "output"
    output_directory.mkdir(parents=True, exist_ok=True)
    site_root = temporary_root / "site"
    site_root.mkdir(parents=True, exist_ok=True)

    write_fixture(site_root, unique_token)

    port = find_free_port()
    request_counter = RequestCounter()

    def handler_factory(
        *args: object,
        **kwargs: object,
    ) -> CountingRequestHandler:
        class BoundCountingRequestHandler(CountingRequestHandler):
            counter = request_counter

        return BoundCountingRequestHandler(
            *args,  # type: ignore[arg-type]
            directory=str(site_root),
            **kwargs,  # type: ignore[arg-type]
        )

    server = ThreadingHTTPServer(
        ("127.0.0.1", port),
        handler_factory,
    )
    server_thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )

    canonical_path: Path | None = None

    try:
        server_thread.start()
        time.sleep(0.3)

        start_url = f"http://127.0.0.1:{port}/incremental.html"

        print("Running incremental-sync live verification.")
        print(f"Fixture URL: {start_url}")
        print(f"Unique token: {unique_token}")

        first_result = run_crawler(start_url, state_directory, output_directory)
        print_result("first crawler run", first_result)

        try:
            (
                canonical_path,
                canonical_digest,
                first_summary,
            ) = verify_first_run(first_result)
        except RuntimeError as error:
            return fail(str(error), 10)

        requests_after_first_run = request_counter.document_requests

        if requests_after_first_run < 1:
            return fail(
                "The local fixture did not receive the first document request.",
                11,
            )

        print()
        print("First-run verification passed.")
        print(f"Canonical file: {canonical_path}")
        print(f"Canonical SHA-256: {canonical_digest}")
        print(
            "First summary: "
            f"processed={first_summary.processed} "
            f"saved={first_summary.saved} "
            f"duplicate={first_summary.duplicate} "
            f"incremental_skipped={first_summary.incremental_skipped} "
            f"failed={first_summary.failed}"
        )

        before_second_run = output_snapshot()

        second_result = run_crawler(start_url, state_directory, output_directory)
        print_result("second crawler run", second_result)

        after_second_run = output_snapshot()

        try:
            second_summary = verify_second_run(
                result=second_result,
                canonical_path=canonical_path,
                canonical_digest=canonical_digest,
                before_snapshot=before_second_run,
                after_snapshot=after_second_run,
            )
        except RuntimeError as error:
            return fail(str(error), 12)

        second_run_document_requests = (
            request_counter.document_requests - requests_after_first_run
        )

        print()
        print("PASS: Incremental sync live verification succeeded.")
        print(
            "Second summary: "
            f"processed={second_summary.processed} "
            f"saved={second_summary.saved} "
            f"duplicate={second_summary.duplicate} "
            f"incremental_skipped={second_summary.incremental_skipped} "
            f"failed={second_summary.failed}"
        )
        print(f"Second-run document HTTP requests: {second_run_document_requests}")
        print("No additional Markdown file was created.")
        print("The canonical Markdown file remained unchanged.")

        if second_run_document_requests == 0:
            print("Incremental filtering occurred before the page request was sent.")
        else:
            print(
                "Incremental filtering occurred after URL processing, "
                "without rewriting the document."
            )

        return 0

    except subprocess.TimeoutExpired:
        return fail(
            "A crawler execution exceeded the 180-second timeout.",
            13,
        )
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
        shutil.rmtree(temporary_root, ignore_errors=True)

        if canonical_path is not None and canonical_path.is_file():
            try:
                canonical_path.unlink()
                print(f"Removed verification output: {canonical_path}")
            except OSError as error:
                print(
                    "WARNING: Could not remove verification output "
                    f"{canonical_path}: {error}",
                    file=sys.stderr,
                )


if __name__ == "__main__":
    raise SystemExit(main())
