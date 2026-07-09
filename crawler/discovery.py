"""Discovery compatibility facade and Phase 1 crawler discovery orchestration."""

# pylint: disable=missing-function-docstring,too-many-return-statements,too-many-branches
# pylint: disable=too-many-locals,too-many-arguments

from __future__ import annotations

import gzip
import json
import re
import time
import xml.etree.ElementTree as ET  # nosec B405
from html import unescape
from typing import Any, cast
from urllib.parse import ParseResult, parse_qsl, urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup
from bs4.element import Tag

from crawler.discovery_bfs import run_recursive_bfs_discovery
from crawler.discovery_result import DiscoveryResult
from crawler.discovery_report import write_discovery_coverage_report
from crawler.discovery_state import (
    discovery_db_key,
    discovery_mark_seen,
    discovery_update_seen_status,
    open_discovery_db,
)
from crawler.discovery_url_rules import (
    DISCOVERY_BLOCKED_FILE_EXTENSIONS,
    DISCOVERY_BLOCKED_SCHEMES,
    DISCOVERY_MAX_ACCEPTED_MULTIPLIER,
    DISCOVERY_MAX_DEFAULT_DEPTH,
    DISCOVERY_MAX_DEFAULT_PAGES,
    DISCOVERY_MAX_LINKS_PER_PAGE,
    DISCOVERY_UTILITY_HOSTS,
    DISCOVERY_UTILITY_PATH_PARTS,
    HIGH_VALUE_PATH_HINTS,
    IMPORTANT_QUERY_KEYS,
    LOW_VALUE_PATH_HINTS,
    OFFICIAL_HOST_PREFIXES,
    ROOT_SEED_HINTS,
    canonical_input,
    host_of,
    is_bad_url,
    is_blocked_machine_file,
    log,
    looks_like_official_host,
    normalize_candidate_url,
    normalize_site,
    path_parts,
    regional_block_reason,
    root_domain,
    same_scope,
    score_url,
    should_suppress_candidate_from_review,
)
from crawler.shared.iso_language_gate import (
    url_declares_non_english_or_region as _shared_iso_block_reason,
)
from crawler.shared.iso_language_gate import (
    url_is_english_or_neutral as _shared_iso_url_is_english_or_neutral,
)

_open_discovery_db = open_discovery_db
_mark_seen = discovery_mark_seen
_update_seen = discovery_update_seen_status
_discovery_db_key = discovery_db_key

_REDIRECT_QUERY_KEYS = frozenset(
    {"url", "q", "continue", "target", "dest", "destination"}
)
_TRACKING_QUERY_KEYS = ("continue=", "url=", "q=", "source=", "ved=", "usg=")
_GOOGLE_REDIRECT_PATHS = frozenset({"/url", "/search", "/setprefdomain"})
_TRACKING_REDIRECT_PATHS = frozenset({"/url", "/search", "/setprefdomain", "/sorry"})
_HTML_URL_ATTRS = (
    "data-href",
    "data-url",
    "data-link",
    "data-target",
    "data-navigation-url",
    "data-destination",
)


def _clean_public_host(host: str) -> str:
    return host.lower().strip().strip(".").removeprefix("www.")


def _host_has_invalid_shape(host: str) -> bool:
    return not host or "." not in host or ".." in host or len(host) > 253


def _host_has_reserved_name(host: str) -> bool:
    reserved_suffixes = (
        ".local",
        ".localhost",
        ".internal",
        ".invalid",
        ".test",
        ".example",
    )
    return host in {"g", "localhost"} or host.endswith(reserved_suffixes)


def _host_label_is_valid(label: str) -> bool:
    return bool(
        label
        and len(label) <= 63
        and not label.startswith("-")
        and not label.endswith("-")
        and re.fullmatch(r"[a-z0-9-]+", label)
    )


def _host_is_valid_public_name(host: str) -> bool:
    clean_host = _clean_public_host(host)

    if _host_has_invalid_shape(clean_host) or _host_has_reserved_name(clean_host):
        return False

    return all(_host_label_is_valid(label) for label in clean_host.split("."))


