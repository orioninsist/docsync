"""Pure pre-fetch URL policy evaluation for crawler orchestration.

The service normalizes candidate URLs and evaluates rejection rules before any
network request is attempted. It deliberately performs no persistence, queue,
dashboard, logging, or observability side effects.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from crawler.crawler_engine_url_rules import is_hard_blacklisted_url
from crawler.policy_engine import PolicyDecision
from crawler.shared.url_normalizer import normalize_optional_url, normalize_url


class UrlPolicyResultProtocol(Protocol):
    """Minimal result contract required from a URL policy implementation."""

    @property
    def allowed(self) -> bool:
        """Return whether the URL may proceed to network fetching."""

    @property
    def decision(self) -> PolicyDecision:
        """Return the structured policy decision."""

    @property
    def reason(self) -> str:
        """Return the machine-readable policy reason."""


class UrlPolicyProtocol(Protocol):
    """Minimal URL policy contract consumed by the service."""

    def evaluate_url(self, url: str) -> UrlPolicyResultProtocol:
        """Evaluate a normalized URL."""


@dataclass(frozen=True, slots=True)
class PreFetchDecision:
    """Immutable outcome of pre-fetch URL evaluation."""

    original_url: str
    normalized_url: str | None
    allowed: bool
    status: str | None
    reason: str
    policy_decision: PolicyDecision | None = None

    @property
    def should_skip(self) -> bool:
        """Return whether orchestration must stop before network fetching."""

        return not self.allowed

    @classmethod
    def allow(cls, *, original_url: str, normalized_url: str) -> PreFetchDecision:
        """Build an allowed pre-fetch decision."""

        return cls(
            original_url=original_url,
            normalized_url=normalized_url,
            allowed=True,
            status=None,
            reason="allowed",
        )

    @classmethod
    def reject(
        cls,
        *,
        original_url: str,
        normalized_url: str | None,
        status: str,
        reason: str,
        policy_decision: PolicyDecision | None = None,
    ) -> PreFetchDecision:
        """Build a rejected pre-fetch decision."""

        return cls(
            original_url=original_url,
            normalized_url=normalized_url,
            allowed=False,
            status=status,
            reason=reason,
            policy_decision=policy_decision,
        )


class PreFetchPolicyService:
    """Evaluate URL normalization and policy rules before network fetching."""

    def __init__(
        self,
        *,
        policy: UrlPolicyProtocol,
        require_english: bool,
        is_allowed_official_cross_host: Callable[[str], bool],
    ) -> None:
        self._policy = policy
        self._require_english = require_english
        self._is_allowed_official_cross_host = is_allowed_official_cross_host

    def evaluate(self, raw_url: str) -> PreFetchDecision:
        """Return a side-effect-free decision for a raw URL."""

        normalized_url = self._normalize_candidate_url(raw_url)

        if normalized_url is None:
            return PreFetchDecision.reject(
                original_url=raw_url,
                normalized_url=None,
                status="non_english_or_invalid_before_fetch",
                reason="non_english_or_invalid_url_before_fetch",
            )

        if is_hard_blacklisted_url(normalized_url):
            return PreFetchDecision.reject(
                original_url=raw_url,
                normalized_url=normalized_url,
                status="hard_blacklist",
                reason="hard_blacklist_before_fetch",
            )

        policy_result = self._policy.evaluate_url(normalized_url)

        if not policy_result.allowed and not self._is_allowed_official_cross_host(
            normalized_url
        ):
            return PreFetchDecision.reject(
                original_url=raw_url,
                normalized_url=normalized_url,
                status=f"policy_{policy_result.decision.value}",
                reason=policy_result.reason,
                policy_decision=policy_result.decision,
            )

        return PreFetchDecision.allow(
            original_url=raw_url,
            normalized_url=normalized_url,
        )

    def _normalize_candidate_url(self, raw_url: str) -> str | None:
        try:
            if self._require_english:
                return normalize_optional_url(raw_url)

            return normalize_url(raw_url)
        except ValueError:
            return None
