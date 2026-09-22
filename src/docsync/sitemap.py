"""Crawlee-native sitemap request loading for DocsSync."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urljoin, urlsplit

from crawlee import RequestOptions, RequestTransformAction
from crawlee.http_clients import HttpClient
from crawlee.request_loaders import SitemapRequestLoader

from docsync.url_security import normalize_url, validated_http_url


def sitemap_seed_urls(start_url: str) -> list[str]:
    """Return conventional sitemap entry points for Crawlee's native loader."""

    validated_start = validated_http_url(start_url)
    parsed = urlsplit(validated_start)
    root_url = f"{parsed.scheme}://{parsed.netloc}/"

    return [
        normalize_url(urljoin(root_url, "sitemap.xml")),
        normalize_url(urljoin(root_url, "sitemap_index.xml")),
        normalize_url(urljoin(root_url, "sitemap.txt")),
        normalize_url(urljoin(root_url, "sitemap.xml.gz")),
    ]


def build_sitemap_request_loader(
    *,
    start_url: str,
    http_client: HttpClient,
    transform_request_function: (
        Callable[[RequestOptions], RequestOptions | RequestTransformAction] | None
    ) = None,
) -> SitemapRequestLoader:
    """Build the public Crawlee sitemap loader used by DocsSync."""

    return SitemapRequestLoader(
        sitemap_urls=sitemap_seed_urls(start_url),
        http_client=http_client,
        enqueue_strategy="same-hostname",
        persist_state_key="DOCSYNC_SITEMAP_REQUEST_LOADER_STATE",
        transform_request_function=transform_request_function,
    )
