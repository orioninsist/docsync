"""Canonical crawler metrics and reporting wiring contracts."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

ROOT: Final[Path] = Path(__file__).resolve().parents[1]
CRAWLER_PATH: Final[Path] = ROOT / "src/docsync/crawler.py"
CLI_PATH: Final[Path] = ROOT / "src/docsync/cli.py"
MAIN_PATH: Final[Path] = ROOT / "src/docsync/main.py"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _function(
    tree: ast.AST,
    name: str,
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node

    raise AssertionError(f"{name}() was not found")


def _calls(function: ast.AST, name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
        )
    ]


def _augmented_metric_names(function: ast.AST) -> set[str]:
    names: set[str] = set()

    for node in ast.walk(function):
        if not isinstance(node, ast.AugAssign):
            continue

        target = node.target
        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "stats"
        ):
            names.add(target.attr)

    return names


def test_crawler_imports_canonical_metrics() -> None:
    tree = _tree(CRAWLER_PATH)

    imported = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "docsync.metrics"
        for alias in node.names
    }

    assert {"CrawlStats", "write_crawl_report"} <= imported


def test_temporary_incremental_stats_class_is_removed() -> None:
    tree = _tree(CRAWLER_PATH)

    class_names = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}

    assert "_IncrementalRuntimeStats" not in class_names


def test_run_crawler_returns_crawl_stats() -> None:
    run_crawler = _function(_tree(CRAWLER_PATH), "run_crawler")

    assert isinstance(run_crawler.returns, ast.Name)
    assert run_crawler.returns.id == "CrawlStats"

    return_names = {
        node.value.id
        for node in ast.walk(run_crawler)
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Name)
    }

    assert "stats" in return_names


def test_request_handler_records_processed_and_saved() -> None:
    request_handler = _function(_tree(CRAWLER_PATH), "request_handler")
    metric_names = _augmented_metric_names(request_handler)

    assert "processed" in metric_names
    assert "saved" in metric_names


def test_incremental_filter_uses_canonical_stats() -> None:
    run_crawler = _function(_tree(CRAWLER_PATH), "run_crawler")
    calls = _calls(run_crawler, "filter_incremental_urls")

    assert len(calls) == 1

    stats_keywords = [
        keyword.value for keyword in calls[0].keywords if keyword.arg == "stats"
    ]

    assert len(stats_keywords) == 1
    assert isinstance(stats_keywords[0], ast.Name)
    assert stats_keywords[0].id == "stats"


def test_sitemap_metrics_are_recorded() -> None:
    source = CRAWLER_PATH.read_text(encoding="utf-8")

    expected_assignments = {
        "stats.sitemap_urls = len(sitemap_result.urls)",
        "stats.sitemap_files_checked = sitemap_result.sitemap_files_checked",
        "stats.sitemap_files_found = sitemap_result.sitemap_files_found",
        "stats.sitemap_errors = len(sitemap_result.errors)",
    }
    normalized_lines = {line.strip() for line in source.splitlines()}

    assert expected_assignments <= normalized_lines


def test_failed_request_handler_records_failure() -> None:
    failed_handler = _function(_tree(CRAWLER_PATH), "failed_handler")
    metric_names = _augmented_metric_names(failed_handler)

    assert "failed" in metric_names


def test_crawler_writes_report_through_shared_finalizer() -> None:
    run_crawler = _function(_tree(CRAWLER_PATH), "run_crawler")
    finalizer = _function(run_crawler, "finalize_crawl")

    report_calls = _calls(finalizer, "write_crawl_report")
    finalizer_calls = _calls(run_crawler, "finalize_crawl")

    assert len(report_calls) == 1
    assert len(finalizer_calls) == 2

    keyword_names = {
        keyword.arg for keyword in report_calls[0].keywords if keyword.arg is not None
    }

    assert {
        "output_dir",
        "stats",
        "configuration",
    } <= keyword_names


def test_cli_emits_canonical_finished_summary() -> None:
    source = CLI_PATH.read_text(encoding="utf-8")

    assert "isinstance(result, CrawlStats)" in source
    assert "print(result.finished_summary())" in source
    assert "return int(result.exit_code)" in source


def test_main_entrypoint_emits_canonical_finished_summary() -> None:
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert "isinstance(stats, CrawlStats)" in source
    assert "logger.info(stats.finished_summary())" in source
    assert "return int(stats.exit_code)" in source


def test_cli_forwards_incremental_arguments() -> None:
    source = CLI_PATH.read_text(encoding="utf-8")

    assert '"refresh_hours": args.refresh_hours' in source
    assert '"force_refresh": args.force_refresh' in source
