"""Discovery URL region and language gate."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlparse

from crawler.shared.iso_language_gate import (
    LANGUAGE_QUERY_KEYS,
    SAFE_HOST_PREFIXES,
    is_english_value,
    normalize_lang_value,
    segment_declares_region,
)

DISCOVERY_SAFE_HOST_PREFIXES = SAFE_HOST_PREFIXES | {
    "research",
    "labs",
}


def discovery_region_block_reason(raw_url: str) -> str | None:
    """Return the reason a URL declares a non-English region or language."""

    parsed = urlparse(raw_url)
    host = parsed.netloc.lower().removeprefix("www.")
    labels = [label for label in host.split(".") if label]

    if labels:
        first_label = normalize_lang_value(labels[0])

        if (
            first_label
            and first_label not in DISCOVERY_SAFE_HOST_PREFIXES
            and segment_declares_region(first_label)
        ):
            return f"iso_block_host_label:{first_label}"

        for label in labels:
            normalized = normalize_lang_value(label)

            if "-" in normalized and segment_declares_region(normalized):
                region = normalized.rsplit("-", 1)[-1]
                return f"iso_block_host_suffix:{region}"

    path_parts = [
        normalize_lang_value(part)
        for part in parsed.path.strip("/").split("/")
        if part.strip()
    ]

    for part in path_parts:
        if is_english_value(part):
            continue

        if segment_declares_region(part):
            return f"iso_block_path_segment:{part}"

    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        normalized_key = key.lower().strip()

        if normalized_key not in LANGUAGE_QUERY_KEYS:
            continue

        if value.strip() and not is_english_value(value):
            normalized_value = normalize_lang_value(value)
            return f"iso_block_query:{normalized_key}={normalized_value}"

    return None
