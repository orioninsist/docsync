"""Discovery policy construction without path-scope restrictions."""

from __future__ import annotations

from crawler.policy_engine import SmartScopePolicy

ROOT_PATH_PREFIX = "/"


def infer_scope_prefix_from_real_links(
    *,
    base_url: str,
    source_url: str,
    links: list[str],
) -> str | None:
    """Return unrestricted root scope when real links are available."""

    del base_url
    del source_url

    if not links:
        return None

    return ROOT_PATH_PREFIX


def merge_scope_prefixes(
    current_prefix: str | None,
    proposed_prefix: str,
) -> str | None:
    """Return unrestricted root scope for every valid proposal."""

    del current_prefix

    if not proposed_prefix:
        return None

    return ROOT_PATH_PREFIX


def build_discovery_policy(
    base_url: str,
    *,
    allowed_path_prefix: str | None = None,
) -> SmartScopePolicy:
    """Build discovery policy without path-prefix filtering."""

    del allowed_path_prefix

    return SmartScopePolicy(start_url=base_url)


def discovery_allowed_real_link(
    base_url: str,
    candidate_url: str,
) -> tuple[bool, str]:
    """Evaluate a real candidate without branch-evidence filtering."""

    result = build_discovery_policy(base_url).evaluate_url(candidate_url)

    return result.allowed, result.reason
