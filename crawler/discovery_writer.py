from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from crawler.discovery_result import DiscoveryResult
from crawler.queue_file import read_urls_from_txt as read_urls_from_txt
from crawler.queue_file import smart_group_key as smart_group_key
from crawler.queue_file import smart_sort_key as smart_sort_key
from crawler.queue_file import write_review_txt as write_review_txt


def host_of(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def path_depth(url: str) -> int:
    parsed = urlparse(url)

    return len([part for part in parsed.path.strip("/").split("/") if part])


def smart_group_title(host: str, group: str) -> str:
    return f"{host} / {group}"


def _build_report_path(seed: str) -> Path:
    report_dir = Path("state/global")
    report_dir.mkdir(parents=True, exist_ok=True)

    seed_key = host_of(seed).replace("/", "-").replace(":", "-") or "site"

    return report_dir / f"discovery_coverage_{seed_key}.md"


def _result_hosts(
    results: list[DiscoveryResult],
) -> set[str]:
    return {
        host_of(item.url)
        for item in results
        if item.url.startswith(("http://", "https://"))
    }


def _raw_hosts(raw_candidates: list[str]) -> set[str]:
    return {
        host_of(url)
        for url in raw_candidates
        if url.startswith(("http://", "https://"))
    }


def _count_block_reasons(
    blocked: list[DiscoveryResult],
    raw_blocked: list[DiscoveryResult],
) -> dict[str, int]:
    reason_counts: dict[str, int] = {}

    for item in [*blocked, *raw_blocked]:
        reason_counts[item.reason] = reason_counts.get(item.reason, 0) + 1

    return reason_counts


def _format_result(item: DiscoveryResult) -> str:
    return f"- `{item.url}` score={item.score} reason={item.reason}"


def _build_summary_section(
    *,
    seed: str,
    elapsed: float,
    raw_candidates: list[str],
    accepted: list[DiscoveryResult],
    review: list[DiscoveryResult],
    blocked: list[DiscoveryResult],
    raw_blocked: list[DiscoveryResult],
    accepted_hosts: set[str],
    review_hosts: set[str],
    blocked_hosts: set[str],
    observed_not_promoted: list[str],
) -> list[str]:
    return [
        "# Discovery Coverage Report",
        "",
        f"Seed: `{seed}`",
        f"Elapsed seconds: `{elapsed:.1f}`",
        "",
        "## Summary",
        "",
        f"- Raw candidates discovered: `{len(raw_candidates)}`",
        f"- Accepted roots: `{len(accepted)}`",
        f"- Review roots: `{len(review)}`",
        f"- Blocked candidates: `{len(blocked)}`",
        f"- Raw blocked candidates: `{len(raw_blocked)}`",
        f"- Accepted hosts: `{len(accepted_hosts)}`",
        f"- Review hosts: `{len(review_hosts)}`",
        f"- Blocked hosts: `{len(blocked_hosts)}`",
        f"- Observed hosts not promoted: `{len(observed_not_promoted)}`",
    ]


def _build_result_section(
    title: str,
    results: list[DiscoveryResult],
) -> list[str]:
    lines = [
        "",
        f"## {title}",
        "",
    ]
    lines.extend(_format_result(item) for item in results)

    return lines


def _build_reason_counts_section(
    reason_counts: dict[str, int],
) -> list[str]:
    lines = [
        "",
        "## Blocked reason counts",
        "",
    ]

    if not reason_counts:
        lines.append("_None_")

        return lines

    sorted_reasons = sorted(
        reason_counts.items(),
        key=lambda item: (-item[1], item[0]),
    )

    lines.extend(f"- `{reason}`: {count}" for reason, count in sorted_reasons)

    return lines


def _build_observed_hosts_section(
    observed_not_promoted: list[str],
) -> list[str]:
    lines = [
        "",
        "## Observed official-like hosts not promoted",
        "",
    ]

    if observed_not_promoted:
        lines.extend(f"- `{host}`" for host in observed_not_promoted[:300])
    else:
        lines.append("_None_")

    return lines


def _build_blocked_examples_section(
    blocked: list[DiscoveryResult],
) -> list[str]:
    return _build_result_section(
        "Blocked examples",
        blocked[:300],
    )


def _build_coverage_report_lines(
    *,
    seed: str,
    accepted: list[DiscoveryResult],
    review: list[DiscoveryResult],
    blocked: list[DiscoveryResult],
    raw_candidates: list[str],
    raw_blocked: list[DiscoveryResult],
    elapsed: float,
) -> list[str]:
    accepted_hosts = _result_hosts(accepted)
    review_hosts = _result_hosts(review)
    blocked_hosts = _result_hosts(blocked)

    promoted_hosts = accepted_hosts | review_hosts
    observed_not_promoted = sorted(_raw_hosts(raw_candidates) - promoted_hosts)
    reason_counts = _count_block_reasons(
        blocked,
        raw_blocked,
    )

    lines = _build_summary_section(
        seed=seed,
        elapsed=elapsed,
        raw_candidates=raw_candidates,
        accepted=accepted,
        review=review,
        blocked=blocked,
        raw_blocked=raw_blocked,
        accepted_hosts=accepted_hosts,
        review_hosts=review_hosts,
        blocked_hosts=blocked_hosts,
        observed_not_promoted=observed_not_promoted,
    )
    lines.extend(
        _build_result_section(
            "Accepted",
            accepted,
        )
    )
    lines.extend(
        _build_result_section(
            "Review",
            review,
        )
    )
    lines.extend(_build_reason_counts_section(reason_counts))
    lines.extend(_build_observed_hosts_section(observed_not_promoted))
    lines.extend(_build_blocked_examples_section(blocked))

    return lines


def write_discovery_coverage_report(
    *,
    seed: str,
    accepted: list[DiscoveryResult],
    review: list[DiscoveryResult],
    blocked: list[DiscoveryResult],
    raw_candidates: list[str],
    raw_blocked: list[DiscoveryResult],
    elapsed: float,
) -> None:
    report_path = _build_report_path(seed)
    lines = _build_coverage_report_lines(
        seed=seed,
        accepted=accepted,
        review=review,
        blocked=blocked,
        raw_candidates=raw_candidates,
        raw_blocked=raw_blocked,
        elapsed=elapsed,
    )

    _ = report_path.write_text(
        "\n".join(lines).rstrip() + "\n",
        encoding="utf-8",
    )
    print(
        f"       coverage report written: {report_path}",
        flush=True,
    )
