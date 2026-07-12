"""Create deterministic, immutable merge plans without performing I/O."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

DEFAULT_MAX_SOURCES_PER_TARGET = 40
DEFAULT_TARGET_STEM = "merged-docs"
MARKDOWN_SUFFIX = ".md"
MAX_TITLE_SLUG_LENGTH = 40


class MergePlanningError(ValueError):
    """Base error raised when a deterministic merge plan cannot be created."""


class InvalidMergeSourceError(MergePlanningError):
    """Raised when a merge source violates the planner contract."""


class DuplicateSourceError(MergePlanningError):
    """Raised when two sources resolve to the same canonical source key."""


class DuplicateTargetError(MergePlanningError):
    """Raised when two planned groups resolve to the same target name."""


@dataclass(frozen=True, slots=True)
class MergeSource:
    """Describe one normalized document supplied to the merge planner."""

    relative_path: str
    title: str
    fingerprint: str
    size: int

    def __post_init__(self) -> None:
        """Validate immutable source metadata at the planner boundary."""
        normalized_path = _normalize_relative_path(self.relative_path)
        normalized_title = self.title.strip()
        normalized_fingerprint = self.fingerprint.strip()

        if not normalized_title:
            raise InvalidMergeSourceError("Source title must not be empty.")

        if not normalized_fingerprint:
            raise InvalidMergeSourceError("Source fingerprint must not be empty.")

        if self.size < 0:
            raise InvalidMergeSourceError("Source size must not be negative.")

        object.__setattr__(self, "relative_path", normalized_path)
        object.__setattr__(self, "title", normalized_title)
        object.__setattr__(self, "fingerprint", normalized_fingerprint)


@dataclass(frozen=True, slots=True)
class PlannedSource:
    """Store one source together with its deterministic position."""

    position: int
    source: MergeSource

    def __post_init__(self) -> None:
        """Ensure source positions remain one-based and valid."""
        if self.position < 1:
            raise MergePlanningError("Planned source position must be positive.")


@dataclass(frozen=True, slots=True)
class MergeTargetPlan:
    """Describe one target file and its ordered source membership."""

    position: int
    target_name: str
    sources: tuple[PlannedSource, ...]
    source_signature: tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate a single immutable target plan."""
        if self.position < 1:
            raise MergePlanningError("Target position must be positive.")

        if not self.target_name.endswith(MARKDOWN_SUFFIX):
            raise MergePlanningError("Target name must use the Markdown suffix.")

        if not self.sources:
            raise MergePlanningError("A merge target must contain at least one source.")

        expected_positions = tuple(range(1, len(self.sources) + 1))
        actual_positions = tuple(item.position for item in self.sources)

        if actual_positions != expected_positions:
            raise MergePlanningError(
                "Planned source positions must be consecutive and one-based."
            )

        expected_signature = tuple(
            _source_signature_item(item.source) for item in self.sources
        )

        if self.source_signature != expected_signature:
            raise MergePlanningError(
                "Target source signature does not match its ordered sources."
            )


@dataclass(frozen=True, slots=True)
class MergePlan:
    """Contain the complete deterministic plan for one project."""

    project_name: str
    targets: tuple[MergeTargetPlan, ...]
    source_count: int

    def __post_init__(self) -> None:
        """Validate complete-plan counts, positions, and target uniqueness."""
        normalized_project_name = self.project_name.strip()

        if not normalized_project_name:
            raise MergePlanningError("Project name must not be empty.")

        if self.source_count < 0:
            raise MergePlanningError("Source count must not be negative.")

        target_positions = tuple(target.position for target in self.targets)
        expected_positions = tuple(range(1, len(self.targets) + 1))

        if target_positions != expected_positions:
            raise MergePlanningError(
                "Merge target positions must be consecutive and one-based."
            )

        planned_source_count = sum(len(target.sources) for target in self.targets)

        if planned_source_count != self.source_count:
            raise MergePlanningError(
                "Merge plan source count does not match target membership."
            )

        target_keys = tuple(target.target_name.casefold() for target in self.targets)

        if len(target_keys) != len(set(target_keys)):
            raise DuplicateTargetError("Merge plan contains duplicate target names.")

        object.__setattr__(self, "project_name", normalized_project_name)


@dataclass(frozen=True, slots=True)
class MergePlanner:
    """Create deterministic merge plans from normalized source metadata."""

    max_sources_per_target: int = DEFAULT_MAX_SOURCES_PER_TARGET

    def __post_init__(self) -> None:
        """Validate planner configuration."""
        if self.max_sources_per_target < 1:
            raise MergePlanningError(
                "Maximum sources per target must be greater than zero."
            )

    def plan(
        self,
        project_name: str,
        sources: Sequence[MergeSource],
    ) -> MergePlan:
        """Return a deterministic plan without reading or writing any files."""
        normalized_project_name = project_name.strip()

        if not normalized_project_name:
            raise MergePlanningError("Project name must not be empty.")

        ordered_sources = _order_sources(sources)
        _reject_duplicate_sources(ordered_sources)

        groups = _partition_sources(
            ordered_sources,
            self.max_sources_per_target,
        )

        targets = _build_target_plans(
            project_name=normalized_project_name,
            groups=groups,
        )

        return MergePlan(
            project_name=normalized_project_name,
            targets=targets,
            source_count=len(ordered_sources),
        )


