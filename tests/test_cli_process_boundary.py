"""Verify DocsSync CLI uses the native Python crawler."""

from pathlib import Path
import tomllib


def test_python_cli_entrypoint_and_crawler_boundary() -> None:
    root = Path(__file__).resolve().parents[1]

    project = tomllib.loads(
        (root / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert project["project"]["scripts"]["docsync"] == "docsync.cli:main"

    cli = (root / "src/docsync/cli.py").read_text(encoding="utf-8")
    assert "asyncio.run(" in cli
    assert "run_crawler(" in cli

    crawler = (
        root / "src/docsync/crawler.py"
    ).read_text(encoding="utf-8")
    assert "SitemapRequestLoader(" in crawler
    assert "ServiceLocator(" in crawler
