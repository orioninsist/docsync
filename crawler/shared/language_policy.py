"""Shared immutable language-policy constants."""

from __future__ import annotations

ENGLISH_PATH_HINTS: tuple[str, ...] = (
    "/en/",
    "/en-us/",
    "/en-gb/",
    "/english/",
)

NON_ENGLISH_PATH_HINTS: frozenset[str] = frozenset(
    {
        "/tr/",
        "/de/",
        "/fr/",
        "/es/",
        "/it/",
        "/pt/",
        "/pt-br/",
        "/ru/",
        "/ja/",
        "/ko/",
        "/zh/",
        "/zh-cn/",
        "/zh-tw/",
        "/ar/",
        "/hi/",
        "/id/",
        "/nl/",
        "/pl/",
        "/uk/",
        "/vi/",
        "/th/",
        "/cs/",
        "/da/",
        "/el/",
        "/fi/",
        "/he/",
        "/hu/",
        "/ms/",
        "/no/",
        "/ro/",
        "/sk/",
        "/sv/",
        "/bg/",
        "/hr/",
        "/lt/",
        "/lv/",
        "/sl/",
        "/sr/",
    }
)

LANGUAGE_QUERY_KEYS: frozenset[str] = frozenset(
    {
        "hl",
        "lang",
        "language",
        "locale",
    }
)

ENGLISH_QUERY_VALUES: frozenset[str] = frozenset(
    {
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
)

NORMALIZED_ENGLISH_QUERY_VALUES: frozenset[str] = frozenset(
    value.replace("_", "-") for value in ENGLISH_QUERY_VALUES
)


def normalize_language_value(value: str) -> str:
    """Normalize a language identifier for policy comparison."""

    return value.strip().lower().replace("_", "-")


def is_english_language_value(value: str) -> bool:
    """Return whether a language identifier explicitly targets English."""

    normalized = normalize_language_value(value)
    return (
        normalized == "en"
        or normalized.startswith("en-")
        or normalized in NORMALIZED_ENGLISH_QUERY_VALUES
    )
