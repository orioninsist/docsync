"""Shared URL path-scope boundary calculation."""

from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import urlparse


DOCUMENT_SUFFIXES = frozenset(
    {
        ".html",
        ".htm",
        ".xhtml",
        ".php",
        ".asp",
        ".aspx",
    }
)

DOCUMENT_COLLECTION_DIRECTORIES = frozenset(
    {
        "aliases",
        "classes",
        "enums",
        "functions",
        "interfaces",
        "modules",
        "namespaces",
        "packages",
        "records",
        "structs",
        "traits",
        "types",
    }
)


def _normalized_path_parts(path: str) -> list[str]:
    """Return normalized non-empty URL path segments."""

    return [part for part in path.split("/") if part]


def _path_from_parts(parts: list[str]) -> str:
    """Build a normalized absolute URL path from path segments."""

    if not parts:
        return "/"

    return "/" + "/".join(parts)


def _document_parent_path(path: str) -> str:
    """Return the normalized parent path of a document URL."""

    parent = str(PurePosixPath(path).parent)

    if parent in {"", ".", "/"}:
        return "/"

    return parent


def _is_collection_document_path(path_parts: list[str]) -> bool:
    """Return whether the final segment is a document inside a collection."""

    if len(path_parts) < 2:
        return False

    parent_segment = path_parts[-2].lower()

    return parent_segment in DOCUMENT_COLLECTION_DIRECTORIES


def _is_smithay_duplicate_root(
    *,
    host: str,
    path_parts: list[str],
) -> bool:
    """Return whether Smithay repeats its project name as the final segment."""

    return (
        host == "smithay.github.io"
        and len(path_parts) >= 2
        and path_parts[-1].lower() == path_parts[-2].lower()
    )


def build_allowed_path_prefix(start_url: str) -> str:
    """Return the normalized path boundary shared by all crawl stages.

    Explicit document files are scoped to their parent directory.

    Extensionless API-reference documents under collection directories such
    as ``classes`` or ``enums`` are also scoped to the collection directory.
    This allows sibling API pages without broadening the crawl to the entire
    website.

    Smithay's duplicated project-root URL remains supported as a documented
    compatibility case.
    """

    parsed = urlparse(start_url)
    path = parsed.path.rstrip("/")

    if not path:
        return "/"

    path_parts = _normalized_path_parts(path)

    if not path_parts:
        return "/"

    suffix = PurePosixPath(path).suffix.lower()

    if suffix in DOCUMENT_SUFFIXES:
        return _document_parent_path(path)

    if _is_collection_document_path(path_parts):
        return _path_from_parts(path_parts[:-1])

    if _is_smithay_duplicate_root(
        host=parsed.netloc.lower(),
        path_parts=path_parts,
    ):
        return _path_from_parts(path_parts[:-1])

    return _path_from_parts(path_parts)
