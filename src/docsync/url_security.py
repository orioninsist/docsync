"""URL validation, normalization, scope, and redirect security."""

from __future__ import annotations

import re
from collections.abc import Collection
from email.message import Message
from pathlib import PurePosixPath
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import (
    parse_qsl,
    urlencode,
    urlsplit,
    urlunsplit,
)

TRACKING_QUERY_KEYS = frozenset(
    {
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
        "ref",
        "referrer",
        "source",
    }
)

DEFAULT_SKIPPED_EXTENSIONS = frozenset(
    {
        ".7z",
        ".avi",
        ".avif",
        ".bin",
        ".bmp",
        ".bz2",
        ".css",
        ".csv",
        ".doc",
        ".docx",
        ".eot",
        ".exe",
        ".gif",
        ".gz",
        ".ico",
        ".iso",
        ".jpeg",
        ".jpg",
        ".js",
        ".json",
        ".m4a",
        ".m4v",
        ".mov",
        ".mp3",
        ".mp4",
        ".mpeg",
        ".mpg",
        ".odp",
        ".ods",
        ".odt",
        ".ogg",
        ".ogv",
        ".otf",
        ".pdf",
        ".png",
        ".ppt",
        ".pptx",
        ".rar",
        ".rss",
        ".svg",
        ".tar",
        ".tgz",
        ".tif",
        ".tiff",
        ".ttf",
        ".wav",
        ".webm",
        ".webp",
        ".woff",
        ".woff2",
        ".xls",
        ".xlsx",
        ".xml",
        ".xz",
        ".zip",
    }
)

DEFAULT_SKIPPED_PATH_PARTS = frozenset(
    {
        "account",
        "admin",
        "auth",
        "cart",
        "checkout",
        "download",
        "downloads",
        "login",
        "logout",
        "register",
        "search",
        "signin",
        "signup",
    }
)


def validated_http_url(value: str) -> str:
    """Validate a credential-free absolute HTTP or HTTPS URL."""

    if not isinstance(value, str):
        raise TypeError("URL must be a string")

    candidate = value.strip()
    parsed = urlsplit(candidate)

    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError(f"Only HTTP and HTTPS URLs are permitted: {value!r}")

    if not parsed.hostname:
        raise ValueError(f"URL has no hostname: {value!r}")

    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs containing embedded credentials are not permitted")

    try:
        validated_port = parsed.port
    except ValueError as error:
        raise ValueError(f"URL contains an invalid port: {value!r}") from error

    del validated_port
    return candidate


def normalized_http_origin(value: str) -> tuple[str, str, int]:
    """Return normalized scheme, hostname, and effective port."""

    validated = validated_http_url(value)
    parsed = urlsplit(validated)

    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").rstrip(".").lower()
    default_port = 443 if scheme == "https" else 80
    port = parsed.port or default_port

    return scheme, hostname, port


class SameOriginRedirectHandler(
    urllib_request.HTTPRedirectHandler,
):
    """Reject unsafe and cross-origin redirects."""

    def __init__(self, initial_url: str) -> None:
        super().__init__()
        self._allowed_origin = normalized_http_origin(initial_url)

    def validate_redirect(self, new_url: str) -> str:
        """Validate one redirect destination before it is followed."""

        validated = validated_http_url(new_url)
        redirect_origin = normalized_http_origin(validated)

        if redirect_origin != self._allowed_origin:
            raise urllib_error.HTTPError(
                validated,
                403,
                "Cross-origin redirect blocked",
                Message(),
                None,
            )

        return validated

    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Any:
        """Validate and delegate an HTTP redirect request."""

        validated_url = self.validate_redirect(newurl)

        return super().redirect_request(
            req,
            fp,
            code,
            msg,
            headers,
            validated_url,
        )


def secure_urlopen(
    target: Any,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Open an HTTP(S) URL while validating every redirect."""

    if isinstance(target, urllib_request.Request):
        initial_url = target.full_url
    else:
        initial_url = str(target)

    validated_url = validated_http_url(initial_url)

    if isinstance(target, urllib_request.Request):
        request_target: Any = target
    else:
        request_target = validated_url

    data = kwargs.pop(
        "data",
        args[0] if len(args) >= 1 else None,
    )
    timeout = kwargs.pop(
        "timeout",
        args[1] if len(args) >= 2 else None,
    )
    context = kwargs.pop("context", None)

    if len(args) > 2:
        raise TypeError(
            "secure_urlopen accepts at most two positional arguments after the URL"
        )

    if kwargs:
        unexpected = ", ".join(sorted(kwargs))
        raise TypeError(f"Unexpected URL open arguments: {unexpected}")

    handlers: list[Any] = [SameOriginRedirectHandler(validated_url)]

    if context is not None:
        handlers.append(urllib_request.HTTPSHandler(context=context))

    opener = urllib_request.build_opener(*handlers)

    return opener.open(
        request_target,
        data=data,
        timeout=timeout,
    )


def normalize_url(url: str) -> str:
    """Normalize a validated URL deterministically."""

    validated = validated_http_url(url)
    parts = urlsplit(validated)

    scheme = parts.scheme.lower()
    hostname = (parts.hostname or "").rstrip(".").lower()

    try:
        port = parts.port
    except ValueError as error:
        raise ValueError(f"URL contains an invalid port: {url!r}") from error

    if (
        port is None
        or (scheme == "http" and port == 80)
        or (scheme == "https" and port == 443)
    ):
        netloc = hostname
    else:
        netloc = f"{hostname}:{port}"

    path = re.sub(r"/{2,}", "/", parts.path or "/")

    if path != "/":
        path = path.rstrip("/")

    filtered_query: list[tuple[str, str]] = []

    for key, value in parse_qsl(
        parts.query,
        keep_blank_values=True,
    ):
        lowered_key = key.lower()

        if lowered_key.startswith("utm_") or lowered_key in TRACKING_QUERY_KEYS:
            continue

        filtered_query.append((key, value))

    query = urlencode(sorted(filtered_query))

    normalized_url: str = urlunsplit(
        (
            scheme,
            netloc,
            path,
            query,
            "",
        )
    )
    return normalized_url


def is_safe_in_scope_url(
    url: str,
    *,
    start_url: str,
    skipped_extensions: Collection[str] = (DEFAULT_SKIPPED_EXTENSIONS),
    skipped_path_parts: Collection[str] = (DEFAULT_SKIPPED_PATH_PARTS),
) -> bool:
    """Return whether a URL is safe and inside the start path tree."""

    try:
        normalized = normalize_url(url)
        normalized_start = normalize_url(start_url)

        parts = urlsplit(normalized)
        start_parts = urlsplit(normalized_start)
    except (TypeError, ValueError):
        return False

    if normalized_http_origin(normalized) != normalized_http_origin(normalized_start):
        return False

    path = parts.path.lower()
    suffix = PurePosixPath(path).suffix.lower()

    normalized_extensions = {value.lower() for value in skipped_extensions}

    if suffix in normalized_extensions:
        return False

    normalized_skipped_parts = {value.lower() for value in skipped_path_parts}

    path_parts = {part for part in path.split("/") if part}

    if path_parts.intersection(normalized_skipped_parts):
        return False

    start_path = start_parts.path or "/"

    if start_path != "/":
        scoped_start = start_path.rstrip("/").lower()

        if path != scoped_start and not path.startswith(f"{scoped_start}/"):
            return False

    return True


# Temporary compatibility aliases for migrated legacy tests.
_validated_http_url = validated_http_url
_normalized_http_origin = normalized_http_origin
_SameOriginRedirectHandler = SameOriginRedirectHandler
_secure_urlopen = secure_urlopen
