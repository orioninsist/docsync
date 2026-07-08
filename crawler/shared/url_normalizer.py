from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from crawler.shared.constants import TRACKING_QUERY_KEYS, TRACKING_QUERY_PREFIXES

LANGUAGE_QUERY_KEYS = {
    "hl",
    "lang",
    "language",
    "locale",
}

ENGLISH_LANGUAGE_VALUES = {
    "en",
    "en-us",
    "en-gb",
    "en-au",
    "en-ca",
    "en-ie",
    "en-in",
    "en-my",
    "en-nz",
    "en-ph",
    "en-sg",
    "en-uk",
    "en-za",
    "en_us",
    "en_gb",
    "en_au",
    "en_ca",
    "en_ie",
    "en_in",
    "en_my",
    "en_nz",
    "en_ph",
    "en_sg",
    "en_uk",
    "en_za",
    "english",
}

NORMALIZED_ENGLISH_LANGUAGE_VALUES = {
    value.replace("_", "-") for value in ENGLISH_LANGUAGE_VALUES
}

BLOCKED_SCHEMES = {
    "mailto",
    "tel",
    "javascript",
    "data",
    "blob",
    "file",
    "ftp",
}

LANGUAGE_SEGMENT_PATTERN = re.compile(
    r"^[a-z]{2}(?:[-_][a-z]{2})?$",
    re.IGNORECASE,
)

INTL_LANGUAGE_SEGMENT_PATTERN = re.compile(
    r"^/intl/([^/]+)(/|$)",
    re.IGNORECASE,
)

ROOT_LANGUAGE_SEGMENT_PATTERN = re.compile(
    r"^/([a-z]{2}(?:[-_][a-z]{2})?)(/|$)",
    re.IGNORECASE,
)


def _normalize_language_value(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def _is_english_language_value(value: str) -> bool:
    normalized = _normalize_language_value(value)
    return normalized in NORMALIZED_ENGLISH_LANGUAGE_VALUES


def _is_english_language_segment(value: str) -> bool:
    normalized = _normalize_language_value(value)
    return normalized == "en" or normalized.startswith("en-")


def _looks_like_language_segment(value: str) -> bool:
    return bool(LANGUAGE_SEGMENT_PATTERN.fullmatch(value.strip()))


def _path_segments(path: str) -> list[str]:
    return [segment.strip() for segment in (path or "/").split("/") if segment.strip()]


def _path_declares_non_english(path: str) -> bool:
    segments = _path_segments(path)

    for index, segment in enumerate(segments):
        normalized = _normalize_language_value(segment)

        if not _looks_like_language_segment(normalized):
            continue

        if _is_english_language_segment(normalized):
            return False

        if index > 0 and segments[index - 1].lower() == "intl":
            return True

        if "-" in normalized:
            return True

        if index == 0:
            return True

    return False


def _path_declares_english(path: str) -> bool:
    for segment in _path_segments(path):
        normalized = _normalize_language_value(segment)

        if _looks_like_language_segment(normalized) and _is_english_language_segment(
            normalized
        ):
            return True

    return False


def _normalize_path(path: str) -> str:
    clean_path = path or "/"
    clean_path = re.sub(r"/{2,}", "/", clean_path)

    clean_path = re.sub(
        r"^/intl/en(?:[-_][a-z]{2})?(/|$)",
        r"/intl/en\1",
        clean_path,
        flags=re.IGNORECASE,
    )

    clean_path = re.sub(
        r"^/en(?:[-_][a-z]{2})?(/|$)",
        r"/en\1",
        clean_path,
        flags=re.IGNORECASE,
    )

    clean_path = re.sub(
        r"/en(?:[-_][a-z]{2})?(/|$)",
        r"/en\1",
        clean_path,
        flags=re.IGNORECASE,
    )

    if clean_path != "/" and clean_path.endswith("/"):
        clean_path = clean_path.rstrip("/")

    return clean_path


def url_declares_english(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path or "/"

    intl_match = INTL_LANGUAGE_SEGMENT_PATTERN.match(path)
    if intl_match:
        return _is_english_language_segment(intl_match.group(1))

    root_match = ROOT_LANGUAGE_SEGMENT_PATTERN.match(path)
    if root_match:
        return _is_english_language_segment(root_match.group(1))

    if _path_declares_english(path):
        return True

    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        if key.lower().strip() not in LANGUAGE_QUERY_KEYS:
            continue

        if _is_english_language_value(value):
            return True

    return False


def url_declares_non_english(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path or "/"

    intl_match = INTL_LANGUAGE_SEGMENT_PATTERN.match(path)
    if intl_match:
        return not _is_english_language_segment(intl_match.group(1))

    root_match = ROOT_LANGUAGE_SEGMENT_PATTERN.match(path)
    if root_match:
        segment = root_match.group(1)
        if _is_english_language_segment(segment):
            return False
        if _looks_like_language_segment(segment):
            return True

    if _path_declares_non_english(path):
        return True

    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        if key.lower().strip() not in LANGUAGE_QUERY_KEYS:
            continue

        value_normalized = _normalize_language_value(value)
        if (
            value_normalized
            and value_normalized not in NORMALIZED_ENGLISH_LANGUAGE_VALUES
        ):
            return True

    return False


def url_is_explicitly_english_or_neutral(url: str) -> bool:
    return not url_declares_non_english(url)


def is_supported_web_url(url: str) -> bool:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()

    if scheme and scheme not in {"http", "https"}:
        return False

    if scheme in BLOCKED_SCHEMES:
        return False

    return True


def absolute_url(base_url: str, candidate_url: str) -> str | None:
    candidate_url = candidate_url.strip()

    if not candidate_url:
        return None

    if candidate_url.startswith("#"):
        return None

    if not is_supported_web_url(candidate_url):
        return None

    joined = urljoin(base_url, candidate_url)
    parsed_joined = urlparse(joined)

    if parsed_joined.scheme.lower() not in {"http", "https"}:
        return None

    if not parsed_joined.netloc:
        return None

    return joined


def normalize_url(url: str) -> str:
    raw_url = url.strip()

    if not raw_url:
        raise ValueError("URL must not be empty.")

    parsed = urlparse(raw_url)

    scheme = parsed.scheme.lower()
    if scheme in {"", "http", "https"}:
        scheme = "https"

    netloc = parsed.netloc.lower().removeprefix("www.")
    path = _normalize_path(parsed.path or "/")

    query_items: list[tuple[str, str]] = []

    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        key_lower = key.lower().strip()
        value_clean = value.strip()

        if not key_lower:
            continue

        if key_lower in TRACKING_QUERY_KEYS:
            continue

        if any(key_lower.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue

        if key_lower in LANGUAGE_QUERY_KEYS:
            if _is_english_language_value(value_clean):
                continue

            query_items.append((key_lower, value_clean))
            continue

        query_items.append((key_lower, value_clean))

    query = urlencode(sorted(query_items))

    return urlunparse((scheme, netloc, path, "", query, ""))


def normalize_joined_url(base_url: str, candidate_url: str) -> str | None:
    joined = absolute_url(base_url, candidate_url)

    if joined is None:
        return None

    if url_declares_non_english(joined):
        return None

    normalized = normalize_url(joined)

    if url_declares_non_english(normalized):
        return None

    return normalized


def normalize_optional_url(url: str) -> str | None:
    if not url.strip():
        return None

    if not is_supported_web_url(url):
        return None

    if url_declares_non_english(url):
        return None

    normalized = normalize_url(url)

    if url_declares_non_english(normalized):
        return None

    return normalized


def url_sha256(url: str) -> str:
    normalized = normalize_url(url)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