def _raw_discovery_input(value: str, base_url: str | None) -> str | None:
    raw = unescape((value or "").strip())
    raw_lower = raw.lower()

    if (
        not raw
        or raw.startswith("#")
        or raw_lower.startswith(DISCOVERY_BLOCKED_SCHEMES)
    ):
        return None

    if regional_block_reason(raw):
        return None

    if base_url:
        return urljoin(base_url, raw)

    if raw_lower.startswith(("http://", "https://")):
        return raw

    return canonical_input(raw)


def _parsed_http_url(value: str) -> ParseResult | None:
    parsed = urlparse(value)

    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None

    if not _host_is_valid_public_name(parsed.netloc):
        return None

    if parsed.path.lower().endswith(DISCOVERY_BLOCKED_FILE_EXTENSIONS):
        return None

    return parsed


def _safe_normalize_candidate(raw: str) -> str | None:
    try:
        return normalize_candidate_url(raw)
    except ValueError:
        return None


def strict_normalize_discovery_url(
    value: str, *, base_url: str | None = None
) -> str | None:
    raw = _raw_discovery_input(value, base_url)

    if raw is None or _parsed_http_url(raw) is None:
        return None

    clean = _safe_normalize_candidate(raw)

    if clean is None or _parsed_http_url(clean) is None:
        return None

    if regional_block_reason(clean):
        return None

    return clean.rstrip("/") + "/"


def _raw_url_parts(raw_url: str) -> tuple[ParseResult, str, str, list[str]]:
    parsed = urlparse(raw_url)
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.lower()
    parts = [
        part.strip().lower() for part in path.strip("/").split("/") if part.strip()
    ]
    return parsed, host, path, parts


def _utility_block_reason(host: str, path: str, parts: list[str]) -> str | None:
    if host in DISCOVERY_UTILITY_HOSTS:
        return f"utility_app_host:{host}"

    if parts and parts[0] in DISCOVERY_UTILITY_PATH_PARTS:
        return f"utility_path:{parts[0]}"

    if path.startswith("/_/"):
        return "utility_internal_path:_"

    return None


def _query_block_reason(parsed: ParseResult, host: str, path: str) -> str | None:
    if not parsed.query:
        return None

    query_lower = parsed.query.lower()
    normalized_path = path.rstrip("/")

    if host.endswith("google.com") and normalized_path in _GOOGLE_REDIRECT_PATHS:
        return "google_redirect_or_preference_endpoint"

    if normalized_path in _TRACKING_REDIRECT_PATHS and any(
        key in query_lower for key in _TRACKING_QUERY_KEYS
    ):
        return "redirect_tracking_query_endpoint"

    return None


def _raw_discovery_block_reason_base(raw_url: str) -> str | None:
    region_reason = regional_block_reason(raw_url)

    if region_reason:
        return region_reason

    parsed, host, path, parts = _raw_url_parts(raw_url)
    return _utility_block_reason(host, path, parts) or _query_block_reason(
        parsed, host, path
    )


def _raw_discovery_block_reason(raw_url: str) -> str | None:
    iso_reason = _shared_iso_block_reason(raw_url)

    if iso_reason:
        return iso_reason

    return _raw_discovery_block_reason_base(raw_url)


def _promote_discovery_root(seed_url: str, url: str) -> str:
    del seed_url

    clean = strict_normalize_discovery_url(url) or normalize_candidate_url(url)
    parsed = urlparse(clean)
    host = parsed.netloc.lower().removeprefix("www.")
    parts = path_parts(clean)
    host_prefix = host.split(".", 1)[0]

    if host_prefix in OFFICIAL_HOST_PREFIXES:
        return f"https://{host}/"

    if set(parts).intersection(ROOT_SEED_HINTS):
        return f"https://{host}/"

    return clean.rstrip("/") + "/"


