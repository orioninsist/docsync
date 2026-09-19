"""Architecture contracts for the Playwright fallback benchmark."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDERING_PATH = ROOT / "src" / "docsync" / "playwright_rendering.py"
BENCHMARK_PATH = ROOT / "tools" / "benchmark_browser_fallback.py"


def test_fallback_currently_constructs_crawler_per_render_call() -> None:
    tree = ast.parse(
        RENDERING_PATH.read_text(encoding="utf-8"),
        filename=str(RENDERING_PATH),
    )

    render_function = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "render_url_with_crawlee"
    )

    constructors = [
        node
        for node in ast.walk(render_function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "PlaywrightCrawler"
    ]

    assert len(constructors) == 1


def test_benchmark_measures_production_fallback_without_changing_it() -> None:
    source = BENCHMARK_PATH.read_text(encoding="utf-8")

    assert "render_url_with_crawlee(" in source
    assert '"mode": "production-per-call-crawler"' in source
    assert "time.perf_counter()" in source
