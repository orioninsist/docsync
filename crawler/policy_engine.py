"""URL and content policy decisions for the crawler smart queue."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from urllib.parse import ParseResult, parse_qs, urlparse

from crawler.shared.url_policy import (
    BLOCKED_EXTENSIONS,
    BLOCKED_SCHEMES,
    MEDIA_SOCIAL_HOSTS as SHARED_MEDIA_SOCIAL_HOSTS,
    TRAP_PATH_PARTS,
    TRAP_QUERY_KEYS,
)


class PolicyDecision(str, Enum):
    """Supported crawler policy decisions."""

    ALLOW = "allow"
    SKIP = "skip"
    REVIEW = "review"
    BLOCK = "block"


@dataclass(frozen=True)
class PolicyResult:
    """Structured policy evaluation result."""

    decision: PolicyDecision
    reason: str

    @property
    def allowed(self) -> bool:
        """Return whether the result allows processing."""
        return self.decision == PolicyDecision.ALLOW


class SmartScopePolicy:
    """Smart crawler scope policy for URL and content filtering."""

    GLOBAL_BLOCKED_SCHEMES = BLOCKED_SCHEMES

    GLOBAL_BLOCKED_EXTENSIONS = tuple(
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

    MEDIA_SOCIAL_HOSTS = SHARED_MEDIA_SOCIAL_HOSTS

    DOCS_POSITIVE_HINTS = {
        "docs",
        "doc",
        "documentation",
        "guide",
        "guides",
        "reference",
        "api",
        "manual",
        "kb",
        "help",
        "support",
        "article",
        "articles",
        "learn",
    }

    BLOG_POSITIVE_HINTS = {
        "blog",
        "post",
        "posts",
        "news",
        "article",
        "articles",
        "story",
        "stories",
    }

    WIKI_POSITIVE_HINTS = {
        "wiki",
        "manual",
        "docs",
        "documentation",
    }

    SUPPORT_NEGATIVE_HINTS = {
        "community",
        "forum",
        "forums",
        "thread",
        "threads",
        "question",
        "questions",
        "answer",
        "answers",
        "discussion",
        "discussions",
        "comment",
        "comments",
        "reply",
        "replies",
        "search",
        "signin",
        "login",
        "auth",
        "client",
        "logs",
        "youtubetv",
        "youtube-tv",
        "tv",
    }

    DOCS_NEGATIVE_HINTS = {
        "community",
        "forum",
        "forums",
        "thread",
        "threads",
        "question",
        "questions",
        "answer",
        "answers",
        "discussion",
        "discussions",
        "comment",
        "comments",
        "reply",
        "replies",
        "search",
        "signin",
        "login",
        "auth",
        "client",
        "logs",
        "cart",
        "checkout",
        "pricing",
        "plans",
        "contact",
        "sales",
        "demo",
    }

    BLOG_NEGATIVE_HINTS = {
        "login",
        "signin",
        "auth",
        "account",
        "client",
        "logs",
        "cart",
        "checkout",
        "search",
        "comment",
        "comments",
        "reply",
        "replies",
        "tag",
        "tags",
        "author",
        "category",
        "page",
    }

    LOW_VALUE_TEXT_PATTERNS = (
        "sign in",
        "log in",
        "create account",
        "search results",
        "no results found",
        "comments",
        "leave a comment",
        "post a reply",
        "verify you are human",
        "checking your browser",
        "access denied",
        "too many requests",
        "rate limited",
    )

    DOCS_TEXT_HINTS = (
        "how to",
        "learn how",
        "set up",
        "configure",
        "manage",
        "troubleshoot",
        "overview",
        "requirements",
        "steps",
        "before you begin",
        "use",
        "create",
        "delete",
        "edit",
    )

    BLOG_TEXT_HINTS = (
        "published",
        "author",
        "read more",
        "in this article",
        "blog",
        "post",
        "guide",
    )

    def __init__(
        self,
        start_url: str,
        allowed_path_prefix: str = "/",
    ) -> None:
        """Initialize policy from the crawler seed URL and allowed path scope."""
        self.start_url = start_url
        self.allowed_path_prefix = allowed_path_prefix or "/"

        parsed = urlparse(start_url)
        self.start_netloc = parsed.netloc.lower()
        self.start_path_parts = self._path_parts(parsed.path)
        self.mode = self._detect_mode(parsed)

    def evaluate_url(self, url: str) -> PolicyResult:
        """Evaluate whether a URL is inside crawler policy scope."""
        parsed = urlparse(url)
        path_lower = parsed.path.lower()
        path_parts = self._path_parts(path_lower)

        for result in self._url_guard_results(parsed, path_lower, path_parts):
            if result is not None:
                return result

        return self._evaluate_mode_path(path_parts)

    def evaluate_content(
        self,
        *,
        url: str,
        title: str,
        text: str,
    ) -> PolicyResult:
        """Evaluate fetched page content after URL-level policy passed."""
        url_result = self.evaluate_url(url)
        if not url_result.allowed:
            return url_result

        normalized_text = " ".join(text.split()).lower()
        normalized_title = " ".join(title.split()).lower()

        if len(normalized_text) < 120:
            return PolicyResult(PolicyDecision.SKIP, "content_too_short")

        low_value_reason = self._low_value_text_reason(normalized_text)
        if low_value_reason:
            return PolicyResult(PolicyDecision.SKIP, low_value_reason)

        haystack = f"{normalized_title} {normalized_text[:3000]}"

        if self.mode in {"docs", "support"}:
            positive_hits = sum(1 for hint in self.DOCS_TEXT_HINTS if hint in haystack)
            if positive_hits <= 0:
                return PolicyResult(PolicyDecision.REVIEW, "weak_docs_relevance")

        if self.mode == "blog":
            return PolicyResult(PolicyDecision.ALLOW, "blog_content_allowed")

        return PolicyResult(PolicyDecision.ALLOW, f"{self.mode}_content_allowed")

    def _url_guard_results(
        self,
        parsed: ParseResult,
        path_lower: str,
        path_parts: set[str],
    ) -> tuple[PolicyResult | None, ...]:
        """Return ordered URL-level guard results."""
        return (
            self._scheme_guard_result(parsed.scheme),
            self._host_guard_result(parsed.netloc),
            self._path_guard_result(path_lower),
            self._prefix_guard_result(path_lower),
            self._query_guard_result(parsed.query),
            self._global_path_guard_result(path_parts),
        )

    def _scheme_guard_result(self, scheme: str) -> PolicyResult | None:
        """Return block result when URL scheme is unsupported or blocked."""
        scheme_lower = scheme.lower()

        if scheme_lower not in {"http", "https"}:
            return PolicyResult(PolicyDecision.BLOCK, "unsupported_scheme")

        if scheme_lower in self.GLOBAL_BLOCKED_SCHEMES:
            return PolicyResult(PolicyDecision.BLOCK, "blocked_scheme")

        return None

    def _host_guard_result(self, netloc: str) -> PolicyResult | None:
        """Return block result when host is outside scope or social media."""
        if netloc.lower() != self.start_netloc:
            return PolicyResult(PolicyDecision.BLOCK, "outside_start_domain")

        social_reason = self._media_social_block_reason(netloc)
        if social_reason:
            return PolicyResult(PolicyDecision.BLOCK, social_reason)

        return None

    def _path_guard_result(self, path_lower: str) -> PolicyResult | None:
        """Return block result for machine files and blocked extensions."""
        if path_lower.endswith(self.GLOBAL_BLOCKED_EXTENSIONS):
            return PolicyResult(PolicyDecision.BLOCK, "blocked_file_extension")

        if path_lower.endswith("/robots.txt"):
            return PolicyResult(PolicyDecision.BLOCK, "blocked_machine_file")

        return None

    def _prefix_guard_result(self, path_lower: str) -> PolicyResult | None:
        """Return block result when path escapes the allowed prefix."""
        if not self._inside_allowed_prefix(path_lower):
            return PolicyResult(PolicyDecision.BLOCK, "outside_allowed_prefix")

        return None

    def _query_guard_result(self, query: str) -> PolicyResult | None:
        """Return block result when URL query parameters are unsafe."""
        blocked_query = self._blocked_query_reason(query)
        if blocked_query:
            return PolicyResult(PolicyDecision.BLOCK, blocked_query)

        return None

    def _global_path_guard_result(self, path_parts: set[str]) -> PolicyResult | None:
        """Return block result when path contains globally blocked tokens."""
        blocked = TRAP_PATH_PARTS.intersection(path_parts)
        if blocked:
            return PolicyResult(
                PolicyDecision.BLOCK,
                f"global_blocked_path:{sorted(blocked)[0]}",
            )

        return None

    def _evaluate_mode_path(self, path_parts: set[str]) -> PolicyResult:
        """Evaluate mode-specific URL path policy."""
        if self.mode == "support":
            return self._evaluate_support_path(path_parts)

        if self.mode == "docs":
            return self._evaluate_docs_path(path_parts)

        if self.mode == "blog":
            return self._evaluate_blog_path(path_parts)

        return PolicyResult(PolicyDecision.ALLOW, f"{self.mode}_url_allowed")

    def _evaluate_support_path(self, path_parts: set[str]) -> PolicyResult:
        """Evaluate support-mode path exclusions."""
        blocked = self.SUPPORT_NEGATIVE_HINTS.intersection(path_parts)
        if blocked:
            return PolicyResult(
                PolicyDecision.BLOCK,
                f"support_blocked_path:{sorted(blocked)[0]}",
            )

        return PolicyResult(PolicyDecision.ALLOW, "support_url_allowed")

    def _evaluate_docs_path(self, path_parts: set[str]) -> PolicyResult:
        """Evaluate docs-mode path exclusions."""
        blocked = self.DOCS_NEGATIVE_HINTS.intersection(path_parts)
        if blocked:
            return PolicyResult(
                PolicyDecision.BLOCK,
                f"docs_blocked_path:{sorted(blocked)[0]}",
            )

        return PolicyResult(PolicyDecision.ALLOW, "docs_url_allowed")

    def _evaluate_blog_path(self, path_parts: set[str]) -> PolicyResult:
        """Evaluate blog-mode path exclusions."""
        blocked = self.BLOG_NEGATIVE_HINTS.intersection(path_parts)
        if blocked:
            return PolicyResult(
                PolicyDecision.SKIP,
                f"blog_low_value_path:{sorted(blocked)[0]}",
            )

        return PolicyResult(PolicyDecision.ALLOW, "blog_url_allowed")

    def _detect_mode(self, parsed: ParseResult) -> str:
        """Detect crawler policy mode from seed URL host and path."""
        netloc = parsed.netloc.lower()
        parts = self._path_parts(parsed.path)

        if "blog" in parts:
            return "blog"

        if "wiki" in parts:
            return "wiki"

        if "support" in netloc or "help" in netloc:
            return "support"

        if self.DOCS_POSITIVE_HINTS.intersection(parts):
            return "docs"

        if self.BLOG_POSITIVE_HINTS.intersection(parts):
            return "blog"

        return "site"

    def _inside_allowed_prefix(self, path: str) -> bool:
        """Return whether a URL path stays under the allowed path prefix."""
        allowed = self.allowed_path_prefix.rstrip("/") or "/"

        if allowed == "/":
            return True

        normalized_path = f"/{path.strip('/')}".lower()
        allowed_lower = allowed.lower()

        return normalized_path == allowed_lower or normalized_path.startswith(
            f"{allowed_lower}/",
        )

    def _blocked_query_reason(self, query: str) -> str | None:
        """Return a query-block reason when URL query parameters are unsafe."""
        if not query:
            return None

        query_items = parse_qs(query, keep_blank_values=False)

        for key in query_items:
            key_lower = key.lower().strip()

            if not key_lower:
                continue

            if key_lower in TRAP_QUERY_KEYS:
                return f"blocked_query:{key_lower}"

        return None

    def _media_social_block_reason(self, netloc: str) -> str | None:
        """Return a block reason for media and social hosts."""
        host = netloc.lower().removeprefix("www.")

        if host.startswith("m."):
            host = host[2:]

        if host in self.MEDIA_SOCIAL_HOSTS:
            return f"blocked_media_social_host:{host}"

        for blocked_host in self.MEDIA_SOCIAL_HOSTS:
            if host.endswith(f".{blocked_host}"):
                return f"blocked_media_social_host:{blocked_host}"

        return None

    def _low_value_text_reason(self, normalized_text: str) -> str | None:
        """Return a low-value content reason when known noise appears early."""
        text_start = normalized_text[:1000]

        for pattern in self.LOW_VALUE_TEXT_PATTERNS:
            if pattern in text_start:
                return f"low_value_text:{pattern}"

        return None

    def _path_parts(self, path: str) -> set[str]:
        """Split a URL path into normalized policy tokens."""
        return {
            part.strip().lower().replace("_", "-")
            for part in path.strip("/").split("/")
            if part.strip()
        }