def final_txt_candidate(seed_url: str, raw_url: str) -> tuple[str | None, str | None]:
    raw_block = _raw_discovery_block_reason(raw_url)

    if raw_block:
        return None, raw_block

    clean = strict_normalize_discovery_url(raw_url)

    if clean is None:
        return None, "invalid_or_unsafe_url"

    clean_block = _raw_discovery_block_reason(clean)

    if clean_block:
        return None, clean_block

    bad = is_bad_url(clean)

    if bad:
        return None, bad

    if not looks_like_official_host(seed_url, clean):
        return None, "not_internal_or_official_like"

    promoted = _promote_discovery_root(seed_url, clean)
    promoted_block = _raw_discovery_block_reason(promoted)

    if promoted_block:
        return None, promoted_block

    return promoted, None


_final_txt_candidate = final_txt_candidate


def is_non_english_path(url: str) -> bool:
    return _shared_iso_block_reason(url) is not None


def is_non_english_query(url: str) -> bool:
    return _shared_iso_block_reason(url) is not None


def is_english_url(url: str) -> bool:
    return _shared_iso_url_is_english_or_neutral(url)


def _content_type_is_fetchable(content_type: str, final_url: str) -> bool:
    return bool(
        "text/html" in content_type
        or "text/plain" in content_type
        or "xml" in content_type
        or final_url.endswith((".xml", ".xml.gz", ".txt"))
    )


def _decode_response_payload(raw: bytes, content_type: str, final_url: str) -> str:
    is_gzip_payload = raw.startswith(b"\x1f\x8b")
    is_gzip_response = final_url.endswith(".gz") or "gzip" in content_type

    if is_gzip_response or is_gzip_payload:
        raw = gzip.decompress(raw)

    return raw.decode("utf-8", errors="replace")


def _html_lang_is_english_or_neutral(text: str) -> bool:
    soup = BeautifulSoup(text[:120000], "html.parser")
    html_tag = cast(Tag | None, soup.find("html"))

    if html_tag is None:
        return True

    lang = str(html_tag.get("lang", "")).strip().lower().replace("_", "-")
    return not lang or lang == "en" or lang.startswith("en-")


def _response_metadata_is_fetchable(
    response: aiohttp.ClientResponse,
) -> tuple[str, str] | None:
    if response.status >= 400:
        return None

    content_type = response.headers.get("Content-Type", "").lower()
    final_url = str(response.url)

    if is_bad_url(final_url) or not _content_type_is_fetchable(content_type, final_url):
        return None

    return content_type, final_url


async def fetch_text(session: aiohttp.ClientSession, url: str) -> str | None:
    if is_bad_url(url):
        return None

    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=20),
            allow_redirects=True,
        ) as response:
            metadata = _response_metadata_is_fetchable(response)

            if metadata is None:
                return None

            content_type, final_url = metadata
            text = _decode_response_payload(
                await response.read(), content_type, final_url
            )

            if "text/html" in content_type and not _html_lang_is_english_or_neutral(
                text
            ):
                return None

            return text
    except (aiohttp.ClientError, TimeoutError, OSError, gzip.BadGzipFile, UnicodeError):
        return None


def _append_normalized_url(
    *,
    value: str,
    base_url: str,
    urls: list[str],
    seen: set[str],
) -> None:
    clean = strict_normalize_discovery_url(value, base_url=base_url)

    if clean and clean not in seen:
        seen.add(clean)
        urls.append(clean)


