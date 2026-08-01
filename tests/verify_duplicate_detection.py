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
from dataclasses import dataclass
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Final

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
MAIN_FILE: Final[Path] = PROJECT_ROOT / "main.py"
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


class QuietRequestHandler(SimpleHTTPRequestHandler):
    def log_message(self, format_string: str, *args: object) -> None:
        return


def fail(message: str, status: int) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return status


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def create_document_body() -> str:
    paragraphs: list[str] = []

    for number in range(1, 31):
        paragraphs.append(
            f"""
            <section>
                <h2>Reliable documentation section {number}</h2>
                <p>
                    This documentation section explains deterministic web
                    crawling, conservative request scheduling, normalized
                    Markdown extraction, English language validation,
                    persistent storage, content fingerprinting, duplicate
                    detection, safe URL processing, incremental synchronization,
                    and reliable recovery behavior.
                </p>
                <p>
                    The document deliberately contains substantial natural
                    English prose so that production content validation accepts
                    it. Both fixture URLs serve exactly the same HTML bytes,
                    title, headings, paragraphs, metadata, and document
                    structure. Only the requested URL path differs.
                </p>
            </section>
            """
        )

    return "\n".join(paragraphs)


def write_fixture(site_root: Path) -> None:
    body = create_document_body()

    identical_html = f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="language" content="en">
    <meta http-equiv="content-language" content="en">
    <title>Docsync Canonical Duplicate Document</title>
    <meta
        name="description"
        content="A deterministic English fixture for duplicate detection."
    >
</head>
<body>
    <main>
        <article>
            <h1>Docsync Canonical Duplicate Document</h1>
            <p>
                This canonical fixture is intentionally available from two
                separate URLs while returning byte-identical HTML content.
            </p>
            {body}
        </article>
    </main>
</body>
</html>
"""

    robots_txt = """User-agent: *
