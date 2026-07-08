from __future__ import annotations

from urllib.parse import parse_qsl, urlparse

ISO_3166_REGION_CODES = {
    "ad",
    "ae",
    "af",
    "ag",
    "ai",
    "al",
    "am",
    "ao",
    "aq",
    "ar",
    "as",
    "at",
    "au",
    "aw",
    "ax",
    "az",
    "ba",
    "bb",
    "bd",
    "be",
    "bf",
    "bg",
    "bh",
    "bi",
    "bj",
    "bl",
    "bm",
    "bn",
    "bo",
    "bq",
    "br",
    "bs",
    "bt",
    "bv",
    "bw",
    "by",
    "bz",
    "ca",
    "cc",
    "cd",
    "cf",
    "cg",
    "ch",
    "ci",
    "ck",
    "cl",
    "cm",
    "cn",
    "co",
    "cr",
    "cu",
    "cv",
    "cw",
    "cx",
    "cy",
    "cz",
    "de",
    "dj",
    "dk",
    "dm",
    "do",
    "dz",
    "ec",
    "ee",
    "eg",
    "es",
    "et",
    "fi",
    "fj",
    "fr",
    "gb",
    "gr",
    "hk",
    "hr",
    "hu",
    "id",
    "ie",
    "il",
    "in",
    "it",
    "jp",
    "kr",
    "mx",
    "my",
    "nl",
    "no",
    "nz",
    "pl",
    "pt",
    "ro",
    "ru",
    "se",
    "sg",
    "tr",
    "tw",
    "ua",
    "uk",
    "us",
    "vn",
    "za",
}

EXTRA_REGION_ALIASES = {
    "uk",
    "usa",
    "u-s",
    "u-s-a",
    "america",
    "united-states",
    "united-kingdom",
}

SAFE_HOST_PREFIXES = {
    "www",
    "docs",
    "doc",
    "developer",
    "developers",
    "help",
    "support",
    "learn",
    "blog",
    "api",
    "cloud",
    "business",
    "research",
    "labs",
}

LANGUAGE_QUERY_KEYS = {"hl", "lang", "language", "locale"}

ENGLISH_VALUES = {
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
    "english",
}


def _normalize(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def _is_english(value: str) -> bool:
    normalized = _normalize(value)
    return (
        normalized == "en"
        or normalized.startswith("en-")
        or normalized in ENGLISH_VALUES
    )


def _segment_declares_region(value: str) -> bool:
    normalized = _normalize(value)

    if not normalized:
        return False

    if normalized in EXTRA_REGION_ALIASES:
        return True

    if normalized in ISO_3166_REGION_CODES:
        return True

    parts = [part for part in normalized.split("-") if part]

    if not parts:
        return False

    if parts[0] in EXTRA_REGION_ALIASES:
        return True

    if parts[0] in ISO_3166_REGION_CODES:
        return True

    if len(parts) >= 2 and parts[-1] in ISO_3166_REGION_CODES:
        return True

    return False


def discovery_region_block_reason(raw_url: str) -> str | None:
    parsed = urlparse(raw_url)
    host = parsed.netloc.lower().removeprefix("www.")
    labels = [label for label in host.split(".") if label]

    if labels:
        first_label = _normalize(labels[0])

        if (
            first_label
            and first_label not in SAFE_HOST_PREFIXES
            and _segment_declares_region(first_label)
        ):
            return f"iso_block_host_label:{first_label}"

        for label in labels:
            normalized = _normalize(label)
            if "-" in normalized and _segment_declares_region(normalized):
                return f"iso_block_host_suffix:{normalized.rsplit('-', 1)[-1]}"

    path_parts = [
        _normalize(part) for part in parsed.path.strip("/").split("/") if part.strip()
    ]

    for part in path_parts:
        if _is_english(part):
            continue

        if _segment_declares_region(part):
            return f"iso_block_path_segment:{part}"

    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        if key.lower().strip() not in LANGUAGE_QUERY_KEYS:
            continue

        if value.strip() and not _is_english(value):
            return f"iso_block_query:{key.lower().strip()}={_normalize(value)}"

    return None
