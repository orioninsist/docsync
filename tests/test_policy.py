from __future__ import annotations

from pathlib import Path

import pytest

from docsync.policy import (
    default_output_dir,
    default_state_dir,
    hostname_for_url,
    normalize_language,
    output_path,
    site_dirname,
    url_is_within_start_scope,
)


def test_normalize_language_accepts_locale_values() -> None:
    assert normalize_language("EN") == "en"
    assert normalize_language("tr_TR") == "tr"
    assert normalize_language("pt-BR") == "pt"


@pytest.mark.parametrize("value", ["", "eng", "1n", "e"])
def test_normalize_language_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError, match="two-letter code"):
        normalize_language(value)


def test_hostname_requires_absolute_http_url() -> None:
    assert hostname_for_url("https://example.com/docs") == "example.com"
    with pytest.raises(ValueError, match=r"HTTP\(S\)"):
        hostname_for_url("file:///tmp/docs")


def test_default_directories_use_documentation_base_and_site_name() -> None:
    start_url = "https://example.com/docs"

    assert site_dirname(start_url) == "example.com-docs"
    assert default_output_dir(start_url) == Path(
        "/home/murat/Media/5-Documentation/example.com-docs"
    )
    assert default_state_dir(start_url) == Path(
        "/home/murat/Media/8-Document/docsync/example.com-docs"
    )


def test_site_dirname_uses_full_url_path() -> None:
    assert (
        site_dirname("https://github.com/niri-wm/niri/wiki")
        == "github.com-niri-wm-niri-wiki"
    )


def test_output_path_is_stable_and_url_specific() -> None:
    first = output_path(Path("docs"), "https://example.com/docs/api/reference")
    second = output_path(Path("docs"), "https://example.com/docs/api/reference")
    sibling = output_path(Path("docs"), "https://example.com/docs/api/reference?x=1")

    assert first == second
    assert first != sibling
    assert first.parent == Path("docs")
    assert first.name.startswith("docs-api-reference-")
    assert first.suffix == ".md"


def test_url_scope_accepts_root_and_descendants_only() -> None:
    root = "https://github.com/espanso/espanso/wiki"

    assert url_is_within_start_scope(
        root,
        "https://github.com/espanso/espanso/wiki",
    )
    assert url_is_within_start_scope(
        root,
        "https://github.com/espanso/espanso/wiki/Getting-Started",
    )
    assert url_is_within_start_scope(
        root,
        "https://github.com/espanso/espanso/wiki/Install/Linux?x=1#section",
    )


def test_url_scope_rejects_parent_sibling_domain_and_subdomain() -> None:
    root = "https://github.com/espanso/espanso/wiki"

    assert not url_is_within_start_scope(
        root,
        "https://github.com/espanso/espanso",
    )
    assert not url_is_within_start_scope(
        root,
        "https://github.com/espanso/espanso/issues",
    )
    assert not url_is_within_start_scope(
        root,
        "https://github.com/features",
    )
    assert not url_is_within_start_scope(
        root,
        "https://github.com/another/repository/wiki",
    )
    assert not url_is_within_start_scope(
        root,
        "https://gist.github.com/espanso/example",
    )
    assert not url_is_within_start_scope(
        root,
        "https://example.com/espanso/espanso/wiki",
    )


def test_url_scope_does_not_confuse_similar_prefixes() -> None:
    root = "https://example.com/docs"

    assert url_is_within_start_scope(root, "https://example.com/docs/api")
    assert not url_is_within_start_scope(root, "https://example.com/docs-old")
    assert not url_is_within_start_scope(root, "https://example.com/documentation")
