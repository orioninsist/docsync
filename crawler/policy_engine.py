"""Canonical URL and host scope policy for crawler queue processing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import ClassVar
from urllib.parse import ParseResult, parse_qs, urlparse

from crawler.shared.url_policy import (
    BLOCKED_EXTENSIONS,
    BLOCKED_SCHEMES,
    MEDIA_SOCIAL_HOSTS as SHARED_MEDIA_SOCIAL_HOSTS,
    TRAP_PATH_PARTS,
    TRAP_QUERY_KEYS,
)

HIGH_VALUE_PATH_HINTS = frozenset(
    {
        "api",
        "developer",
        "developers",
        "doc",
        "docs",
        "documentation",
        "guide",
        "guides",
        "help",
        "learn",
        "reference",
        "support",
    }
)


class PolicyDecision(str, Enum):
    """Supported crawler policy decisions."""

    ALLOW = "allow"
    SKIP = "skip"
    REVIEW = "review"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class PolicyResult:
    """Structured policy evaluation result."""

    decision: PolicyDecision
    reason: str

    @property
    def allowed(self) -> bool:
        """Return whether the result allows processing."""

        return self.decision == PolicyDecision.ALLOW


class SmartScopePolicy:
    """Own every deterministic URL, host, path, and cross-host scope decision."""

    GLOBAL_BLOCKED_SCHEMES: ClassVar[set[str]] = BLOCKED_SCHEMES

    GLOBAL_BLOCKED_EXTENSIONS: ClassVar[tuple[str, ...]] = tuple(
        extension
        for extension in BLOCKED_EXTENSIONS
        if extension
        not in {
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".ppt",
            ".pptx",
        }
    )

    MEDIA_SOCIAL_HOSTS: ClassVar[frozenset[str]] = SHARED_MEDIA_SOCIAL_HOSTS

    start_url: str
    allowed_path_prefix: str
    start_netloc: str
    start_host: str
    start_root_domain: str

    def __init__(
        self,
        start_url: str,
        allowed_path_prefix: str = "/",
    ) -> None:
        """Initialize the canonical scope from the seed URL."""

        self.start_url = start_url
        self.allowed_path_prefix = allowed_path_prefix or "/"

        parsed = urlparse(start_url)
        self.start_netloc = parsed.netloc.lower()
        self.start_host = self.normalize_host(parsed.netloc)
        self.start_root_domain = self.root_domain(self.start_host)

    def evaluate_url(self, url: str) -> PolicyResult:
        """Evaluate a normal same-scope crawler URL."""

        parsed = urlparse(url)
        base_result = self._base_url_guard_result(parsed)

        if base_result is not None:
            return base_result

        host_result = self._same_scope_host_guard_result(parsed.netloc)

        if host_result is not None:
            return host_result

        prefix_result = self._prefix_guard_result(parsed.path.lower())

        if prefix_result is not None:
            return prefix_result

        return PolicyResult(PolicyDecision.ALLOW, "url_allowed")

    def evaluate_discovered_url(
        self,
        url: str,
        *,
        parent_url: str,
        depth: int,
        known_hosts: set[str] | None = None,
        allow_official_cross_host: bool,
    ) -> PolicyResult:
        """Evaluate one discovered URL through the canonical scope decision."""

        parsed = urlparse(url)
        base_result = self._base_url_guard_result(parsed)

        if base_result is not None:
            return base_result

        social_reason = self._media_social_block_reason(parsed.netloc)

        if social_reason:
            return PolicyResult(PolicyDecision.BLOCK, social_reason)

        if self.same_scope(url):
            prefix_result = self._prefix_guard_result(parsed.path.lower())

            if prefix_result is not None:
                return prefix_result

            return PolicyResult(PolicyDecision.ALLOW, "url_allowed")

        if not allow_official_cross_host:
            return PolicyResult(
                PolicyDecision.BLOCK,
                "outside_start_domain",
            )

        return self._official_cross_host_result(
            url=url,
            parent_url=parent_url,
            depth=depth,
            known_hosts=known_hosts,
        )

    def evaluate_official_url(
        self,
        url: str,
        *,
        parent_url: str | None = None,
        depth: int = 0,
        known_hosts: set[str] | None = None,
    ) -> PolicyResult:
        """Evaluate a candidate official URL outside the normal seed scope."""

        parsed = urlparse(url)
        base_result = self._base_url_guard_result(parsed)

        if base_result is not None:
            return base_result

        social_reason = self._media_social_block_reason(parsed.netloc)

        if social_reason:
            return PolicyResult(PolicyDecision.BLOCK, social_reason)

        if self.same_scope(url):
            return PolicyResult(PolicyDecision.ALLOW, "same_scope")

        return self._official_cross_host_result(
            url=url,
            parent_url=parent_url,
            depth=depth,
            known_hosts=known_hosts,
        )

    def same_scope(self, candidate_url: str) -> bool:
        """Return whether a URL belongs to the seed registrable domain."""

        candidate_host = self.normalize_host(urlparse(candidate_url).netloc)

        return bool(candidate_host) and (
            candidate_host == self.start_root_domain
            or candidate_host.endswith(f".{self.start_root_domain}")
        )

    def looks_like_official_host(self, candidate_url: str) -> bool:
        """Return whether a candidate host belongs to the seed root domain."""

        return self.same_scope(candidate_url)

    @staticmethod
    def normalize_host(host: str) -> str:
        """Return a normalized hostname without common presentation prefixes."""

        normalized = host.lower().strip().strip(".")

        if normalized.startswith("www."):
            normalized = normalized[4:]

        return normalized

    @staticmethod
    def root_domain(host: str) -> str:
        """Return the project's simple registrable-domain approximation."""

        normalized = SmartScopePolicy.normalize_host(host)
        labels = [label for label in normalized.split(".") if label]

        if len(labels) <= 2:
            return ".".join(labels)

        return ".".join(labels[-2:])

    @staticmethod
    def path_parts(url: str) -> set[str]:
        """Return normalized non-empty URL path tokens."""

        return {
            part.strip().lower().replace("_", "-")
            for part in urlparse(url).path.strip("/").split("/")
            if part.strip()
        }

    def _base_url_guard_result(
        self,
        parsed: ParseResult,
    ) -> PolicyResult | None:
        """Return the first deterministic non-scope URL rejection."""

        path_lower = parsed.path.lower()
        path_parts = self.path_parts(parsed.geturl())

        for result in (
            self._scheme_guard_result(parsed.scheme),
            self._path_guard_result(path_lower),
            self._query_guard_result(parsed.query),
            self._global_path_guard_result(path_parts),
        ):
            if result is not None:
                return result

        return None

    def _official_cross_host_result(
        self,
        *,
        url: str,
        parent_url: str | None,
        depth: int,
        known_hosts: set[str] | None,
    ) -> PolicyResult:
        """Return the canonical decision for an outside-scope official URL."""

        if depth > 2:
            return PolicyResult(
                PolicyDecision.BLOCK,
                "cross_host_depth_limited",
            )

        normalized_known_hosts = {
            self.normalize_host(host) for host in (known_hosts or set()) if host
        }
        candidate_host = self.normalize_host(urlparse(url).netloc)

        if candidate_host in normalized_known_hosts:
            return PolicyResult(
                PolicyDecision.ALLOW,
                "known_official_host",
            )

        if not self.looks_like_official_host(url):
            return PolicyResult(
                PolicyDecision.BLOCK,
                "not_official_like",
            )

        if not self._parent_is_trusted(
            parent_url=parent_url,
            known_hosts=normalized_known_hosts,
        ):
            return PolicyResult(
                PolicyDecision.BLOCK,
                "cross_host_parent_not_trusted",
            )

        if not self._shares_path_intent(url):
            return PolicyResult(
                PolicyDecision.BLOCK,
                "cross_host_weak_path_intent",
            )

        return PolicyResult(
            PolicyDecision.ALLOW,
            "official_cross_host_allowed",
        )

    def _same_scope_host_guard_result(
        self,
        netloc: str,
    ) -> PolicyResult | None:
        """Block hosts outside the canonical seed scope."""

        candidate_url = f"https://{netloc}/"

        if not self.same_scope(candidate_url):
            return PolicyResult(
                PolicyDecision.BLOCK,
                "outside_start_domain",
            )

        social_reason = self._media_social_block_reason(netloc)

        if social_reason:
            return PolicyResult(PolicyDecision.BLOCK, social_reason)

        return None

    def _scheme_guard_result(self, scheme: str) -> PolicyResult | None:
        """Block unsupported URL schemes."""

        scheme_lower = scheme.lower()

        if scheme_lower not in {"http", "https"}:
            return PolicyResult(
                PolicyDecision.BLOCK,
                "unsupported_scheme",
            )

        if scheme_lower in self.GLOBAL_BLOCKED_SCHEMES:
            return PolicyResult(
                PolicyDecision.BLOCK,
                "blocked_scheme",
            )

        return None

    def _path_guard_result(self, path_lower: str) -> PolicyResult | None:
        """Block machine files and binary resources."""

        if path_lower.endswith(self.GLOBAL_BLOCKED_EXTENSIONS):
            return PolicyResult(
                PolicyDecision.BLOCK,
                "blocked_file_extension",
            )

        if path_lower.endswith("/robots.txt"):
            return PolicyResult(
                PolicyDecision.BLOCK,
                "blocked_machine_file",
            )

        return None

    def _prefix_guard_result(self, path_lower: str) -> PolicyResult | None:
        """Block URLs outside the requested path prefix."""

        if not self._inside_allowed_prefix(path_lower):
            return PolicyResult(
                PolicyDecision.BLOCK,
                "outside_allowed_prefix",
            )

        return None

    def _query_guard_result(self, query: str) -> PolicyResult | None:
        """Block known crawler-trap query parameters."""

        blocked_query = self._blocked_query_reason(query)

        if blocked_query:
            return PolicyResult(
                PolicyDecision.BLOCK,
                blocked_query,
            )

        return None

    @staticmethod
    def _global_path_guard_result(
        path_parts: set[str],
    ) -> PolicyResult | None:
        """Block deterministic crawler-trap path tokens."""

        blocked = TRAP_PATH_PARTS.intersection(path_parts)

        if blocked:
            return PolicyResult(
                PolicyDecision.BLOCK,
                f"global_blocked_path:{sorted(blocked)[0]}",
            )

        return None

    def _inside_allowed_prefix(self, path: str) -> bool:
        """Return whether a URL remains under the configured path prefix."""

        allowed = self.allowed_path_prefix.rstrip("/") or "/"

        if allowed == "/":
            return True

        normalized_path = f"/{path.strip('/')}".lower()
        allowed_lower = allowed.lower()

        return normalized_path == allowed_lower or normalized_path.startswith(
            f"{allowed_lower}/",
        )

    @staticmethod
    def _blocked_query_reason(query: str) -> str | None:
        """Return the first deterministic blocked-query reason."""

        if not query:
            return None

        query_items = parse_qs(query, keep_blank_values=False)

        for key in query_items:
            key_lower = key.lower().strip()

            if key_lower in TRAP_QUERY_KEYS:
                return f"blocked_query:{key_lower}"

        return None

    def _media_social_block_reason(self, netloc: str) -> str | None:
        """Return a block reason for external media and social hosts."""

        host = self.normalize_host(netloc)

        if host.startswith("m."):
            host = host[2:]

        if host in self.MEDIA_SOCIAL_HOSTS:
            return f"blocked_media_social_host:{host}"

        for blocked_host in self.MEDIA_SOCIAL_HOSTS:
            if host.endswith(f".{blocked_host}"):
                return f"blocked_media_social_host:{blocked_host}"

        return None

    def _parent_is_trusted(
        self,
        *,
        parent_url: str | None,
        known_hosts: set[str],
    ) -> bool:
        """Return whether the discovery parent belongs to trusted scope."""

        if parent_url is None:
            return False

        parent_host = self.normalize_host(urlparse(parent_url).netloc)

        return self.same_scope(parent_url) or parent_host in known_hosts

    def _shares_path_intent(self, candidate_url: str) -> bool:
        """Return whether candidate paths preserve seed documentation intent."""

        seed_parts = self.path_parts(self.start_url)

        if not seed_parts:
            return True

        candidate_parts = self.path_parts(candidate_url)

        return bool(
            seed_parts.intersection(candidate_parts)
            or HIGH_VALUE_PATH_HINTS.intersection(candidate_parts)
        )
