from __future__ import annotations

import asyncio
import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from docsync.crawler import run_crawler


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/robots.txt":
            body = b"User-agent: *\nAllow: /\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/docs/start":
            self.send_response(302)
            self.send_header("Location", "/docs/final")
            self.end_headers()
            return

        if self.path == "/docs/final":
            body = b"""<!doctype html>
<html lang="en">
<body>
  <main>
    <h1>Parity fixture</h1>
    <p>Hello <span>DocsSync</span>.</p>
    <pre><code class="language-python">print("ok")</code></pre>
  </main>
</body>
</html>
"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass


def read_manifest(state_dir: Path) -> dict[str, dict[str, str]]:
    files = list(state_dir.glob("*.json"))
    assert len(files) == 1
    return json.loads(files[0].read_text(encoding="utf-8"))


def read_outputs(output_dir: Path) -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(output_dir.glob("*.md"))
    }


def test_python_typescript_redirect_parity(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        start_url = f"http://127.0.0.1:{server.server_port}/docs/start"

        python_output = tmp_path / "python-output"
        python_state = tmp_path / "python-state"
        typescript_output = tmp_path / "typescript-output"
        typescript_state = tmp_path / "typescript-state"

        asyncio.run(
            run_crawler(
                start_url=start_url,
                output_dir=python_output,
                state_dir=python_state,
                language="en",
                max_concurrency=1,
                max_requests=10,
                requests_per_minute=600,
            )
        )

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
                str(typescript_state),
            ],
            cwd=Path(__file__).parents[1] / "typescript",
            check=True,
        )

        assert read_outputs(python_output) == read_outputs(typescript_output)
        assert read_manifest(python_state) == read_manifest(typescript_state)

        second_python_run = subprocess.run(
            [
                "uv",
                "run",
                "docsync",
                "sync",
                start_url,
                "--engine",
                "python",
                "--language",
                "en",
                "--output-dir",
                str(python_output),
                "--state-dir",
                str(python_state),
            ],
            cwd=Path(__file__).parents[1],
            check=True,
            capture_output=True,
            text=True,
        )

        assert "processed=1 saved=0 unchanged=1" in second_python_run.stdout
        assert read_outputs(python_output) == read_outputs(typescript_output)
        assert read_manifest(python_state) == read_manifest(typescript_state)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
