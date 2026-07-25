"""Pure URL host and path helpers for crawler discovery."""

from __future__ import annotations

from urllib.parse import urlparse


def normalized_host(url: str) -> str:
    """Return a lowercase host without a leading www label."""

    return urlparse(url).netloc.lower().removeprefix("www.")


def normalized_path(url: str) -> str:
    """Return a normalized absolute URL path."""

    path = urlparse(url).path or "/"

    if path != "/":
        path = path.rstrip("/")

    return path or "/"


def path_segments(path: str) -> tuple[str, ...]:
    """Return non-empty path segments."""

    return tuple(part for part in path.split("/") if part)


def path_from_segments(segments: tuple[str, ...]) -> str:
    """Build an absolute path from normalized segments."""

    if not segments:
        return "/"

    return "/" + "/".join(segments)


def path_is_inside_prefix(path: str, prefix: str) -> bool:
    """Return whether a path is equal to or below a prefix boundary."""

    normalized_candidate = path.rstrip("/") or "/"
    normalized_prefix = prefix.rstrip("/") or "/"

    if normalized_prefix == "/":
        return True

    return (
        normalized_candidate == normalized_prefix
        or normalized_candidate.startswith(normalized_prefix + "/")
        or normalized_candidate.startswith(normalized_prefix + ".")
    )


def common_path_prefix(paths: list[str]) -> str | None:
    """Return the longest non-root path shared by supplied paths."""

    unique_segments = {path_segments(path) for path in paths if path and path != "/"}

    if len(unique_segments) < 2:
        return None

    ordered = sorted(unique_segments)
    first = ordered[0]
    last = ordered[-1]
    shared: list[str] = []

    for left, right in zip(first, last, strict=False):
        if left != right:
            break

        shared.append(left)

    if not shared:
        return None

    return path_from_segments(tuple(shared))


def source_branch_candidates(source_url: str) -> list[str]:
    """Return source-ancestor branches ordered deepest first.

    For a document-like source URL, the final path component is excluded.
    For a directory URL ending in a slash, the directory itself is included.
    """

    parsed = urlparse(source_url)
    source_path = normalized_path(source_url)
    segments = path_segments(source_path)

    if not segments:
        return []

    if parsed.path.endswith("/"):
        deepest_size = len(segments)
    else:
        deepest_size = len(segments) - 1

    if deepest_size <= 0:
        return []

    return [path_from_segments(segments[:size]) for size in range(deepest_size, 0, -1)]


def same_host_real_paths(
    *,
    base_url: str,
    links: list[str],
) -> list[str]:
    """Return unique same-host paths from real extracted links."""

    base_host = normalized_host(base_url)
    paths: list[str] = []
    seen: set[str] = set()

    for link in links:
        if normalized_host(link) != base_host:
            continue

        path = normalized_path(link)

        if path in seen:
            continue

        seen.add(path)
        paths.append(path)

    return paths


def discovery_path_prefix(base_url: str) -> str:
    """Return the host-safe bootstrap path before scope learning."""

    del base_url
    return "/"
