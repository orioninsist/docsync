from __future__ import annotations

import hashlib
import http.server
import os
import re
import shutil
import socket
import subprocess  # nosec B404 - subprocess module is required for controlled local tooling
import tempfile
import threading
import time
from pathlib import Path
from typing import Final

PROJECT_ROOT: Final = Path("/mnt/local/areas/docsync")
MAIN_FILE: Final = PROJECT_ROOT / "main.py"
OUTPUT_DIR: Final = PROJECT_ROOT / "output"
STORAGE_DIR: Final = PROJECT_ROOT / "storage"

VISIBLE_TOKEN: Final = "DOCSYNC_STATIC_CONTENT"
JAVASCRIPT_TOKEN: Final = (
    "DOCSYNC_JAVASCRIPT_RENDERED_"
    + hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:24]
)

SUMMARY_PATTERN: Final = re.compile(
    r"Finished:\s+"
    r"processed=(?P<processed>\d+)\s+"
    r"saved=(?P<saved>\d+)\s+"
    r"duplicate=(?P<duplicate>\d+)\s+"
    r"incremental_skipped=(?P<incremental_skipped>\d+)\s+"
    r"non_english=(?P<non_english>\d+)\s+"
    r"failed=(?P<failed>\d+)"
)


class QuietRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


def reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run_command(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    effective_env = os.environ.copy()

    if env:
        effective_env.update(env)

    return subprocess.run(  # nosec B603 - argument list is constructed internally without shell execution
        command,
        cwd=PROJECT_ROOT,
        env=effective_env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def print_process_result(
    title: str,
    result: subprocess.CompletedProcess[str],
) -> None:
    print()
    print(f"--- {title} stdout ---")
    print(result.stdout.rstrip() or "(empty)")
    print()
    print(f"--- {title} stderr ---")
    print(result.stderr.rstrip() or "(empty)")
    print()
    print(f"Exit status: {result.returncode}")


def get_help_text() -> str:
    result = run_command(
        ["uv", "run", "python", str(MAIN_FILE), "--help"],
        timeout=60,
    )

    return f"{result.stdout}\n{result.stderr}"


def detect_javascript_invocations(
    fixture_url: str,
    help_text: str,
) -> list[tuple[str, list[str], dict[str, str]]]:
    invocations: list[tuple[str, list[str], dict[str, str]]] = []
    base = ["uv", "run", "python", str(MAIN_FILE), fixture_url]
    lowered = help_text.lower()

    mode_match = re.search(
        r"--mode(?:\s+\{([^}]+)\}|\s+[\w-]+)",
        help_text,
        flags=re.IGNORECASE,
    )

    if mode_match and mode_match.group(1):
        choices = [
            value.strip() for value in mode_match.group(1).split(",") if value.strip()
        ]

        preferred = (
            "javascript",
            "browser",
            "playwright",
            "js",
            "dynamic",
        )

        for wanted in preferred:
            for choice in choices:
                if choice.lower() == wanted:
                    invocations.append(
                        (
                            f"--mode {choice}",
                            [*base, "--mode", choice],
                            {},
                        )
                    )

    explicit_flags = (
        "--javascript",
        "--js",
        "--browser",
        "--playwright",
        "--render-javascript",
        "--javascript-rendering",
    )

    for flag in explicit_flags:
        if flag in lowered:
            invocations.append((flag, [*base, flag], {}))

    environment_candidates = (
        ("DOCSYNC_MODE", "javascript"),
        ("DOCSYNC_MODE", "browser"),
        ("DOCSYNC_CRAWLER_MODE", "javascript"),
        ("DOCSYNC_CRAWLER_MODE", "browser"),
        ("CRAWLER_MODE", "javascript"),
        ("CRAWLER_MODE", "browser"),
        ("RENDER_JAVASCRIPT", "1"),
        ("DOCSYNC_RENDER_JAVASCRIPT", "1"),
        ("USE_PLAYWRIGHT", "1"),
    )

    source = MAIN_FILE.read_text(encoding="utf-8", errors="replace")

    for name, value in environment_candidates:
        if name in source:
            invocations.append(
                (
                    f"{name}={value}",
                    base,
                    {name: value},
                )
            )

    common_fallbacks: tuple[
        tuple[str, list[str], dict[str, str]],
        ...,
    ] = (
        ("--mode javascript", [*base, "--mode", "javascript"], {}),
        ("--mode browser", [*base, "--mode", "browser"], {}),
        ("--javascript", [*base, "--javascript"], {}),
    )

    invocations.extend(common_fallbacks)

    unique: list[tuple[str, list[str], dict[str, str]]] = []
    seen: set[tuple[tuple[str, ...], tuple[tuple[str, str], ...]]] = set()

    for label, command, env in invocations:
        key = (tuple(command), tuple(sorted(env.items())))

        if key in seen:
            continue

        seen.add(key)
        unique.append((label, command, env))

    return unique


def remove_test_artifacts() -> None:
    if STORAGE_DIR.exists():
        shutil.rmtree(STORAGE_DIR)

    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for path in OUTPUT_DIR.glob("javascript-rendering*"):
        if path.is_file():
            path.unlink()


def markdown_files() -> list[Path]:
    if not OUTPUT_DIR.exists():
        return []

    return sorted(path for path in OUTPUT_DIR.glob("*.md") if path.is_file())


def find_token_file(token: str) -> Path | None:
    for path in markdown_files():
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        if token in content:
            return path

    return None


def find_summary(text: str) -> dict[str, int] | None:
    matches = list(SUMMARY_PATTERN.finditer(text))

    if not matches:
        return None

    match = matches[-1]

    return {name: int(value) for name, value in match.groupdict().items()}


def main() -> int:
    if not MAIN_FILE.exists():
        print(f"ERROR: Missing crawler entry point: {MAIN_FILE}")
        return 2

    fixture_root = Path(tempfile.mkdtemp(prefix="docsync-js-fixture-"))
    fixture_file = fixture_root / "javascript-rendering.html"

    fixture_file.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Docsync JavaScript Rendering Verification</title>
</head>
<body>
    <main>
        <h1>{VISIBLE_TOKEN}</h1>
        <div id="render-target">JavaScript has not executed.</div>
    </main>

    <script>
        window.setTimeout(() => {{
            const target = document.getElementById("render-target");
            target.textContent = "{JAVASCRIPT_TOKEN}";
            target.setAttribute("data-rendered", "true");
        }}, 150);
    </script>
</body>
</html>
""",
        encoding="utf-8",
    )

    port = reserve_port()
    fixture_url = f"http://127.0.0.1:{port}/javascript-rendering.html"

    def handler(*args, **kwargs):
        return QuietRequestHandler(
            *args,
            directory=str(fixture_root),
            **kwargs,
        )

    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", port),
        handler,
    )
    server_thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )
    server_thread.start()

    try:
        print("Running JavaScript-rendering live verification.")
        print(f"Fixture URL: {fixture_url}")
        print(f"Static token: {VISIBLE_TOKEN}")
        print(f"JavaScript token: {JAVASCRIPT_TOKEN}")

        help_text = get_help_text()
        invocations = detect_javascript_invocations(
            fixture_url,
            help_text,
        )

        print()
        print("Detected/attempted JavaScript invocation methods:")

        for label, _, env in invocations:
            environment_suffix = (
                " " + " ".join(f"{key}={value}" for key, value in env.items())
                if env
                else ""
            )
            print(f"  - {label}{environment_suffix}")

        failures: list[str] = []

        for index, (label, command, env) in enumerate(invocations, start=1):
            remove_test_artifacts()

            effective_env = {
                "UV_LINK_MODE": "copy",
                "DOCSYNC_FORCE_REFRESH": "1",
                "DOCSYNC_REFRESH_HOURS": "0",
                **env,
            }

            print()
            print(f"Attempt {index}/{len(invocations)}: {label}")

            try:
                result = run_command(
                    command,
                    env=effective_env,
                    timeout=180,
                )
            except subprocess.TimeoutExpired:
                failures.append(f"{label}: timed out")
                print(f"FAIL: {label} timed out.")
                continue

            print_process_result(label, result)

            combined_output = f"{result.stdout}\n{result.stderr}"
            summary = find_summary(combined_output)
            rendered_file = find_token_file(JAVASCRIPT_TOKEN)
            static_file = find_token_file(VISIBLE_TOKEN)

            if result.returncode != 0:
                failures.append(f"{label}: exit status {result.returncode}")
                continue

            if rendered_file is None:
                reason = (
                    "JavaScript token missing"
                    if static_file is not None
                    else "no matching Markdown output"
                )
                failures.append(f"{label}: {reason}")
                continue

            if summary is None:
                failures.append(f"{label}: final summary was not parseable")
                continue

            if summary["failed"] != 0:
                failures.append(f"{label}: summary reported failures")
                continue

            content = rendered_file.read_text(encoding="utf-8")

            if JAVASCRIPT_TOKEN not in content:
                failures.append(f"{label}: rendered token missing from output")
                continue

            print()
            print("PASS: JavaScript rendering live verification succeeded.")
            print(f"Successful invocation: {label}")
            print(f"Rendered Markdown file: {rendered_file}")
            print(
                "Final summary: "
                + " ".join(f"{name}={value}" for name, value in summary.items())
            )

            rendered_file.unlink(missing_ok=True)
            return 0

        print()
        print("ERROR: No JavaScript invocation produced rendered content.")

        for failure in failures:
            print(f"  - {failure}")

        print()
        print("Crawler help output:")
        print(help_text.strip() or "(empty)")
        return 12

    finally:
        server.shutdown()
        server.server_close()
        shutil.rmtree(fixture_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