Allow: /
"""

    (site_root / "duplicate-a.html").write_text(
        identical_html,
        encoding="utf-8",
    )
    (site_root / "duplicate-b.html").write_text(
        identical_html,
        encoding="utf-8",
    )
    (site_root / "robots.txt").write_text(
        robots_txt,
        encoding="utf-8",
    )


def run_crawler(url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 - argument list is constructed internally without shell execution
        [
            sys.executable,
            str(MAIN_FILE),
            url,
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
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
    logs = combined_logs(result)
    matches = list(FINISHED_PATTERN.finditer(logs))

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
    paths: list[Path] = []

    for match in SAVED_PATH_PATTERN.finditer(combined_logs(result)):
        relative_path = Path(match.group("path"))
        absolute_path = (PROJECT_ROOT / relative_path).resolve()
        paths.append(absolute_path)

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


def remove_previous_fixture_outputs() -> None:
    if not OUTPUT_DIRECTORY.is_dir():
        return

    prefixes = (
        "duplicate-a.html-",
        "duplicate-b.html-",
    )

    for path in OUTPUT_DIRECTORY.glob("*.md"):
        if not path.name.startswith(prefixes):
            continue

        path.unlink()
        print(f"Removed previous fixture output: {path}")


def verify_first_run(
    result: subprocess.CompletedProcess[str],
) -> tuple[Path, str]:
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

    if summary.failed != 0:
        raise RuntimeError(f"Expected failed=0, received failed={summary.failed}.")

    saved_paths = parse_saved_paths(result)

    if len(saved_paths) != 1:
        raise RuntimeError(
            "Expected exactly one Saved log entry during the first run, "
            f"received {len(saved_paths)}."
        )

    saved_path = saved_paths[0]

    if not saved_path.is_file():
        raise RuntimeError(f"The logged Markdown output does not exist: {saved_path}")

    if saved_path.stat().st_size < 500:
        raise RuntimeError(
            f"The saved Markdown document is unexpectedly small: "
            f"{saved_path.stat().st_size} bytes."
        )

    return saved_path, sha256_file(saved_path)


def verify_second_run(
    result: subprocess.CompletedProcess[str],
    canonical_path: Path,
    canonical_digest: str,
    before_second_run: dict[Path, str],
    after_second_run: dict[Path, str],
) -> None:
    if result.returncode != 0:
        raise RuntimeError(
            f"The second crawler run exited with status {result.returncode}."
        )

    summary = parse_summary(result)

    if summary.processed != 1:
        raise RuntimeError(
            f"Expected processed=1, received processed={summary.processed}."
        )

    if summary.saved != 0:
        raise RuntimeError(f"Expected saved=0, received saved={summary.saved}.")

    if summary.duplicate != 1:
        raise RuntimeError(
            f"Expected duplicate=1, received duplicate={summary.duplicate}."
        )

    if summary.failed != 0:
        raise RuntimeError(f"Expected failed=0, received failed={summary.failed}.")

    second_saved_paths = parse_saved_paths(result)

    if second_saved_paths:
        formatted_paths = "\n".join(f"  - {path}" for path in second_saved_paths)
        raise RuntimeError(
            f"The duplicate run emitted unexpected Saved entries:\n{formatted_paths}"
        )

    new_paths = sorted(set(after_second_run) - set(before_second_run))

    if new_paths:
        formatted_paths = "\n".join(f"  - {path}" for path in new_paths)
        raise RuntimeError(
            f"The duplicate run created unexpected Markdown files:\n{formatted_paths}"
        )

    if not canonical_path.is_file():
        raise RuntimeError(
            "The canonical Markdown file disappeared after the duplicate run."
        )

    final_digest = sha256_file(canonical_path)

    if final_digest != canonical_digest:
        raise RuntimeError(
            "The canonical Markdown file changed during the duplicate run."
        )


def main() -> int:
    if not MAIN_FILE.is_file():
        return fail(f"main.py was not found at {MAIN_FILE}", 2)

    temporary_root = Path(
        tempfile.mkdtemp(
            prefix="docsync-duplicate-verification-",
        )
    )
    site_root = temporary_root / "site"
    site_root.mkdir(parents=True, exist_ok=True)

    write_fixture(site_root)

    port = find_free_port()

    def handler_factory(
        *args: object,
        **kwargs: object,
    ) -> QuietRequestHandler:
        return QuietRequestHandler(
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

    try:
        remove_previous_fixture_outputs()

        server_thread.start()
        time.sleep(0.3)

        first_url = f"http://127.0.0.1:{port}/duplicate-a.html"
        second_url = f"http://127.0.0.1:{port}/duplicate-b.html"

        print("Running duplicate-detection live verification.")
        print(f"First URL:  {first_url}")
        print(f"Second URL: {second_url}")
        print("Both URLs serve byte-identical HTML content.")

        first_result = run_crawler(first_url)
        print_result("first crawler run", first_result)

        try:
            canonical_path, canonical_digest = verify_first_run(first_result)
        except RuntimeError as error:
            return fail(str(error), 10)

        print()
        print("First-run verification passed.")
        print(f"Canonical file: {canonical_path}")
        print(f"Canonical SHA-256: {canonical_digest}")

        before_second_run = output_snapshot()

        second_result = run_crawler(second_url)
        print_result("second crawler run", second_result)

        after_second_run = output_snapshot()

        try:
            verify_second_run(
                result=second_result,
                canonical_path=canonical_path,
                canonical_digest=canonical_digest,
                before_second_run=before_second_run,
                after_second_run=after_second_run,
            )
        except RuntimeError as error:
            return fail(str(error), 11)

        print()
        print("PASS: Duplicate detection live verification succeeded.")
        print("First URL: processed=1 saved=1 duplicate=0 failed=0")
        print("Second URL: processed=1 saved=0 duplicate=1 failed=0")
        print("No additional Markdown file was created.")
        print("The canonical Markdown file remained unchanged.")

        return 0

    except subprocess.TimeoutExpired:
        return fail(
            "A crawler execution exceeded the 180-second timeout.",
            12,
        )
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
        shutil.rmtree(temporary_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