def _extract_standard_html_urls(soup: BeautifulSoup, base_url: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    for tag in soup.select(
        "a[href],link[href],area[href],meta[property='og:url'],meta[name='twitter:url']"
    ):
        attr = "content" if tag.name == "meta" else "href"
        _append_normalized_url(
            value=str(tag.get(attr, "")).strip(),
            base_url=base_url,
            urls=urls,
            seen=seen,
        )

    return urls


def _extract_data_attr_urls(soup: BeautifulSoup, base_url: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    for tag in soup.find_all(True):
        for attr in _HTML_URL_ATTRS:
            value = tag.get(attr)

            if isinstance(value, str):
                _append_normalized_url(
                    value=value, base_url=base_url, urls=urls, seen=seen
                )

    return urls


def _extract_script_urls(soup: BeautifulSoup, base_url: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    for script in soup.find_all("script"):
        script_text = script.string or script.get_text(" ", strip=True)

        if not script_text:
            continue

        for match in re.finditer(r"https?://[^\s<>'\"\\]+", script_text):
            _append_normalized_url(
                value=match.group(0), base_url=base_url, urls=urls, seen=seen
            )

    return urls


def _extract_escaped_urls(html: str, base_url: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    for match in re.finditer(r"https?:\\/\\/[^\s<>'\"\\]+", html):
        _append_normalized_url(
            value=match.group(0).replace("\\/", "/"),
            base_url=base_url,
            urls=urls,
            seen=seen,
        )

    return urls


def _dedupe_urls(url_groups: list[list[str]]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    for group in url_groups:
        for url in group:
            if url not in seen:
                seen.add(url)
                urls.append(url)

    return urls


def extract_real_urls_from_html(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls = _dedupe_urls(
        [
            _extract_standard_html_urls(soup, base_url),
            _extract_data_attr_urls(soup, base_url),
            _extract_script_urls(soup, base_url),
            _extract_escaped_urls(html, base_url),
        ]
    )
    return urls[:DISCOVERY_MAX_LINKS_PER_PAGE]


async def robots_sitemaps(session: aiohttp.ClientSession, base_url: str) -> list[str]:
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    sitemaps: list[str] = []

    text = await fetch_text(session, robots_url)

    if text:
        for line in text.splitlines():
            line = line.strip()

            if line.lower().startswith("sitemap:"):
                sitemap = line.split(":", 1)[1].strip()

                if sitemap:
                    sitemaps.append(sitemap)

    for item in (
        "/sitemap.xml",
        "/sitemap_index.xml",
        "/sitemap-index.xml",
        "/sitemap.xml.gz",
    ):
        sitemaps.append(urljoin(base_url, item))

    return list(dict.fromkeys(sitemaps))


def extract_urls_from_xml(text: str) -> list[str]:
    try:
        root = ET.fromstring(text)  # nosec B314
    except ET.ParseError:
        return re.findall(r"https?://[^\s<>'\"]+", text)

    urls: list[str] = []

    for node in root.iter():
        tag = node.tag.split("}", 1)[-1].lower()

        if tag == "loc" and node.text:
            urls.append(unescape(node.text.strip()))

        if tag == "link":
            href = node.attrib.get("href")

            if href:
                urls.append(unescape(href.strip()))

    return urls


def _append_sitemap_candidate(
    *,
    base_url: str,
    clean: str,
    candidates: list[str],
    queue: list[str],
    seen_sitemaps: set[str],
) -> None:
    if not looks_like_official_host(base_url, clean):
        return

    if clean.endswith((".xml/", ".xml.gz/")):
        if len(seen_sitemaps) + len(queue) < 14:
            queue.append(clean)
        return

    candidates.append(clean)


async def _consume_sitemap_url(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    sitemap_url: str,
    candidates: list[str],
    queue: list[str],
    seen_sitemaps: set[str],
) -> None:
    clean_sitemap = strict_normalize_discovery_url(sitemap_url)

    if not clean_sitemap or clean_sitemap in seen_sitemaps:
        return

    seen_sitemaps.add(clean_sitemap)
    text = await fetch_text(session, clean_sitemap)

    if not text:
        return

    for raw_url in extract_urls_from_xml(text)[:1200]:
        clean = strict_normalize_discovery_url(raw_url)

        if clean:
            _append_sitemap_candidate(
                base_url=base_url,
                clean=clean,
                candidates=candidates,
                queue=queue,
                seen_sitemaps=seen_sitemaps,
            )


async def sitemap_candidates(
    session: aiohttp.ClientSession, base_url: str
) -> list[str]:
    candidates: list[str] = []
    seen_sitemaps: set[str] = set()
    queue = await robots_sitemaps(session, base_url)

    log(f"  [2/6] robots/sitemaps found={len(queue)}")

    while queue and len(seen_sitemaps) < 14:
        await _consume_sitemap_url(
            session,
            base_url=base_url,
            sitemap_url=queue.pop(0),
            candidates=candidates,
            queue=queue,
            seen_sitemaps=seen_sitemaps,
        )

    return list(dict.fromkeys(candidates))


def _host_is_under_root_domain(host: str, root: str) -> bool:
    host = _clean_public_host(host)
    root = _clean_public_host(root)
    return host == root or host.endswith("." + root)


def _candidate_root_url_from_host(host: str) -> str | None:
    host = _clean_public_host(host.replace("*.", ""))

    if not _host_is_valid_public_name(host):
        return None

    if regional_block_reason(f"https://{host}/"):
        return None

    return f"https://{host}/"


async def _fetch_certificate_transparency_payload(
    session: aiohttp.ClientSession,
    root: str,
) -> str | None:
    query_url = f"https://crt.sh/?q=%25.{root}&output=json"

    try:
        async with session.get(
            query_url,
            timeout=aiohttp.ClientTimeout(total=25),
            allow_redirects=True,
        ) as response:
            if response.status >= 400:
                return None

            return await response.text()
    except (aiohttp.ClientError, TimeoutError, OSError, UnicodeError):
        return None


def _certificate_rows(payload: str) -> list[dict[str, Any]]:
    try:
        rows = json.loads(payload)
    except (json.JSONDecodeError, TypeError, ValueError):
        return []

    if not isinstance(rows, list):
        return []

    return [row for row in rows if isinstance(row, dict)]


def _certificate_host_values(row: dict[str, Any]) -> list[str]:
    name_value = str(row.get("name_value", "") or "")
    common_name = str(row.get("common_name", "") or "")
    values = f"{name_value}\n{common_name}"
    return [value.lower().strip().strip(".") for value in values.splitlines()]


def _clean_certificate_host(raw_name: str) -> str:
    return raw_name.replace("*.", "").removeprefix("www.")


def _certificate_hosts_from_rows(
    rows: list[dict[str, Any]],
    *,
    root: str,
    max_hosts: int,
) -> list[str]:
    hosts: list[str] = []
    seen: set[str] = set()

    for row in rows:
        for raw_name in _certificate_host_values(row):
            host = _clean_certificate_host(raw_name)

            if _host_is_under_root_domain(host, root) and host not in seen:
                seen.add(host)
                hosts.append(host)

            if len(hosts) >= max_hosts:
                return hosts

    return hosts


def _certificate_candidates_from_hosts(base_url: str, hosts: list[str]) -> list[str]:
    candidates: list[str] = []

    for host in hosts:
        root_url = _candidate_root_url_from_host(host)
        clean = strict_normalize_discovery_url(root_url or "")

        if clean and looks_like_official_host(base_url, clean):
            candidates.append(clean)

    return list(dict.fromkeys(candidates))


async def certificate_transparency_subdomain_candidates(
    session: aiohttp.ClientSession,
    base_url: str,
    *,
    max_hosts: int = 2500,
) -> list[str]:
    root = root_domain(base_url)
    payload = await _fetch_certificate_transparency_payload(session, root)

    if payload is None:
        return []

    hosts = _certificate_hosts_from_rows(
        _certificate_rows(payload),
        root=root,
        max_hosts=max_hosts,
    )
    return _certificate_candidates_from_hosts(base_url, hosts)


async def _recursive_bfs_discovery_candidates(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    limit: int,
) -> tuple[list[str], list[DiscoveryResult]]:
    result = await run_recursive_bfs_discovery(
        session=session,
        base_url=base_url,
        limit=limit,
        discovery_result_type=DiscoveryResult,
        normalize_url=strict_normalize_discovery_url,
        final_txt_candidate=final_txt_candidate,
        sitemap_candidates=sitemap_candidates,
        certificate_transparency_subdomain_candidates=certificate_transparency_subdomain_candidates,
        fetch_text=fetch_text,
        extract_real_urls_from_html=extract_real_urls_from_html,
        discovery_db_key=_discovery_db_key,
        open_discovery_db=_open_discovery_db,
        mark_seen=_mark_seen,
        update_seen=_update_seen,
        log=log,
        max_default_pages=DISCOVERY_MAX_DEFAULT_PAGES,
        max_accepted_multiplier=DISCOVERY_MAX_ACCEPTED_MULTIPLIER,
        max_default_depth=DISCOVERY_MAX_DEFAULT_DEPTH,
    )

    return result.discovered, result.blocked


def _redirect_param_targets(raw_url: str) -> list[str]:
    parsed = urlparse(raw_url)
    targets: list[str] = []

    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        if key.lower().strip() in _REDIRECT_QUERY_KEYS:
            stripped = value.strip()

            if stripped.startswith(("http://", "https://")):
                targets.append(stripped)

    return list(dict.fromkeys(targets))


def _probe_candidates(raw_url: str) -> list[str]:
    return [raw_url] + _redirect_param_targets(raw_url)


def _response_is_html(response: aiohttp.ClientResponse) -> bool:
    content_type = response.headers.get("Content-Type", "").lower()
    return "text/html" in content_type or "application/xhtml+xml" in content_type


async def _probe_final_url(session: aiohttp.ClientSession, clean: str) -> str | None:
    try:
        async with session.get(
            clean,
            timeout=aiohttp.ClientTimeout(total=20),
            allow_redirects=True,
            headers={"Accept": "text/html,*/*;q=0.1"},
        ) as response:
            if response.status >= 400 or not _response_is_html(response):
                return None

            return str(response.url)
    except (aiohttp.ClientError, TimeoutError, OSError) as exc:
        log(f"       redirect probe skipped: {clean} reason={exc.__class__.__name__}")
        return None


async def _probe_final_working_root(
    session: aiohttp.ClientSession,
    *,
    seed_url: str,
    raw_url: str,
) -> str | None:
    for candidate in _probe_candidates(raw_url):
        clean = strict_normalize_discovery_url(candidate)

        if not clean:
            continue

        final_url = await _probe_final_url(session, clean)
        final_clean = strict_normalize_discovery_url(final_url or "")

        if not final_clean:
            continue

        promoted, reason = final_txt_candidate(seed_url, final_clean)

        if promoted and not reason:
            return promoted

    return None


async def _probe_redirect_final_roots(
    session: aiohttp.ClientSession,
    *,
    seed_url: str,
    raw_urls: list[str],
) -> list[str]:
    roots: list[str] = []
    seen: set[str] = set()

    for raw_url in raw_urls:
        root = await _probe_final_working_root(
            session, seed_url=seed_url, raw_url=raw_url
        )

        if root and root not in seen:
            seen.add(root)
            roots.append(root)

    return roots


def _discovery_headers() -> dict[str, str]:
    return {"User-Agent": "DocsMarkdownCrawler/1.0 clean discovery"}


def _to_discovery_result(item: Any, *, fallback_source: str) -> DiscoveryResult:
    return DiscoveryResult(
        url=str(item.url),
        source=str(getattr(item, "source", fallback_source)),
        score=int(item.score),
        reason=str(item.reason),
    )


def _classify_candidate(
    *,
    base_url: str,
    raw_url: str,
    accepted_map: dict[str, DiscoveryResult],
    blocked_map: dict[str, DiscoveryResult],
    review_map: dict[str, DiscoveryResult],
) -> None:
    final_url, block_reason = final_txt_candidate(base_url, raw_url)

    if block_reason or not final_url:
        blocked_map[raw_url] = DiscoveryResult(
            raw_url,
            "final_txt_candidate",
            0,
            block_reason or "blocked",
        )
        return

    bucket, item = score_url(final_url, seed=base_url)

    if bucket == "accepted":
        accepted_map[item.url] = _to_discovery_result(item, fallback_source="score_url")
    elif bucket == "review":
        review_map[item.url] = _to_discovery_result(item, fallback_source="score_url")
    elif not should_suppress_candidate_from_review(item.url, item.reason):
        blocked_map[item.url] = _to_discovery_result(item, fallback_source="score_url")


def _sorted_results(
    *,
    accepted_map: dict[str, DiscoveryResult],
    blocked_map: dict[str, DiscoveryResult],
    review_map: dict[str, DiscoveryResult],
    limit: int,
    include_review: bool,
) -> tuple[list[DiscoveryResult], list[DiscoveryResult], list[DiscoveryResult]]:
    accepted = sorted(accepted_map.values(), key=lambda item: (-item.score, item.url))[
        :limit
    ]
    review_limit = limit if include_review else 0
    review = sorted(
        (item for url, item in review_map.items() if url not in accepted_map),
        key=lambda item: (-item.score, item.url),
    )[:review_limit]
    blocked = sorted(blocked_map.values(), key=lambda item: (-item.score, item.url))
    return accepted, blocked, review


async def _discover_candidates(
    *,
    session: aiohttp.ClientSession,
    base_url: str,
    limit: int,
) -> tuple[list[str], list[DiscoveryResult]]:
    raw_candidates, raw_blocked = await _recursive_bfs_discovery_candidates(
        session=session,
        base_url=base_url,
        limit=limit,
    )
    redirect_final_roots = await _probe_redirect_final_roots(
        session=session,
        seed_url=base_url,
        raw_urls=list(raw_candidates) + [item.url for item in raw_blocked],
    )
    return list(dict.fromkeys(raw_candidates + redirect_final_roots)), raw_blocked


def _log_discover_start(base_url: str) -> None:
    log("")
    log(f"[DISCOVER START] {base_url}")
    log("  Mode: clean recursive BFS real-link discovery")
    log("  Rule: no fake URL generation; regional/English/trap gates before TXT")


def _log_discover_finish(
    accepted: list[DiscoveryResult],
    review: list[DiscoveryResult],
    blocked: list[DiscoveryResult],
) -> None:
    log("  [5/6] final TXT gate complete")
    log(f"       accepted={len(accepted)} review={len(review)} blocked={len(blocked)}")
    log("  [6/6] discovery finished")


async def discover(
    seed: str,
    limit: int = 40,
    include_review: bool = False,
) -> tuple[list[DiscoveryResult], list[DiscoveryResult], list[DiscoveryResult]]:
    started = time.time()
    base_url = normalize_site(seed)
    _log_discover_start(base_url)

    accepted_map: dict[str, DiscoveryResult] = {}
    blocked_map: dict[str, DiscoveryResult] = {}
    review_map: dict[str, DiscoveryResult] = {}

    async with aiohttp.ClientSession(headers=_discovery_headers()) as session:
        all_candidates, raw_blocked = await _discover_candidates(
            session=session,
            base_url=base_url,
            limit=limit,
        )

    for raw_url in all_candidates:
        _classify_candidate(
            base_url=base_url,
            raw_url=raw_url,
            accepted_map=accepted_map,
            blocked_map=blocked_map,
            review_map=review_map,
        )

    accepted, blocked, review = _sorted_results(
        accepted_map=accepted_map,
        blocked_map=blocked_map,
        review_map=review_map,
        limit=limit,
        include_review=include_review,
    )

    write_discovery_coverage_report(
        seed=base_url,
        accepted=accepted,
        review=review,
        blocked=blocked,
        raw_candidates=all_candidates,
        raw_blocked=raw_blocked,
        elapsed=time.time() - started,
    )
    _log_discover_finish(accepted, review, blocked)
    return accepted, blocked, review


__all__ = [
    "DiscoveryResult",
    "HIGH_VALUE_PATH_HINTS",
    "IMPORTANT_QUERY_KEYS",
    "LOW_VALUE_PATH_HINTS",
    "discover",
    "final_txt_candidate",
    "host_of",
    "is_bad_url",
    "is_blocked_machine_file",
    "is_english_url",
    "is_non_english_path",
    "is_non_english_query",
    "looks_like_official_host",
    "normalize_candidate_url",
    "path_parts",
    "root_domain",
    "same_scope",
    "score_url",
    "should_suppress_candidate_from_review",
    "strict_normalize_discovery_url",
    "_final_txt_candidate",
]
