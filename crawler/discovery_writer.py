from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from crawler.discovery_types import DiscoveryResult
from crawler.queue_file import read_urls_from_txt as read_urls_from_txt
from crawler.queue_file import smart_group_key as smart_group_key
from crawler.queue_file import smart_sort_key as smart_sort_key
from crawler.queue_file import write_seed_txt as write_seed_txt


def host_of(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def path_depth(url: str) -> int:
    parsed = urlparse(url)
    return len([part for part in parsed.path.strip("/").split("/") if part])


def smart_group_title(host: str, group: str) -> str:
    return f"{host} / {group}"


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
    report_dir = Path("state/global")
    report_dir.mkdir(parents=True, exist_ok=True)

    seed_key = host_of(seed).replace("/", "-").replace(":", "-") or "site"
    report_path = report_dir / f"discovery_coverage_{seed_key}.md"

    accepted_hosts = {host_of(item.url) for item in accepted}
    review_hosts = {host_of(item.url) for item in review}
    blocked_hosts = {
        host_of(item.url)
        for item in blocked
        if item.url.startswith(("http://", "https://"))
    }

    raw_hosts: set[str] = set()
    for url in raw_candidates:
        if url.startswith(("http://", "https://")):
            raw_hosts.add(host_of(url))

    promoted_hosts = accepted_hosts | review_hosts
    observed_not_promoted = sorted(raw_hosts - promoted_hosts)

    reason_counts: dict[str, int] = {}
    for item in list(blocked) + list(raw_blocked):
        reason_counts[item.reason] = reason_counts.get(item.reason, 0) + 1

    lines: list[str] = []
    lines.append("# Discovery Coverage Report")
    lines.append("")
    lines.append(f"Seed: `{seed}`")
    lines.append(f"Elapsed seconds: `{elapsed:.1f}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Raw candidates discovered: `{len(raw_candidates)}`")
    lines.append(f"- Accepted roots: `{len(accepted)}`")
    lines.append(f"- Review roots: `{len(review)}`")
    lines.append(f"- Blocked candidates: `{len(blocked)}`")
    lines.append(f"- Raw blocked candidates: `{len(raw_blocked)}`")
    lines.append(f"- Accepted hosts: `{len(accepted_hosts)}`")
    lines.append(f"- Review hosts: `{len(review_hosts)}`")
    lines.append(f"- Blocked hosts: `{len(blocked_hosts)}`")
    lines.append(f"- Observed hosts not promoted: `{len(observed_not_promoted)}`")
    lines.append("")
    lines.append("## Accepted")
    lines.append("")
    for item in accepted:
        lines.append(f"- `{item.url}` score={item.score} reason={item.reason}")
    lines.append("")
    lines.append("## Review")
    lines.append("")
    for item in review:
        lines.append(f"- `{item.url}` score={item.score} reason={item.reason}")
    lines.append("")
    lines.append("## Blocked reason counts")
    lines.append("")
    if reason_counts:
        for reason, count in sorted(reason_counts.items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"- `{reason}`: {count}")
    else:
        lines.append("_None_")
    lines.append("")
    lines.append("## Observed official-like hosts not promoted")
    lines.append("")
    if observed_not_promoted:
        for host in observed_not_promoted[:300]:
            lines.append(f"- `{host}`")
    else:
        lines.append("_None_")
    lines.append("")
    lines.append("## Blocked examples")
    lines.append("")
    for item in blocked[:300]:
        lines.append(f"- `{item.url}` score={item.score} reason={item.reason}")

    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"       coverage report written: {report_path}", flush=True)
