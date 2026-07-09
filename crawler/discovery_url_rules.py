"""Pure URL, content-type, and language rules for discovery fetching."""

from __future__ import annotations

from dataclasses import dataclass
import re
from html import escape
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, Tag

ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
BLOCKED_CONTENT_TYPE_MARKERS = (
    "application/pdf",
    "application/zip",
    "application/x-zip-compressed",
    "application/x-rar",
    "application/x-7z-compressed",
    "application/x-tar",
    "application/gzip",
    "application/octet-stream",
    "image/",
    "video/",
    "audio/",
    "font/",
)
BLOCKED_FILE_EXTENSIONS = (
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
    ".xml",
    ".rss",
    ".atom",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
)
MEDIA_SOCIAL_HOSTS = frozenset(
    """
    instagram.com tiktok.com facebook.com twitter.com x.com threads.net youtube.com
    youtu.be vimeo.com dailymotion.com twitch.tv snapchat.com pinterest.com reddit.com
    linkedin.com linktr.ee beacons.ai bio.site campsite.bio about.me
    """.split()
)
SOCIAL_PROFILE_PATH_MARKERS = (
    "/@",
    "/user/",
    "/users/",
    "/profile/",
    "/profiles/",
    "/account/",
    "/accounts/",
    "/channel/",
    "/channels/",
    "/c/",
    "/u/",
    "/watch",
    "/shorts/",
    "/reel/",
    "/reels/",
    "/video/",
    "/videos/",
    "/pin/",
    "/pins/",
    "/board/",
    "/boards/",
    "/status/",
    "/posts/",
    "/post/",
    "/photos/",
    "/photo/",
    "/stories/",
    "/story/",
)
JS_REQUIRED_PATTERNS = (
    "enable javascript",
    "javascript is required",
    "please enable js",
    "requires javascript",
    "you need to enable javascript",
    "this app works best with javascript",
)
LANGUAGE_QUERY_KEYS = frozenset({"hl", "lang", "language", "locale"})
ENGLISH_LANGUAGE_VALUES = frozenset(
    """
    en en-us en-gb en-au en-ca en-ie en-in en-my en-nz en-ph en-sg en-uk en-za
    en_us en_gb en_au en_ca en_ie en_in en_my en_nz en_ph en_sg en_uk en_za english
    """.split()
)
ISO_3166_REGION_CODES = frozenset(
    """
    ad ae af ag ai al am ao aq ar as at au aw ax az ba bb bd be bf bg bh bi bj bl
    bm bn bo bq br bs bt bv bw by bz ca cc cd cf cg ch ci ck cl cm cn co cr cu cv
    cw cx cy cz de dj dk dm do dz ec ee eg eh er es et fi fj fk fm fo fr ga gb gd
    ge gf gg gh gi gl gm gn gp gq gr gs gt gu gw gy hk hm hn hr ht hu id ie il im
    in io iq ir is it je jm jo jp ke kg kh ki km kn kp kr kw ky kz la lb lc li lk
    lr ls lt lu lv ly ma mc md me mf mg mh mk ml mm mn mo mp mq mr ms mt mu mv mw
    mx my mz na nc ne nf ng ni nl no np nr nu nz om pa pe pf pg ph pk pl pm pn pr
    ps pt pw py qa re ro rs ru rw sa sb sc sd se sg sh si sj sk sl sm sn so sr ss
    st sv sx sy sz tc td tf tg th tj tk tl tm tn to tr tt tv tw tz ua ug um us uy
    uz va vc ve vg vi vn vu wf ws ye yt za zm zw
    """.split()
)
EXTRA_REGION_ALIASES = frozenset(
    {"uk", "usa", "u-s", "u-s-a", "america", "united-states", "united-kingdom"}
)
REGION_GATEKEEPER_SAFE_HOST_PREFIXES = frozenset(
    {
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
)
ENGLISH_STOPWORDS = frozenset(
    """
    the and you your for with from this that are can how what when where learn create
    account help support settings manage use using page content policy privacy terms search
    make get set new more about not all or if to in on of is it as be by a an at we
    our they their will may should before after overview guide documentation reference
    example examples install configure build run delete edit update
    """.split()
)
NON_ENGLISH_STOPWORDS = frozenset(
    """
    ve veya bir bu şu için ile nasıl nedir olan olarak daha değil giriş hesap ayarlar
    kullan kullanım hakkında yardım destek und oder der die das ein eine für mit nicht ist
    sind wie was konto einstellungen hilfe unterstützung et ou le la les des un une pour
    avec pas est sont comment quoi compte paramètres aide assistance y o el los las una
    para con no es son cómo qué cuenta configuración ayuda soporte não como que conta
    configurações ajuda suporte het een voor met niet zijn hoe wat instellingen hulp ondersteuning
    """.split()
)
NON_ENGLISH_CHARACTER_MARKERS = frozenset(
    {"ç", "ğ", "ı", "İ", "ö", "ş", "ü", "ß", "ñ", "¿", "¡", "ã", "õ"}
)

PREFLIGHT_SAMPLE_BYTES = 98_304
PREFLIGHT_MIN_WORDS = 20
PREFLIGHT_MIN_ENGLISH_RATIO = 0.035
PREFLIGHT_MAX_NON_ENGLISH_RATIO = 0.035
PREFLIGHT_MAX_NON_ENGLISH_MARKER_RATIO = 0.025


def is_html(content_type: str) -> bool:
    """Return True when a response content type can be converted to markdown."""

    normalized = content_type.lower().strip()
    return not normalized or any(
        marker in normalized for marker in ALLOWED_CONTENT_TYPES
    )


def is_blocked_content_type(content_type: str) -> bool:
    """Return True when a response content type is binary/media/archive."""

    normalized = content_type.lower().strip()
    return any(marker in normalized for marker in BLOCKED_CONTENT_TYPE_MARKERS)


def is_english(value: str) -> bool:
    """Return True for English language tags."""

    normalized = value.strip().lower().replace("_", "-")
    allowed = {item.replace("_", "-") for item in ENGLISH_LANGUAGE_VALUES}
    return normalized in allowed or normalized.startswith("en-")


def segment_declares_region(value: str) -> bool:
    """Return True when a segment is an ISO region or configured alias."""

    normalized = value.strip().lower().replace("_", "-")
    if not normalized:
        return False

    parts = [part for part in normalized.split("-") if part]
    direct_match = (
        normalized in EXTRA_REGION_ALIASES or normalized in ISO_3166_REGION_CODES
    )
    prefix_match = bool(parts) and parts[0] in EXTRA_REGION_ALIASES.union(
        ISO_3166_REGION_CODES
    )
    suffix_match = 2 <= len(parts) and parts[-1] in ISO_3166_REGION_CODES
    return direct_match or prefix_match or suffix_match


def host_declares_non_english_region(host: str) -> bool:
    """Return True when first host label is a regional language marker."""

    labels = [label for label in host.split(".") if label]
    if not labels:
        return False

    first_label = labels[0].lower().replace("_", "-")
    safe_prefix = first_label in REGION_GATEKEEPER_SAFE_HOST_PREFIXES
    return (
        not safe_prefix
        and not is_english(first_label)
        and segment_declares_region(first_label)
    )


def first_region_or_language_path_segment(path: str) -> str | None:
    """Return first path segment that looks like a language or region marker."""

    for part in path.strip("/").split("/"):
        normalized = part.strip().lower().replace("_", "-")
        if not normalized:
            continue

        if is_english(normalized) or segment_declares_region(normalized):
            return normalized

        if re.fullmatch(r"[a-z]{2}(?:-[a-z]{2})?", normalized):
            return normalized

    return None


def query_declares_non_english_region(query_string: str) -> bool:
    """Return True when language query params explicitly request non-English."""

    query = parse_qs(query_string)
    language_values = [
        value
        for key, values in query.items()
        if key.lower().strip() in LANGUAGE_QUERY_KEYS
        for value in values
        if value.strip()
    ]
    return any(not is_english(value) for value in language_values)


def url_has_definite_non_english_region(url: str) -> bool:
    """Return True when URL host/path/query explicitly points to a non-English region."""

    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.lower()
    normalized_path = f"/{path.strip('/')}/"

    if host_declares_non_english_region(host):
        return True

    region_segment = first_region_or_language_path_segment(path)
    if region_segment and not is_english(region_segment):
        return True

    intl_match = re.search(r"/intl/([^/]+)/", normalized_path)
    if intl_match is not None:
        return not is_english(intl_match.group(1))

    return query_declares_non_english_region(parsed.query)


def is_blocked_url_before_network(url: str, *, require_english: bool) -> bool:
    """Return True when URL can be rejected before any network request."""

    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    path_lower = parsed.path.lower()

    blocked_host = any(
        host == item or host.endswith(f".{item}") for item in MEDIA_SOCIAL_HOSTS
    )
    blocked_social_path = any(
        marker in path_lower for marker in SOCIAL_PROFILE_PATH_MARKERS
    )
    blocked_region = require_english and url_has_definite_non_english_region(url)
    blocked_extension = path_lower.endswith(BLOCKED_FILE_EXTENSIONS)

    return blocked_host or blocked_social_path or blocked_region or blocked_extension


def should_download(
    *,
    url: str,
    content_type: str = "",
    require_english: bool = True,
) -> tuple[bool, str | None]:
    """Return a cheap URL/content-type download decision."""

    if is_blocked_url_before_network(url, require_english=require_english):
        return False, "blocked_url"

    if is_blocked_content_type(content_type):
        return False, "blocked_content_type"

    if content_type and not is_html(content_type):
        return False, "non_html_content_type"

    return True, None


def html_language_decision(soup: BeautifulSoup) -> bool | None:
    """Return HTML language decision from lang/locale metadata."""

    html_tag = soup.find("html")
    if isinstance(html_tag, Tag):
        lang = str(html_tag.get("lang", "")).strip().lower().replace("_", "-")
        if lang:
            return is_english(lang)

    selectors = (
        'meta[property="og:locale"]',
        'meta[name="locale"]',
        'meta[http-equiv="content-language"]',
        'meta[name="language"]',
    )
    for selector in selectors:
        tag = soup.select_one(selector)
        if tag is None:
            continue

        content = str(tag.get("content", "")).strip().lower().replace("_", "-")
        if content:
            return is_english(content)

    return None


def sample_declares_non_english(
    html_or_text: str, *, url: str, content_type: str
) -> bool:
    """Return True when metadata or sampled words confidently identify non-English."""

    if url_has_definite_non_english_region(url):
        return True

    if "text/plain" in content_type:
        return text_sample_is_confidently_non_english(html_or_text)

    soup = BeautifulSoup(html_or_text, "html.parser")
    decision = html_language_decision(soup)
    if decision is not None:
        return not decision

    text = " ".join(soup.get_text(" ", strip=True).split())
    return bool(text) and text_sample_is_confidently_non_english(text)


def text_sample_is_confidently_non_english(text: str) -> bool:
    """Return True only for confident non-English text samples."""

    clean_text = " ".join(text.split())
    if not clean_text:
        return False

    words = re.findall(r"[a-zA-ZÀ-ÿ]{2,}", clean_text.lower())
    if len(words) < PREFLIGHT_MIN_WORDS:
        return False

    english_hits = sum(1 for word in words if word in ENGLISH_STOPWORDS)
    non_english_hits = sum(1 for word in words if word in NON_ENGLISH_STOPWORDS)
    if english_hits == 0 and non_english_hits >= 3:
        return True

    english_ratio = english_hits / len(words)
    non_english_ratio = non_english_hits / len(words)
    marker_ratio = non_english_marker_ratio(clean_text)
    marker_blocked = marker_ratio > PREFLIGHT_MAX_NON_ENGLISH_MARKER_RATIO
    stopword_blocked = non_english_ratio > PREFLIGHT_MAX_NON_ENGLISH_RATIO

    if english_ratio >= PREFLIGHT_MIN_ENGLISH_RATIO:
        return False

    return (marker_blocked or stopword_blocked) and non_english_hits >= english_hits


def non_english_marker_ratio(text: str) -> float:
    """Return ratio of region-specific letters in alphabetic text."""

    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0.0

    marker_count = sum(1 for char in letters if char in NON_ENGLISH_CHARACTER_MARKERS)
    return marker_count / len(letters)


def plain_text_to_html(text: str, url: str) -> str:
    """Wrap allowed plain text in minimal English HTML."""

    return (
        "<!doctype html>"
        '<html lang="en">'
        "<head>"
        f"<title>{escape(url)}</title>"
        "</head>"
        "<body>"
        f"<main><pre>{escape(text)}</pre></main>"
        "</body>"
        "</html>"
    )


def html_needs_playwright(html: str) -> bool:
    """Return True when static HTML looks like a JavaScript shell."""

    lowered = html.lower()
    if any(pattern in lowered for pattern in JS_REQUIRED_PATTERNS):
        return True

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    script_count = len(soup.find_all("script"))
    link_count = len(soup.find_all("a"))

    return len(text) < 160 and script_count >= 3 and not link_count > 3


HIGH_VALUE_PATH_HINTS = (
    "docs",
    "doc",
    "documentation",
    "developers",
    "developer",
    "api",
    "reference",
    "guide",
    "guides",
    "learn",
    "help",
    "support",
)


def path_parts(url: str) -> list[str]:
    """Return normalized non-empty URL path parts."""

    return [part for part in urlparse(url).path.lower().strip("/").split("/") if part]


def root_domain(host: str) -> str:
    """Return a simple registrable-domain approximation."""

    labels = [label for label in host.lower().strip(".").split(".") if label]
    if len(labels) <= 2:
        return ".".join(labels)

    return ".".join(labels[-2:])


def looks_like_official_host(host: str, expected_root_domain: str) -> bool:
    """Return True when host belongs to the expected root domain."""

    normalized_host = host.lower().removeprefix("www.")
    normalized_root = expected_root_domain.lower().removeprefix("www.")

    return normalized_host == normalized_root or normalized_host.endswith(
        f".{normalized_root}",
    )


def same_scope(candidate_url: str, start_url: str) -> bool:
    """Return True when candidate URL stays inside the start URL root domain."""

    candidate = urlparse(candidate_url)
    start = urlparse(start_url)

    return looks_like_official_host(candidate.netloc, root_domain(start.netloc))


def normalize_candidate_url(url: str) -> str:
    """Normalize candidate URL for discovery ranking and deduplication."""

    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"

    normalized = parsed._replace(
        scheme=scheme,
        netloc=netloc,
        path=path,
        fragment="",
    )
    return normalized.geturl().rstrip("/")


def is_non_english_query(query: str) -> bool:
    """Return True when query explicitly asks for a non-English locale."""

    return query_declares_non_english_region(query)


def is_blocked_machine_file(url: str) -> bool:
    """Return True for machine/media/archive URLs that should not be crawled."""

    parsed = urlparse(url)
    path_lower = parsed.path.lower()

    return path_lower.endswith(BLOCKED_FILE_EXTENSIONS)


def is_bad_url(url: str, *, require_english: bool = True) -> bool:
    """Return True when a candidate URL should be rejected before scoring."""

    return is_blocked_url_before_network(url, require_english=require_english)


def official_host_confidence(url: str, expected_root_domain: str) -> int:
    """Return a small confidence score for official host matching."""

    host = urlparse(url).netloc.lower().removeprefix("www.")
    expected = expected_root_domain.lower().removeprefix("www.")

    if host == expected:
        return 3

    if host.endswith(f".{expected}"):
        return 2

    if root_domain(host) == root_domain(expected):
        return 1

    return 0


@dataclass(frozen=True, slots=True)
class ScoredUrl:
    """Legacy discovery URL score result."""

    url: str
    score: int
    reason: str


def _score_single_url(url: str, *, start_url: str = "", seed: str = "") -> ScoredUrl:
    """Return deterministic discovery priority score for one URL."""

    score = 0
    reasons: list[str] = []
    parts = path_parts(url)
    scope_seed = start_url or seed

    if any(part in HIGH_VALUE_PATH_HINTS for part in parts):
        score += 20
        reasons.append("high_value_path")

    if scope_seed and same_scope(url, scope_seed):
        score += 10
        reasons.append("same_scope")

    if not is_bad_url(url):
        score += 5
        reasons.append("not_blocked")

    depth_penalty = min(len(parts), 10)
    if depth_penalty:
        score -= depth_penalty
        reasons.append("path_depth_penalty")

    reason = ",".join(reasons) if reasons else "neutral"
    return ScoredUrl(url=url, score=score, reason=reason)


def score_url(
    urls: str | list[str] | tuple[str, ...] | set[str],
    *,
    start_url: str = "",
    seed: str = "",
) -> list[ScoredUrl]:
    """Return legacy discovery score results for one or more URLs."""

    candidates = [urls] if isinstance(urls, str) else list(urls)

    return sorted(
        (
            _score_single_url(
                url,
                start_url=start_url,
                seed=seed,
            )
            for url in candidates
        ),
        key=lambda item: (-item.score, item.url),
    )
