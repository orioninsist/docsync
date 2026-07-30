"""Canonical URL and host scope policy for crawler queue processing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import ClassVar
from urllib.parse import ParseResult, parse_qs, urlparse

from crawler.shared.url_policy import (
    BLOCKED_EXTENSIONS,
    BLOCKED_SCHEMES,
    TRAP_PATH_PARTS,
    TRAP_QUERY_KEYS,
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
    """Own deterministic URL, host, path, and cross-host scope decisions."""

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

    start_url: str
    start_netloc: str
    start_host: str
    start_root_domain: str
    allowed_path_prefix: str

    def __init__(
        self,
        start_url: str,
        allowed_path_prefix: str = "/",
    ) -> None:
        """Initialize the canonical scope from the seed URL."""

        self.start_url = start_url

        parsed = urlparse(start_url)
        self.start_netloc = parsed.netloc.lower()
        self.start_host = self.normalize_host(parsed.netloc)
        self.start_root_domain = self.root_domain(self.start_host)
        self.allowed_path_prefix = self._normalize_path_prefix(allowed_path_prefix)

    def evaluate_url(self, url: str) -> PolicyResult:
        """Evaluate a normal same-scope crawler URL."""

        parsed = urlparse(url)
        base_result = self._base_url_guard_result(parsed)

        if base_result is not None:
            return base_result

        host_result = self._same_scope_host_guard_result(parsed.netloc)

        if host_result is not None:
            return host_result

        path_scope_result = self._path_scope_guard_result(parsed.path)

        if path_scope_result is not None:
            return path_scope_result

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

        del known_hosts

        parsed = urlparse(url)
        base_result = self._base_url_guard_result(parsed)

        if base_result is not None:
            return base_result

        if self.same_scope(url):
            path_scope_result = self._path_scope_guard_result(parsed.path)

            if path_scope_result is not None:
                return path_scope_result

            return PolicyResult(PolicyDecision.ALLOW, "url_allowed")

        if not allow_official_cross_host:
            return PolicyResult(
                PolicyDecision.BLOCK,
                "outside_start_domain",
            )

        return self._official_cross_host_result(
            parent_url=parent_url,
            depth=depth,
        )

    def evaluate_official_url(
        self,
        url: str,
        *,
        parent_url: str | None = None,
        depth: int = 0,
        known_hosts: set[str] | None = None,
    ) -> PolicyResult:
        """Evaluate a candidate URL outside the normal seed scope."""

        del known_hosts

        parsed = urlparse(url)
        base_result = self._base_url_guard_result(parsed)

        if base_result is not None:
            return base_result

        if self.same_scope(url):
            path_scope_result = self._path_scope_guard_result(parsed.path)

            if path_scope_result is not None:
                return path_scope_result

            return PolicyResult(PolicyDecision.ALLOW, "same_scope")

        return self._official_cross_host_result(
            parent_url=parent_url,
            depth=depth,
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

    @staticmethod
    def _normalize_path_prefix(path_prefix: str) -> str:
        """Return a canonical absolute path prefix."""

        normalized = f"/{path_prefix.strip().strip('/')}" if path_prefix else "/"

        return normalized.rstrip("/") or "/"

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

    def _path_scope_guard_result(
        self,
        path: str,
    ) -> PolicyResult | None:
        """Block paths outside the configured seed-path boundary."""

        if self.allowed_path_prefix == "/":
            return None

        normalized_path = self._normalize_path_prefix(path)

        if normalized_path == self.allowed_path_prefix or normalized_path.startswith(
            f"{self.allowed_path_prefix}/"
        ):
            return None

        return PolicyResult(
            PolicyDecision.BLOCK,
            "outside_allowed_path",
        )

    @staticmethod
    def _official_cross_host_result(
        *,
        parent_url: str | None,
        depth: int,
    ) -> PolicyResult:
        """Return the decision for an explicitly enabled cross-host URL."""

        if depth > 2:
            return PolicyResult(
                PolicyDecision.BLOCK,
                "cross_host_depth_limited",
            )

        if parent_url is None:
            return PolicyResult(
                PolicyDecision.BLOCK,
                "cross_host_parent_missing",
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
