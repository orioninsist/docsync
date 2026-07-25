from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

from crawler.discovery_url_rules import (
    HIGH_VALUE_PATH_HINTS,
    is_bad_url,
    is_blocked_machine_file,
    is_non_english_query,
    looks_like_official_host,
    normalize_candidate_url,
    path_parts,
    root_domain,
    same_scope,
    score_url,
)
from crawler.time_utils import utc_now

GRAPH_DB_PATH = Path("state/global/official_host_graph.db")


@dataclass(frozen=True)
class HostDecision:
    allowed: bool
    host: str
    confidence: int
    reason: str


def host_of_url(url: str) -> str:
    return urlparse(normalize_candidate_url(url)).netloc.lower().removeprefix("www.")


class OfficialHostGraph:
    """
    Learns real official hosts from discovered URLs, but prevents broad
    ecosystem explosions.

    Important:
    - Never invent hosts.
    - Same-scope subdomains are allowed normally.
    - Cross-host official discovery is allowed only when the host/path is
      close enough to the seed intent.
    - Huge external documentation universes are blocked unless they are the
      original seed scope.
    """

    def __init__(
        self,
        *,
        seed_url: str,
        owner_project: str,
        db_path: Path = GRAPH_DB_PATH,
    ) -> None:
        self.seed_url: str = normalize_candidate_url(seed_url)
        self.owner_project: str = owner_project
        self.seed_host: str = host_of_url(seed_url)
        self.seed_root_domain: str = root_domain(seed_url)
        self.db_path: Path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.connection: sqlite3.Connection = sqlite3.connect(str(self.db_path))
        self._configure()
        self._create_schema()
        self.learn_host(
            url=seed_url,
            parent_url=None,
            confidence=100,
            reason="seed_host",
            depth=0,
        )

    def _configure(self) -> None:
        _ = self.connection.execute("PRAGMA journal_mode=WAL;")
        _ = self.connection.execute("PRAGMA synchronous=NORMAL;")
        _ = self.connection.execute("PRAGMA busy_timeout=30000;")

    def _create_schema(self) -> None:
        _ = self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS official_hosts (
                owner_project TEXT NOT NULL,
                seed_host TEXT NOT NULL,
                host TEXT NOT NULL,
                parent_host TEXT,
                confidence INTEGER NOT NULL,
                reason TEXT NOT NULL,
                depth INTEGER NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                PRIMARY KEY(owner_project, seed_host, host)
            );
            """
        )
        _ = self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_official_hosts_seed
            ON official_hosts(owner_project, seed_host);
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def known_hosts(self) -> set[str]:
        rows = cast(
            list[tuple[str]],
            self.connection.execute(
                """
                SELECT host
                FROM official_hosts
                WHERE owner_project = ?
                  AND seed_host = ?;
                """,
                (self.owner_project, self.seed_host),
            ).fetchall(),
        )

        return {host for (host,) in rows}

    def learn_host(
        self,
        *,
        url: str,
        parent_url: str | None,
        confidence: int,
        reason: str,
        depth: int,
    ) -> None:
        confidence = max(0, min(confidence, 100))
        depth = max(depth, 0)

        host = host_of_url(url)
        parent_host = host_of_url(parent_url) if parent_url else None
        now = utc_now()

        existing = cast(
            tuple[int, int] | None,
            self.connection.execute(
                """
                SELECT confidence, depth
                FROM official_hosts
                WHERE owner_project = ?
                  AND seed_host = ?
                  AND host = ?;
                """,
                (self.owner_project, self.seed_host, host),
            ).fetchone(),
        )

        if existing is None:
            _ = self.connection.execute(
                """
                INSERT INTO official_hosts (
                    owner_project,
                    seed_host,
                    host,
                    parent_host,
                    confidence,
                    reason,
                    depth,
                    first_seen_at,
                    last_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    self.owner_project,
                    self.seed_host,
                    host,
                    parent_host,
                    confidence,
                    reason,
                    depth,
                    now,
                    now,
                ),
            )
        else:
            existing_confidence, existing_depth = existing
            best_confidence = max(existing_confidence, confidence)
            best_depth = min(existing_depth, depth)

            _ = self.connection.execute(
                """
                UPDATE official_hosts
                SET
                    parent_host = COALESCE(parent_host, ?),
                    confidence = ?,
                    reason = CASE
                        WHEN ? > confidence THEN ?
                        ELSE reason
                    END,
                    depth = ?,
                    last_seen_at = ?
                WHERE owner_project = ?
                  AND seed_host = ?
                  AND host = ?;
                """,
                (
                    parent_host,
                    best_confidence,
                    confidence,
                    reason,
                    best_depth,
                    now,
                    self.owner_project,
                    self.seed_host,
                    host,
                ),
            )

        self.connection.commit()

    def evaluate_url(
        self,
        *,
        url: str,
        parent_url: str | None = None,
        depth: int = 0,
    ) -> HostDecision:
        clean = normalize_candidate_url(url)
        host = host_of_url(clean)

        if (
            is_bad_url(clean)
            or is_non_english_query(clean)
            or is_blocked_machine_file(clean)
        ):
            return HostDecision(False, host, 0, "bad_or_non_english_url")

        scope_block_reason = self._cross_host_scope_block_reason(
            url=clean,
            parent_url=parent_url,
            depth=depth,
        )

        if scope_block_reason:
            return HostDecision(False, host, 0, scope_block_reason)

        known = self.known_hosts()
        item = score_url(clean, seed=self.seed_url)[0]

        if host in known:
            confidence = max(75, item.score)
            return HostDecision(True, host, confidence, "known_official_host")

        if not looks_like_official_host(self.seed_url, clean):
            return HostDecision(False, host, 0, "not_official_like")

        parts = set(path_parts(clean))
        high_value_hits = parts.intersection(HIGH_VALUE_PATH_HINTS)

        confidence = item.score

        if high_value_hits:
            confidence += min(40, len(high_value_hits) * 8)

        if parent_url and host_of_url(parent_url) in known:
            confidence += 15

        if confidence < 55:
            return HostDecision(False, host, confidence, "weak_official_confidence")

        self.learn_host(
            url=clean,
            parent_url=parent_url,
            confidence=confidence,
            reason=item.reason,
            depth=depth,
        )

        return HostDecision(True, host, confidence, item.reason)

    def _cross_host_scope_block_reason(
        self,
        *,
        url: str,
        parent_url: str | None,
        depth: int,
    ) -> str | None:
        host = host_of_url(url)

        if host == self.seed_host:
            return None

        if same_scope(self.seed_url, url):
            return None

        if depth > 2:
            return "cross_host_depth_limited"

        if self._is_google_product_seed():
            return self._google_product_scope_block_reason(url=url)

        return self._generic_cross_host_scope_block_reason(
            url=url,
            parent_url=parent_url,
        )

    def _is_google_product_seed(self) -> bool:
        return False

    def _google_product_scope_block_reason(self, *, url: str) -> str | None:
        _ = url
        return None

    def _generic_cross_host_scope_block_reason(
        self,
        *,
        url: str,
        parent_url: str | None,
    ) -> str | None:
        host = host_of_url(url)
        parts = set(path_parts(url))
        seed_parts = set(path_parts(self.seed_url))

        if parent_url:
            parent_host = host_of_url(parent_url)

            if parent_host == self.seed_host or parent_host in self.known_hosts():
                parent_is_trusted = True
            else:
                parent_is_trusted = False
        else:
            parent_is_trusted = False

        if not parent_is_trusted and host not in self.known_hosts():
            return "cross_host_parent_not_trusted"

        if seed_parts:
            shared_path_intent = seed_parts.intersection(parts)
            high_value_hits = parts.intersection(HIGH_VALUE_PATH_HINTS)

            if not shared_path_intent and not high_value_hits:
                return "cross_host_weak_path_intent"

        return None
