from __future__ import annotations

from urllib.parse import parse_qsl, urlparse

ISO_3166_ALPHA2 = {
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
    "eh",
    "er",
    "es",
    "et",
    "fi",
    "fj",
    "fk",
    "fm",
    "fo",
    "fr",
    "ga",
    "gb",
    "gd",
    "ge",
    "gf",
    "gg",
    "gh",
    "gi",
    "gl",
    "gm",
    "gn",
    "gp",
    "gq",
    "gr",
    "gs",
    "gt",
    "gu",
    "gw",
    "gy",
    "hk",
    "hm",
    "hn",
    "hr",
    "ht",
    "hu",
    "id",
    "ie",
    "il",
    "im",
    "in",
    "io",
    "iq",
    "ir",
    "is",
    "it",
    "je",
    "jm",
    "jo",
    "jp",
    "ke",
    "kg",
    "kh",
    "ki",
    "km",
    "kn",
    "kp",
    "kr",
    "kw",
    "ky",
    "kz",
    "la",
    "lb",
    "lc",
    "li",
    "lk",
    "lr",
    "ls",
    "lt",
    "lu",
    "lv",
    "ly",
    "ma",
    "mc",
    "md",
    "me",
    "mf",
    "mg",
    "mh",
    "mk",
    "ml",
    "mm",
    "mn",
    "mo",
    "mp",
    "mq",
    "mr",
    "ms",
    "mt",
    "mu",
    "mv",
    "mw",
    "mx",
    "my",
    "mz",
    "na",
    "nc",
    "ne",
    "nf",
    "ng",
    "ni",
    "nl",
    "no",
    "np",
    "nr",
    "nu",
    "nz",
    "om",
    "pa",
    "pe",
    "pf",
    "pg",
    "ph",
    "pk",
    "pl",
    "pm",
    "pn",
    "pr",
    "ps",
    "pt",
    "pw",
    "py",
    "qa",
    "re",
    "ro",
    "rs",
    "ru",
    "rw",
    "sa",
    "sb",
    "sc",
    "sd",
    "se",
    "sg",
    "sh",
    "si",
    "sj",
    "sk",
    "sl",
    "sm",
    "sn",
    "so",
    "sr",
    "ss",
    "st",
    "sv",
    "sx",
    "sy",
    "sz",
    "tc",
    "td",
    "tf",
    "tg",
    "th",
    "tj",
    "tk",
    "tl",
    "tm",
    "tn",
    "to",
    "tr",
    "tt",
    "tv",
    "tw",
    "tz",
    "ua",
    "ug",
    "um",
    "us",
    "uy",
    "uz",
    "va",
    "vc",
    "ve",
    "vg",
    "vi",
    "vn",
    "vu",
    "wf",
    "ws",
    "ye",
    "yt",
    "za",
    "zm",
    "zw",
}

REGION_ALIASES = {
    "uk",
    "usa",
    "u-s",
    "u-s-a",
    "america",
    "united-states",
    "united-kingdom",
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
    "about",
    "news",
}


def normalize_lang_value(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def is_english_value(value: str) -> bool:
    normalized = normalize_lang_value(value)
    return (
        normalized == "en"
        or normalized.startswith("en-")
        or normalized in ENGLISH_VALUES
    )


def segment_declares_region(value: str) -> bool:
    normalized = normalize_lang_value(value)

    if not normalized:
        return False

    if is_english_value(normalized):
        return False

    if normalized in REGION_ALIASES or normalized in ISO_3166_ALPHA2:
        return True

    parts = [part for part in normalized.split("-") if part]

    if not parts:
        return False

    if parts[0] in REGION_ALIASES or parts[0] in ISO_3166_ALPHA2:
        return True

    if parts[-1] in REGION_ALIASES or parts[-1] in ISO_3166_ALPHA2:
        return True

    return False


def url_declares_non_english_or_region(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    labels = [label for label in host.split(".") if label]

    if labels:
        tld = labels[-1]
        if tld in ISO_3166_ALPHA2 and tld not in {"com", "org", "net"}:
            return f"iso_block_host_tld:{tld}"

        first = normalize_lang_value(labels[0])
        if first not in SAFE_HOST_PREFIXES and segment_declares_region(first):
            return f"iso_block_host_label:{first}"

        for label in labels[:-1]:
            normalized = normalize_lang_value(label)
            if normalized in SAFE_HOST_PREFIXES:
                continue
            if segment_declares_region(normalized):
                return f"iso_block_host_suffix:{normalized}"

    for raw_part in parsed.path.strip("/").split("/"):
        part = normalize_lang_value(raw_part)
        if not part:
            continue
        if is_english_value(part):
            continue
        if segment_declares_region(part):
            return f"iso_block_path_segment:{part}"

    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        if key.lower().strip() not in LANGUAGE_QUERY_KEYS:
            continue

        normalized = normalize_lang_value(value)
        if normalized and not is_english_value(normalized):
            return f"iso_block_query_language:{normalized}"

    return None


def url_is_english_or_neutral(url: str) -> bool:
    return url_declares_non_english_or_region(url) is None
