from __future__ import annotations

from docsync.inventory import (
    SiteInventory,
    _inventory_progress_text,
    _print_inventory_progress,
)


def test_inventory_progress_text_contains_all_counters() -> None:
    report = SiteInventory(
        seed_url="https://example.com/docs/",
        english_urls=12,
        non_english_urls=2,
        robots_blocked=3,
        reachable_pages=14,
        not_found_pages=1,
        timeouts=2,
        failed_pages=4,
        processed_urls=26,
    )

    result = _inventory_progress_text(
        report=report,
        discovered_count=80,
        queued_count=54,
    )

    assert "processed=26/80" in result
    assert "queued=54" in result
    assert "reachable=14" in result
    assert "classified=14" in result
    assert "english=12" in result
    assert "non_english=2" in result
    assert "blocked=3" in result
    assert "404=1" in result
    assert "timeouts=2" in result
    assert "failed=4" in result
    assert "problems=10" in result


def test_inventory_progress_prints_immediately(
    capsys,
) -> None:
    report = SiteInventory(
        seed_url="https://example.com/docs/",
        english_urls=3,
        reachable_pages=3,
        processed_urls=5,
    )

    _print_inventory_progress(
        report=report,
        discovered_count=8,
        queued_count=3,
    )

    output = capsys.readouterr().out

    assert output.startswith("Inventory progress | ")
    assert "processed=5/8" in output
    assert "queued=3" in output
    assert output.endswith("\n")
