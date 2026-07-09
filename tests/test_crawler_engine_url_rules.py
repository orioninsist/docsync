from crawler.crawler_engine_url_rules import is_hard_blacklisted_url


def test_is_hard_blacklisted_url_rejects_binary_and_archive_assets() -> None:
    blocked_urls = [
        "https://example.com/file.pdf",
        "https://example.com/archive.zip",
        "https://example.com/package.tar.gz",
        "https://example.com/image.png",
        "https://example.com/photo.jpeg",
        "https://example.com/script.js",
        "https://example.com/styles.css",
    ]

    for url in blocked_urls:
        assert is_hard_blacklisted_url(url)


def test_is_hard_blacklisted_url_does_not_reject_document_fragments() -> None:
    allowed_urls = [
        "https://example.com/docs#content",
        "https://example.com/docs#main",
        "https://example.com/docs#navigation",
        "https://example.com/docs#skip",
    ]

    for url in allowed_urls:
        assert not is_hard_blacklisted_url(url)


def test_is_hard_blacklisted_url_allows_regular_documentation_pages() -> None:
    allowed_urls = [
        "https://example.com/docs",
        "https://example.com/docs/getting-started",
        "https://example.com/api/reference",
        "https://example.com/guides/authentication?lang=python",
    ]

    for url in allowed_urls:
        assert not is_hard_blacklisted_url(url)


def test_is_hard_blacklisted_url_is_case_insensitive_for_extensions() -> None:
    assert is_hard_blacklisted_url("https://example.com/WHITEPAPER.PDF")
    assert is_hard_blacklisted_url("https://example.com/ASSET.PNG")
