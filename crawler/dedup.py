"""URL and content deduplication engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import xxhash

from crawler.database import DatabaseManager
from crawler.shared.url_normalizer import normalize_url, url_sha256


DedupStatus = Literal[
    "same_url_unchanged",
    "same_url_changed",
    "same_final_url",
    "same_redirect_target",
    "same_canonical",
    "same_content",
    "new",
]


@dataclass(frozen=True)
class DedupResult:
    """Result returned by deduplication checks."""

    status: DedupStatus
    content_changed: bool


class DeduplicationEngine:
    def __init__(self, database: DatabaseManager) -> None:
        self.database = database

    def normalize_url(self, url: str) -> str | None:
        return normalize_url(url)

    def hash_url(self, url: str) -> str:
        return url_sha256(url)

    def url_hash(self, url: str) -> str:
        return self.hash_url(url)

    def final_url_hash(self, final_url: str) -> str:
        return self.hash_url(final_url)

    def redirect_target_hash(
        self,
        original_url: str,
        final_url: str,
    ) -> str | None:
        original_normalized = self.normalize_url(original_url)
        final_normalized = self.normalize_url(final_url)

        if original_normalized == final_normalized:
            return None

        return self.hash_url(final_url)

    def content_hash(self, content: str) -> str:
        normalized_content = " ".join(content.split())
        return xxhash.xxh64_hexdigest(normalized_content)

    def check(
        self,
        *,
        url_hash: str,
        content_hash: str,
        final_url_hash: str | None,
        redirect_target_hash: str | None,
        canonical_url: str | None,
    ) -> DedupResult:
        same_url = self.database.get_by_url_hash(url_hash)

        if same_url is not None:
            old_hash = same_url["content_hash"]

            if old_hash == content_hash:
                return DedupResult(
                    status="same_url_unchanged",
                    content_changed=False,
                )

            return DedupResult(
                status="same_url_changed",
                content_changed=True,
            )

        if final_url_hash:
            same_final_url = self.database.get_by_final_url_hash(
                final_url_hash
            )

            if same_final_url is not None:
                return DedupResult(
                    status="same_final_url",
                    content_changed=False,
                )

        if redirect_target_hash:
            same_redirect = self.database.get_by_redirect_target_hash(
                redirect_target_hash
            )

            if same_redirect is not None:
                return DedupResult(
                    status="same_redirect_target",
                    content_changed=False,
                )

        if canonical_url:
            normalized_canonical_url = self.normalize_url(canonical_url)

            if normalized_canonical_url is not None:
                same_canonical = self.database.get_by_canonical_url(
                    normalized_canonical_url
                )

                if same_canonical is not None:
                    return DedupResult(
                        status="same_canonical",
                        content_changed=False,
                    )

        same_content = self.database.get_by_content_hash(content_hash)

        if same_content is not None:
            return DedupResult(
                status="same_content",
                content_changed=False,
            )

        return DedupResult(
            status="new",
            content_changed=True,
        )
