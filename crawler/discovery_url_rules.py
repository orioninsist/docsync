"""Pure URL, content-type, and language rules for discovery fetching."""

from __future__ import annotations

from html import escape
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from crawler.policy_engine import SmartScopePolicy
from crawler.shared.url_normalizer import normalize_url as shared_normalize_url
from crawler.shared.url_policy import (
    MEDIA_SOCIAL_HOSTS as MEDIA_SOCIAL_HOSTS,
    is_allowed_text_content_type,
    is_blocked_content_type as shared_is_blocked_content_type,
    path_has_blocked_extension,
)

DISCOVERY_EXTRA_MEDIA_SOCIAL_HOSTS = frozenset(
    {
        "about.me",
        "beacons.ai",
        "bio.site",
        "campsite.bio",
        "linkedin.com",
        "linktr.ee",
    }
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

    return not normalized or is_allowed_text_content_type(normalized)


def is_blocked_content_type(content_type: str) -> bool:
    """Return True when a response content type is binary, media, or archive data."""

    return shared_is_blocked_content_type(content_type)


def is_english(value: str) -> bool:
    """Return True for explicit English language tags."""

    normalized = value.strip().lower().replace("_", "-")
    allowed = {item.replace("_", "-") for item in ENGLISH_LANGUAGE_VALUES}

    return normalized in allowed or normalized.startswith("en-")


def segment_declares_region(value: str) -> bool:
    """Retain the legacy public API without using regions as crawl barriers."""

    del value

    return False


def host_declares_non_english_region(host: str) -> bool:
    """Never infer content language from a hostname."""

    del host

    return False


def first_region_or_language_path_segment(path: str) -> str | None:
    """Never infer content language from URL path segments."""

    del path

    return None


def query_declares_non_english_region(query_string: str) -> bool:
    """Never reject a page solely because of URL query parameters."""

    del query_string

    return False


def url_has_definite_non_english_region(url: str) -> bool:
    """Never infer page language from its URL."""

    del url

    return False


def is_blocked_url_before_network(url: str, *, require_english: bool) -> bool:
    """Reject only URLs that cannot represent convertible document content."""

    del require_english

    path_lower = urlparse(url).path.lower()

    return path_has_blocked_extension(path_lower)


def should_download(
    *,
    url: str,
    content_type: str = "",
    require_english: bool = True,
) -> tuple[bool, str | None]:
    """Return a cheap URL and content-type download decision."""

    if is_blocked_url_before_network(url, require_english=require_english):
        return False, "blocked_machine_file"

    if is_blocked_content_type(content_type):
        return False, "blocked_content_type"

    if content_type and not is_html(content_type):
        return False, "non_html_content_type"

    return True, None


def html_language_decision(soup: BeautifulSoup) -> bool | None:
    """Return a language decision from explicit HTML metadata."""

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
    html_or_text: str,
    *,
    url: str,
    content_type: str,
) -> bool:
    """Return True only when downloaded content confidently appears non-English."""

    del url

    if "text/plain" in content_type.lower():
        return text_sample_is_confidently_non_english(html_or_text)

    soup = BeautifulSoup(html_or_text, "html.parser")
    metadata_decision = html_language_decision(soup)

    if metadata_decision is not None:
        return not metadata_decision

    text = " ".join(soup.get_text(" ", strip=True).split())

    return bool(text) and text_sample_is_confidently_non_english(text)


def text_sample_is_confidently_non_english(text: str) -> bool:
    """Return True only for strongly supported non-English text samples."""

    clean_text = " ".join(text.split())

    if not clean_text:
        return False

    words: list[str] = re.findall(r"[a-zA-ZÀ-ÿ]{2,}", clean_text.lower())

    if len(words) < PREFLIGHT_MIN_WORDS:
        return False

    english_hits = sum(1 for word in words if word in ENGLISH_STOPWORDS)
    non_english_hits = sum(1 for word in words if word in NON_ENGLISH_STOPWORDS)

    if english_hits == 0 and non_english_hits >= 3:
        return True

    english_ratio = english_hits / len(words)
    non_english_ratio = non_english_hits / len(words)
    marker_ratio = non_english_marker_ratio(clean_text)

    if english_ratio >= PREFLIGHT_MIN_ENGLISH_RATIO:
        return False

    marker_blocked = marker_ratio > PREFLIGHT_MAX_NON_ENGLISH_MARKER_RATIO
    stopword_blocked = non_english_ratio > PREFLIGHT_MAX_NON_ENGLISH_RATIO

    return (marker_blocked or stopword_blocked) and non_english_hits >= english_hits


def non_english_marker_ratio(text: str) -> float:
    """Return the ratio of selected non-English letters in alphabetic text."""

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

    return len(text) < 160 and script_count >= 3 and link_count <= 3


def normalize_candidate_url(url: str) -> str:
    """Normalize a discovery URL through the shared canonical URL layer."""

    normalized = shared_normalize_url(url)

    if normalized is not None:
        return normalized

    return url.strip()


def path_parts(url: str) -> set[str]:
    """Return canonical normalized URL path tokens."""

    return SmartScopePolicy.path_parts(url)


def is_non_english_query(query: str) -> bool:
    """Retain the legacy public API without URL-language filtering."""

    del query

    return False


def is_blocked_machine_file(url: str) -> bool:
    """Retain the legacy machine-file predicate through the canonical gate."""

    return is_blocked_url_before_network(url, require_english=True)


def is_bad_url(url: str, *, require_english: bool = True) -> bool:
    """Return True only for non-convertible machine-file URLs."""

    return is_blocked_url_before_network(url, require_english=require_english)
