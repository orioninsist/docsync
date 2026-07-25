from __future__ import annotations

from pathlib import Path

from crawler.config import CrawlerConfig
from crawler.runtime_paths import build_runtime_paths
from crawler.scope_prefix import build_allowed_path_prefix
from crawler.source_manifest import SourceManifest
from crawler.url_utils import (
    build_project_slug,
    should_allow_cross_host_discovery,
)

SOURCES_ROOT = Path("sources")


def build_auto_config(
    start_url: str,
    workspace: str | None,
    run_id: str,
) -> CrawlerConfig:
    project_slug = build_project_slug(start_url)
    allowed_path_prefix = build_allowed_path_prefix(start_url)

    project_name = workspace or project_slug
    output_dir = SourceManifest.from_project_name(
        project_name=project_name,
        root_dir=SOURCES_ROOT,
    ).output_dir

    db_path, logs_dir = build_runtime_paths(
        project_slug,
        workspace,
        run_id,
    )

    return CrawlerConfig(
        start_url=start_url,
        allowed_path_prefix=allowed_path_prefix,
        output_dir=output_dir,
        db_path=db_path,
        logs_dir=logs_dir,
        require_english=True,
        recursive_discovery=True,
        use_sitemap_discovery=False,
        auto_continue_until_complete=True,
        allow_official_cross_host_discovery=(
            should_allow_cross_host_discovery(start_url)
        ),
    )
