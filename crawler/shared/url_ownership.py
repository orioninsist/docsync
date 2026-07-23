"""Shared URL ownership decision behavior for crawler services."""

from __future__ import annotations

import logging
from pathlib import Path

from crawler.global_url_registry import GlobalUrlRegistry


def claim_url_ownership(
    *,
    url: str,
    registry: GlobalUrlRegistry,
    owner_project: str,
    owner_project_dir: Path,
    logger: logging.Logger,
) -> bool:
    """Claim a URL and report rejection when another project owns it."""

    result = registry.claim_or_check(
        raw_url=url,
        owner_project=owner_project,
        owner_project_dir=owner_project_dir,
    )

    if result.allowed:
        return True

    logger.warning(
        (
            "Blocked URL owned by another project: "
            "url=%s normalized_url=%s owner_project=%s status=%s"
        ),
        url,
        result.normalized_url,
        result.owner_project,
        result.status,
    )
    print(result.message, flush=True)
    return False
