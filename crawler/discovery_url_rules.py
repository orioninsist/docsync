"""URL normalization, filtering, and scoring rules for discovery crawling."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from crawler.discovery_result import DiscoveryResult


TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
    "spm",
    "igshid",
    "yclid",
    "msclkid",
    "utm_id",
    "utm_term",
    "utm_campaign",
    "utm_medium",
    "utm_content",
    "utm_source",
}

IMPORTANT_QUERY_KEYS = {"topic", "category", "section", "segment"}

ENGLISH_QUERY_KEYS = {"hl", "lang", "locale", "language"}
ENGLISH_QUERY_VALUES = {
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
    "english",
}

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
    "gt",
    "gu",
    "gw",
    "gy",
    "hk",
    "hn",
    "hr",
    "ht",
    "hu",
    "id",
    "ie",
    "il",
    "in",
    "is",
    "it",
    "jm",
    "jo",
    "jp",
    "ke",
    "kh",
    "kr",
    "kw",
    "kz",
    "la",
    "lb",
    "li",
    "lk",
    "lt",
    "lu",
    "lv",
    "ma",
    "md",
    "me",
    "mk",
    "mx",
    "my",
    "ng",
    "nl",
    "no",
    "nz",
    "pa",
    "pe",
    "ph",
    "pk",
    "pl",
    "pt",
    "qa",
    "ro",
    "rs",
    "ru",
    "sa",
    "se",
    "sg",
    "si",
    "sk",
    "th",
    "tr",
    "tw",
    "ua",
    "uk",
    "us",
    "uy",
    "vn",
    "za",
}

EXTRA_REGION_ALIASES = {
    "usa",
    "u-s",
    "u-s-a",
    "america",
    "united-states",
    "united-kingdom",
}

SAFE_REGION_HOST_PREFIXES = {
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
}

HIGH_VALUE_PATH_HINTS = {
    "docs",
    "documentation",
    "doc",
    "developer",
    "developers",
    "api",
    "reference",
    "guide",
    "guides",
    "manual",
    "help",
    "support",
    "learn",
    "academy",
    "tutorial",
    "tutorials",
    "blog",
    "news",
    "resources",
    "resource",
    "products",
    "product",
    "platform",
    "business",
    "creator",
    "creators",
    "policy",
    "policies",
    "rules",
    "requirements",
    "eligibility",
    "guidelines",
    "standards",
    "solutions",
    "solution",
    "overview",
    "getting-started",
    "start",
    "cloud",
    "ai",
    "models",
    "search-console",
    "analytics",
    "ads",
    "advertising",
    "workspace",
    "maps",
    "android",
    "chrome",
    "enterprise",
    "firebase",
    "flutter",
    "tensorflow",
    "web",
}

ROOT_SEED_HINTS = HIGH_VALUE_PATH_HINTS | {
    "about",
    "company",
    "customers",
    "pricing",
}

LOW_VALUE_HOST_HINTS = {
    "accounts.google.com",
    "admin.google.com",
    "calendar.google.com",
    "console.cloud.google.com",
    "drive.google.com",
    "forms.google.com",
    "keep.google.com",
    "payments.google.com",
    "photos.google.com",
    "play.google.com",
    "shopping.google.com",
    "sites.google.com",
    "goo.gle",
    "g.co",
    "docs.google.com",
}

LOW_VALUE_PATH_HINTS = {
    "login",
    "signin",
    "sign-in",
    "logout",
    "auth",
    "oauth",
    "account",
    "accounts",
    "profile",
    "profiles",
    "user",
    "users",
    "community",
    "forum",
    "forums",
    "thread",
    "threads",
    "discussion",
    "discussions",
    "question",
    "questions",
    "answer",
    "answers",
    "qna",
    "qa",
    "comments",
    "comment",
    "careers",
    "jobs",
    "cart",
    "checkout",
    "billing",
    "pricing",
    "plans",
    "contact",
    "sales",
    "demo",
    "search",
    "tag",
    "tags",
    "author",
    "category",
    "categories",
    "request",
    "requests",
    "signup",
    "subscribe",
    "subscription",
    "partner",
    "partners",
    "admin",
    "calendar",
    "drive",
    "forms",
    "photos",
    "shopping",
    "payments",
    "settings",
    "store",
    "console",
    "video",
    "videos",
    "reel",
    "reels",
    "shorts",
}

BAD_PATH_PREFIXES = (
    "/finance/quote/",
    "/quote/",
    "/search/",
    "/search",
    "/advanced_search",
    "/sorry/",
    "/preferences",
    "/setprefs",
    "/travel/flights/",
)

BAD_PATH_CONTAINS = (
    "/servicelogin",
    "/accounts/",
    "/login/",
    "/signin/",
    "/sign-in/",
    "/oauth/",
    "/auth/",
    "/community/",
    "/forum/",
    "/forums/",
    "/questions/",
    "/answers/",
    "/search/",
    "/calendar/",
    "/drive/",
    "/forms/",
    "/photos/",
    "/shopping/",
    "/payments/",
    "/account/",
    "/reel/",
    "/reels/",
    "/video/",
    "/videos/",
    "/shorts/",
)

OFFICIAL_HOST_PREFIXES = {
    "about",
    "docs",
    "doc",
    "developers",
    "developer",
    "help",
    "support",
    "learn",
    "business",
    "creators",
    "creator",
    "blog",
    "news",
    "resources",
    "api",
    "cloud",
    "ai",
    "research",
    "labs",
    "firebase",
    "workspace",
    "marketingplatform",
    "ads",
    "admob",
    "analytics",
    "mapsplatform",
    "chrome",
    "android",
}

DISCOVERY_BLOCKED_SCHEMES = (
    "mailto:",
    "tel:",
    "javascript:",
    "data:",
    "blob:",
    "file:",
    "ftp:",
)

DISCOVERY_BLOCKED_FILE_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".gz",
    ".mp4",
    ".webm",
    ".mov",
    ".avi",
    ".mp3",
    ".wav",
    ".css",
    ".js",
    ".mjs",
    ".json",
    ".rss",
    ".atom",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
)

DISCOVERY_UTILITY_PATH_PARTS = {
    "_",
    "url",
    "setprefdomain",
    "preferences",
    "setprefs",
    "sorry",
    "search",
    "advanced_search",
    "imghp",
    "maps",
    "mail",
    "calendar",
    "drive",
    "forms",
    "photos",
    "shopping",
    "finance",
    "travel",
    "flights",
    "accounts",
    "signin",
    "login",
    "servicelogin",
    "oauth",
    "auth",
}

DISCOVERY_UTILITY_HOSTS = {
    "mail.google.com",
    "accounts.google.com",
    "calendar.google.com",
    "drive.google.com",
    "forms.google.com",
    "photos.google.com",
    "shopping.google.com",
    "payments.google.com",
    "myaccount.google.com",
    "myactivity.google.com",
}

DISCOVERY_MAX_DEFAULT_PAGES = 900
DISCOVERY_MAX_DEFAULT_DEPTH = 5
DISCOVERY_MAX_LINKS_PER_PAGE = 2500
DISCOVERY_MAX_ACCEPTED_MULTIPLIER = 30

BAD_QUERY_KEYS = {
    "q",
    "query",
    "search",
    "search_id",
    "results_count",
    "rank",
    "return_to",
    "redirect",
    "redirect_to",
    "callback",
    "data",
    "url",
    "continue",
    "next",
}

SUPPRESSED_REVIEW_MARKERS = (
    "machine_file",
    "non_english",
    "iso_block",
    "search",
    "login",
    "auth",
    "forum",
    "community",
    "account",
)


def log(message: str) -> None:
    """Print a crawler log message immediately."""
    print(message, flush=True)


def canonical_input(value: str) -> str:
    """Return a URL-like input with a scheme and default .com host suffix."""
    value = value.strip()
    if not value:
        raise ValueError("URL value must not be empty.")
    if not value.startswith(("http://", "https://")):
        if "." not in value:
            value = f"{value}.com"
        value = "https://" + value
    return value


def normalize_site(value: str) -> str:
    """Normalize a site seed while preserving the seed path."""
    parsed = urlparse(canonical_input(value))
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower().removeprefix("www.")
    return urlunparse((scheme, netloc, parsed.path or "/", "", "", ""))


def normalize_candidate_url(url: str) -> str:
    """Normalize a candidate URL for stable deduplication and scoring."""
    parsed = urlparse(canonical_input(url))
    scheme = "https"
    netloc = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path or "/"
    english_intl_pattern = r"^/intl/en(?:[-_][a-z]{2})?/"

    path = re.sub(
        english_intl_pattern,
        "/intl/en/",
        path,
        flags=re.IGNORECASE,
    )

    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    query_items: list[tuple[str, str]] = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        key_lower = key.lower().strip()
        value_clean = value.strip()
        if key_lower.startswith("utm_") or key_lower in TRACKING_QUERY_KEYS:
            continue
        if key_lower in ENGLISH_QUERY_KEYS:
            continue
        if key_lower not in IMPORTANT_QUERY_KEYS:
            continue
        query_items.append((key_lower, value_clean))

    query = urlencode(sorted(query_items))
    return urlunparse((scheme, netloc, path, "", query, ""))


def host_of(url: str) -> str:
    """Return the normalized host for a URL or host-like value."""
    return urlparse(normalize_site(url)).netloc.lower().removeprefix("www.")


def root_domain(url: str) -> str:
    """Return the root domain while preserving common second-level TLDs."""
    host = host_of(url)
    parts = host.split(".")
    second_level_tlds = {"co", "com", "org", "net", "ac", "gov"}
    if len(parts) >= 3 and parts[-2] in second_level_tlds:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def path_parts(url: str) -> list[str]:
    """Return normalized path segments for a candidate URL."""
    parsed = urlparse(normalize_candidate_url(url))
    raw_parts = parsed.path.strip("/").split("/")
    return [
        part.strip().lower().replace("_", "-") for part in raw_parts if part.strip()
    ]


def path_part_set(url: str) -> set[str]:
    """Return normalized path segments as a set."""
    return set(path_parts(url))


def path_depth(url: str) -> int:
    """Return the number of normalized path segments."""
    return len(path_parts(url))


def _is_allowed_english_segment(value: str) -> bool:
    """Return True when a locale segment is explicitly English."""
    return value == "en" or value.startswith("en-")


def _is_blocked_region_segment(value: str) -> bool:
    """Return True when a segment is a regional or non-English marker."""
    normalized = value.strip().lower().replace("_", "-")
    if not normalized or _is_allowed_english_segment(normalized):
        return False

    parts = [part for part in normalized.split("-") if part]
    return (
        normalized in ISO_3166_REGION_CODES
        or normalized in EXTRA_REGION_ALIASES
        or bool(parts and parts[0] in ISO_3166_REGION_CODES)
        or bool(parts and parts[0] in EXTRA_REGION_ALIASES)
        or bool(len(parts) >= 2 and parts[-1] in ISO_3166_REGION_CODES)
    )


def _host_region_block_reason(host: str) -> str | None:
    """Return a region block reason from the first host label."""
    labels = [label for label in host.split(".") if label]
    first_label = labels[0].replace("_", "-") if labels else ""
    is_safe_prefix = first_label in SAFE_REGION_HOST_PREFIXES

    if first_label and not is_safe_prefix and _is_blocked_region_segment(first_label):
        return f"iso_block_host_label:{first_label}"
    return None


def _path_region_block_reason(path: str) -> str | None:
    """Return a region block reason from URL path segments."""
    reason: str | None = None
    for part in path.strip("/").split("/"):
        normalized = part.strip().lower().replace("_", "-")
        if _is_blocked_region_segment(normalized):
            reason = f"iso_block_path_segment:{normalized}"
            break
    return reason


def _query_region_block_reason(query: str) -> str | None:
    """Return a region block reason from language query parameters."""
    reason: str | None = None
    for key, value in parse_qsl(query, keep_blank_values=False):
        key_lower = key.lower().strip()
        normalized = value.strip().lower().replace("_", "-")
        if key_lower not in ENGLISH_QUERY_KEYS:
            continue
        if normalized and not _is_allowed_english_segment(normalized):
            reason = f"iso_block_query_language:{normalized}"
            break
    return reason


def regional_block_reason(url: str) -> str | None:
    """Return the first regional or non-English block reason for a URL."""
    source = url if url.startswith(("http://", "https://")) else canonical_input(url)
    parsed = urlparse(source)
    host = parsed.netloc.lower().removeprefix("www.")

    reason = _host_region_block_reason(host)
    if reason is None:
        reason = _path_region_block_reason(parsed.path)
    if reason is None:
        reason = _query_region_block_reason(parsed.query)
    return reason


def is_non_english_query(url: str) -> bool:
    """Return True when URL query or locale markers are non-English."""
    return regional_block_reason(url) is not None


def is_english_url(url: str) -> bool:
    """Return True when URL has no regional or non-English markers."""
    return regional_block_reason(url) is None


def is_blocked_machine_file(url: str) -> bool:
    """Return True when a URL points to a blocked machine or media file."""
    parsed = urlparse(url)
    return parsed.path.lower().endswith(DISCOVERY_BLOCKED_FILE_EXTENSIONS)


def has_bad_query(url: str) -> bool:
    """Return True when URL query keys indicate search, redirects, or junk."""
    parsed = urlparse(url)
    query_items = parse_qsl(parsed.query, keep_blank_values=False)
    return any(key.lower().strip() in BAD_QUERY_KEYS for key, _ in query_items)


def is_bad_url(url: str) -> str | None:
    """Return a block reason when a candidate URL should be rejected."""
    clean = normalize_candidate_url(url)
    parsed = urlparse(clean)
    host = parsed.netloc.lower().removeprefix("www.")
    path_lower = parsed.path.lower()
    normalized_path = f"/{path_lower.strip('/')}/"
    reason: str | None = None

    if host in LOW_VALUE_HOST_HINTS:
        reason = f"blocked:low_value_host:{host}"
    elif is_blocked_machine_file(clean):
        reason = "blocked:machine_file"
    else:
        reason = regional_block_reason(clean)

    if reason is None and has_bad_query(clean):
        reason = "blocked:bad_query"

    if reason is None:
        for prefix in BAD_PATH_PREFIXES:
            if path_lower.startswith(prefix.lower()):
                reason = f"blocked:path_prefix:{prefix}"
                break

    if reason is None:
        for bad in BAD_PATH_CONTAINS:
            if bad.lower() in normalized_path:
                reason = f"blocked:path_contains:{bad}"
                break

    if reason is None:
        low_value_parts = path_part_set(clean).intersection(LOW_VALUE_PATH_HINTS)
        if low_value_parts:
            reason = "blocked:" + ",".join(sorted(low_value_parts))

    return reason


def same_scope(seed: str, candidate: str) -> bool:
    """Return True when candidate is in the same crawl scope as seed."""
    seed_host = host_of(seed)
    candidate_host = host_of(candidate)
    same_host = candidate_host == seed_host
    subdomain_of_seed = candidate_host.endswith("." + seed_host)
    same_root = root_domain(seed) == root_domain(candidate)
    return same_host or subdomain_of_seed or same_root


def looks_like_official_host(seed: str, candidate: str) -> bool:
    """Return True when candidate host appears official for the seed."""
    clean = normalize_candidate_url(candidate)
    if is_bad_url(clean):
        return False
    if same_scope(seed, clean):
        return True

    seed_root = root_domain(seed).split(".", 1)[0]
    candidate_host = host_of(clean)
    candidate_root = root_domain(clean).split(".", 1)[0]
    host_prefix = candidate_host.split(".", 1)[0]

    if seed_root and seed_root in candidate_host:
        return True
    if candidate_root and candidate_root in host_of(seed):
        return True
    if host_prefix in OFFICIAL_HOST_PREFIXES:
        return bool(seed_root and seed_root in candidate_host)
    return False


def official_host_confidence(seed: str, candidate: str) -> int:
    """Score whether a candidate host and path appear official."""
    clean = normalize_candidate_url(candidate)
    if is_bad_url(clean):
        return 0

    score = 0
    if same_scope(seed, clean):
        score += 60
    if looks_like_official_host(seed, clean):
        score += 35

    host_prefix = host_of(clean).split(".", 1)[0]
    if host_prefix in OFFICIAL_HOST_PREFIXES:
        score += 25

    parts = path_part_set(clean)
    score += min(60, len(parts.intersection(HIGH_VALUE_PATH_HINTS)) * 12)
    score += min(35, len(parts.intersection(ROOT_SEED_HINTS)) * 10)

    if parts.intersection(LOW_VALUE_PATH_HINTS):
        score -= 100

    return max(score, 0)


def _add_depth_score(score: int, reasons: set[str], depth: int) -> int:
    """Apply path-depth score adjustments and reason labels."""
    adjusted_score = score
    if depth == 0:
        adjusted_score += 30
        reasons.add("root_landing")
    elif depth <= 2:
        adjusted_score += 20
        reasons.add("shallow_root")
    elif depth <= 3:
        adjusted_score += 5
        reasons.add("specific_root")
    else:
        adjusted_score -= 80
        reasons.add("deep_page_penalty")
    return adjusted_score


def score_url(url: str, *, seed: str) -> tuple[str, DiscoveryResult]:
    """Classify and score a candidate URL for discovery queue review."""
    clean = normalize_candidate_url(url).rstrip("/") + "/"
    bad = is_bad_url(clean)
    if bad:
        return "blocked", DiscoveryResult(clean, seed, 0, bad)

    score = official_host_confidence(seed, clean)
    reasons: set[str] = set()

    if same_scope(seed, clean):
        reasons.add("same_scope")
    if looks_like_official_host(seed, clean):
        reasons.add("official_like_host")

    high_value_parts = path_part_set(clean).intersection(HIGH_VALUE_PATH_HINTS)
    if high_value_parts:
        score += len(high_value_parts) * 18
        reasons.update(high_value_parts)

    score = _add_depth_score(score, reasons, path_depth(clean))

    if not reasons:
        no_signal = DiscoveryResult(clean, seed, 0, "no_official_knowledge_signal")
        return "blocked", no_signal

    item = DiscoveryResult(clean, seed, score, ",".join(sorted(reasons)))

    if score >= 95:
        return "accepted", item
    if score >= 65:
        return "review", item
    return "blocked", DiscoveryResult(clean, seed, score, "weak_official_signal")


def should_suppress_candidate_from_review(url: str, reason: str = "") -> bool:
    """Return True when a blocked candidate should not be shown for review."""
    clean = normalize_candidate_url(url)
    reason_lower = reason.lower()
    if is_blocked_machine_file(clean):
        return True
    return any(marker in reason_lower for marker in SUPPRESSED_REVIEW_MARKERS)