def create_merge_plan(
    project_name: str,
    sources: Sequence[MergeSource],
    *,
    max_sources_per_target: int = DEFAULT_MAX_SOURCES_PER_TARGET,
) -> MergePlan:
    """Create a merge plan through the default functional boundary."""
    planner = MergePlanner(max_sources_per_target=max_sources_per_target)
    return planner.plan(project_name=project_name, sources=sources)


def _normalize_relative_path(value: str) -> str:
    """Return a portable relative path suitable for deterministic comparison."""
    normalized = value.strip().replace("\\", "/")
    normalized = re.sub(r"/+", "/", normalized)
    normalized = normalized.removeprefix("./").strip("/")

    if not normalized:
        raise InvalidMergeSourceError("Source relative path must not be empty.")

    parts = normalized.split("/")

    if any(part in {"", ".", ".."} for part in parts):
        raise InvalidMergeSourceError(
            "Source relative path must not contain empty or traversal segments."
        )

    return "/".join(parts)


def _canonical_source_key(source: MergeSource) -> str:
    """Return the stable key used for ordering and duplicate detection."""
    return source.relative_path.casefold()


def _order_sources(sources: Sequence[MergeSource]) -> tuple[MergeSource, ...]:
    """Return sources ordered by path and stable metadata tie-breakers."""
    return tuple(
        sorted(
            sources,
            key=lambda source: (
                _canonical_source_key(source),
                source.relative_path,
                source.title.casefold(),
                source.fingerprint,
                source.size,
            ),
        )
    )


def _reject_duplicate_sources(sources: Sequence[MergeSource]) -> None:
    """Reject canonical path collisions before target planning begins."""
    seen_keys: set[str] = set()

    for source in sources:
        source_key = _canonical_source_key(source)

        if source_key in seen_keys:
            raise DuplicateSourceError(
                f"Duplicate source path detected: {source.relative_path}"
            )

        seen_keys.add(source_key)


def _partition_sources(
    sources: Sequence[MergeSource],
    group_size: int,
) -> tuple[tuple[MergeSource, ...], ...]:
    """Partition ordered sources into stable fixed-size groups."""
    return tuple(
        tuple(sources[index : index + group_size])
        for index in range(0, len(sources), group_size)
    )


def _build_target_plans(
    project_name: str,
    groups: Sequence[Sequence[MergeSource]],
) -> tuple[MergeTargetPlan, ...]:
    """Build immutable target plans and reject target-name collisions."""
    total_groups = len(groups)
    targets: list[MergeTargetPlan] = []
    target_keys: set[str] = set()

    for target_position, group in enumerate(groups, start=1):
        target_name = _build_target_name(
            project_name=project_name,
            target_position=target_position,
            total_groups=total_groups,
            first_source=group[0],
        )
        target_key = target_name.casefold()

        if target_key in target_keys:
            raise DuplicateTargetError(
                f"Duplicate merge target detected: {target_name}"
            )

        target_keys.add(target_key)
        planned_sources = _build_planned_sources(group)

        targets.append(
            MergeTargetPlan(
                position=target_position,
                target_name=target_name,
                sources=planned_sources,
                source_signature=tuple(
                    _source_signature_item(item.source) for item in planned_sources
                ),
            )
        )

    return tuple(targets)


def _build_planned_sources(
    sources: Sequence[MergeSource],
) -> tuple[PlannedSource, ...]:
    """Attach stable one-based positions to ordered source metadata."""
    return tuple(
        PlannedSource(position=position, source=source)
        for position, source in enumerate(sources, start=1)
    )


def _build_target_name(
    *,
    project_name: str,
    target_position: int,
    total_groups: int,
    first_source: MergeSource,
) -> str:
    """Return the deterministic Markdown target name for one source group."""
    project_slug = _safe_slug(project_name)

    if total_groups == 1:
        return f"{project_slug}__merged{MARKDOWN_SUFFIX}"

    title_slug = _safe_slug(first_source.title)[:MAX_TITLE_SLUG_LENGTH]

    return f"{project_slug}__part-{target_position:03d}__{title_slug}{MARKDOWN_SUFFIX}"


def _safe_slug(value: str) -> str:
    """Convert text into a stable ASCII slug without external dependencies."""
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_value = decomposed.encode("ascii", "ignore").decode("ascii")
    normalized = ascii_value.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized or DEFAULT_TARGET_STEM


def _source_signature_item(source: MergeSource) -> str:
    """Return stable source metadata consumed later by persistence boundaries."""
    return "\t".join(
        (
            source.relative_path,
            source.fingerprint,
            str(source.size),
        )
    )


__all__ = [
    "DEFAULT_MAX_SOURCES_PER_TARGET",
    "DuplicateSourceError",
    "DuplicateTargetError",
    "InvalidMergeSourceError",
    "MergePlan",
    "MergePlanner",
    "MergePlanningError",
    "MergeSource",
    "MergeTargetPlan",
    "PlannedSource",
    "create_merge_plan",
]
