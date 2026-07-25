"""Dynamic path-scope inference and policy construction for discovery."""

from __future__ import annotations

from urllib.parse import urlparse

from crawler.discovery_paths import (
    discovery_path_prefix,
    normalized_host,
    path_is_inside_prefix,
    same_host_real_paths,
    source_branch_candidates,
)
from crawler.policy_engine import SmartScopePolicy

DISCOVERY_MIN_BRANCH_LINKS = 2
ROOT_PATH_PREFIX = "/"


def branch_support_count(
    branch_prefix: str,
    real_paths: list[str],
) -> int:
    """Count unique real paths contained by one candidate branch."""

    return sum(
        1
        for path in real_paths
        if path_is_inside_prefix(
            path,
            branch_prefix,
        )
    )


def source_is_host_root(source_url: str) -> bool:
    """Return whether the fetched source represents the host root."""

    path = urlparse(source_url).path
    return path in {"", ROOT_PATH_PREFIX}


def infer_scope_prefix_from_real_links(
    *,
    base_url: str,
    source_url: str,
    links: list[str],
) -> str | None:
    """Infer the deepest source branch supported by real HTML links.

    Scope evidence is restricted to links from the same host. Candidate
    branches are ancestors of the fetched source page, ordered deepest first.
    The first branch containing multiple real links becomes the proposal.

    A host-root source explicitly proposes the root path when multiple
    same-host real links exist. This bootstraps documentation sites whose
    primary pages are sibling directories directly beneath the host root.
    """

    if normalized_host(source_url) != normalized_host(base_url):
        return None

    real_paths = same_host_real_paths(
        base_url=base_url,
        links=links,
    )

    if len(real_paths) < DISCOVERY_MIN_BRANCH_LINKS:
        return None

    if source_is_host_root(source_url):
        return ROOT_PATH_PREFIX

    for branch_prefix in source_branch_candidates(source_url):
        support = branch_support_count(
            branch_prefix,
            real_paths,
        )

        if support >= DISCOVERY_MIN_BRANCH_LINKS:
            return branch_prefix

    return None


def merge_scope_prefixes(
    current_prefix: str | None,
    proposed_prefix: str,
) -> str | None:
    """Return a safe relationship-based scope merge result.

    A narrower proposal does not narrow an established scope. A broader
    ancestor proposal may widen it. Unrelated branches are rejected.
    """

    if current_prefix is None:
        return proposed_prefix

    if path_is_inside_prefix(
        proposed_prefix,
        current_prefix,
    ):
        return current_prefix

    if path_is_inside_prefix(
        current_prefix,
        proposed_prefix,
    ):
        return proposed_prefix

    return None


def build_discovery_policy(
    base_url: str,
    *,
    allowed_path_prefix: str | None = None,
) -> SmartScopePolicy:
    """Build crawler policy with an explicit or bootstrap path boundary."""

    return SmartScopePolicy(
        start_url=base_url,
        allowed_path_prefix=(allowed_path_prefix or discovery_path_prefix(base_url)),
    )


def discovery_allowed_real_link(
    base_url: str,
    candidate_url: str,
) -> tuple[bool, str]:
    """Evaluate one real candidate using seed-branch evidence."""

    proposed_prefix = infer_scope_prefix_from_real_links(
        base_url=base_url,
        source_url=base_url,
        links=[candidate_url],
    )

    if proposed_prefix is None:
        return False, "insufficient_same_branch_evidence"

    result = build_discovery_policy(
        base_url,
        allowed_path_prefix=proposed_prefix,
    ).evaluate_url(candidate_url)

    return result.allowed, result.reason
