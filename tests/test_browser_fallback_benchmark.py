"""Architecture contracts for the Playwright fallback benchmark."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDERING_PATH = ROOT / "src" / "docsync" / "playwright_rendering.py"
BENCHMARK_PATH = ROOT / "tools" / "benchmark_browser_fallback.py"


def test_fallback_renderer_owns_crawler_construction() -> None:
    tree = ast.parse(
        RENDERING_PATH.read_text(encoding="utf-8"),
        filename=str(RENDERING_PATH),
    )

    renderer_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "PlaywrightFallbackRenderer"
    )

    constructors = [
        node
        for node in ast.walk(renderer_class)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "PlaywrightCrawler"
    ]

    assert len(constructors) == 1


def test_benchmark_measures_production_fallback_without_changing_it() -> None:
    source = BENCHMARK_PATH.read_text(encoding="utf-8")

    assert "PlaywrightFallbackRenderer(" in source
    assert "renderer.render(url)" in source
    assert '"mode": "production-reused-renderer"' in source
    assert "time.perf_counter()" in source
