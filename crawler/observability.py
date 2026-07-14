from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from crawler.time_utils import utc_now


def host_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


@dataclass
class CrawlerObservability:
    logs_dir: Path
    start_url: str
    max_examples_per_bucket: int = 30

    allowed_hosts: Counter[str] = field(default_factory=Counter)
    rejected_hosts: Counter[str] = field(default_factory=Counter)
    rejected_reasons: Counter[str] = field(default_factory=Counter)
    blacklist_reasons: Counter[str] = field(default_factory=Counter)
    downloaded_hosts: Counter[str] = field(default_factory=Counter)
    skipped_hosts: Counter[str] = field(default_factory=Counter)
    duplicate_hosts: Counter[str] = field(default_factory=Counter)
    error_hosts: Counter[str] = field(default_factory=Counter)

    allowed_examples: dict[str, list[str]] = field(
        default_factory=lambda: defaultdict(list)
    )
    rejected_examples: dict[str, list[str]] = field(
        default_factory=lambda: defaultdict(list)
    )
    blacklist_examples: dict[str, list[str]] = field(
        default_factory=lambda: defaultdict(list)
    )
    status_examples: dict[str, list[str]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def record_official_allowed(
        self,
        *,
        url: str,
        reason: str,
    ) -> None:
        host = host_of(url)
        if not host:
            return

        self.allowed_hosts[host] += 1
        self._append_example(self.allowed_examples, reason, url)

    def record_official_rejected(
        self,
        *,
        url: str,
        reason: str,
    ) -> None:
        host = host_of(url) or "unknown"

        self.rejected_hosts[host] += 1
        self.rejected_reasons[reason] += 1
        self._append_example(self.rejected_examples, reason, url)

        if self._looks_like_blacklist_reason(reason):
            self.blacklist_reasons[reason] += 1
            self._append_example(self.blacklist_examples, reason, url)

    def record_url_status(
        self,
        *,
        url: str,
        status: str,
    ) -> None:
        host = host_of(url) or "unknown"

        if status in {"downloaded", "updated", "restored"}:
            self.downloaded_hosts[host] += 1
        elif status == "duplicate":
            self.duplicate_hosts[host] += 1
        elif status == "error":
            self.error_hosts[host] += 1
        else:
            self.skipped_hosts[host] += 1

        self._append_example(self.status_examples, status, url)

    def write_report(self) -> Path:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        path = self.logs_dir / "crawl_observability_report.md"

        lines: list[str] = []
        lines.append("# Crawl Observability Report")
        lines.append("")
        lines.append(f"Generated at: `{utc_now()}`")
        lines.append(f"Start URL: `{self.start_url}`")
        lines.append("")

        self._write_counter_section(
            lines,
            title="Allowed official hosts",
            counter=self.allowed_hosts,
        )
        self._write_counter_section(
            lines,
            title="Rejected hosts",
            counter=self.rejected_hosts,
        )
        self._write_counter_section(
            lines,
            title="Rejected reasons",
            counter=self.rejected_reasons,
        )
        self._write_counter_section(
            lines,
            title="Blacklist-style rejections",
            counter=self.blacklist_reasons,
        )
        self._write_counter_section(
            lines,
            title="Downloaded / updated hosts",
            counter=self.downloaded_hosts,
        )
        self._write_counter_section(
            lines,
            title="Skipped hosts",
            counter=self.skipped_hosts,
        )
        self._write_counter_section(
            lines,
            title="Duplicate hosts",
            counter=self.duplicate_hosts,
        )
        self._write_counter_section(
            lines,
            title="Error hosts",
            counter=self.error_hosts,
        )

        self._write_examples_section(
            lines,
            title="Allowed examples by reason",
            examples=self.allowed_examples,
        )
        self._write_examples_section(
            lines,
            title="Rejected examples by reason",
            examples=self.rejected_examples,
        )
        self._write_examples_section(
            lines,
            title="Blacklist examples by reason",
            examples=self.blacklist_examples,
        )
        self._write_examples_section(
            lines,
            title="Final status examples",
            examples=self.status_examples,
        )

        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

        json_path = self.logs_dir / "crawl_observability_report.json"
        json_path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        return path

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": utc_now(),
            "start_url": self.start_url,
            "allowed_hosts": dict(self.allowed_hosts),
            "rejected_hosts": dict(self.rejected_hosts),
            "rejected_reasons": dict(self.rejected_reasons),
            "blacklist_reasons": dict(self.blacklist_reasons),
            "downloaded_hosts": dict(self.downloaded_hosts),
            "skipped_hosts": dict(self.skipped_hosts),
            "duplicate_hosts": dict(self.duplicate_hosts),
            "error_hosts": dict(self.error_hosts),
            "allowed_examples": {
                key: list(value) for key, value in self.allowed_examples.items()
            },
            "rejected_examples": {
                key: list(value) for key, value in self.rejected_examples.items()
            },
            "blacklist_examples": {
                key: list(value) for key, value in self.blacklist_examples.items()
            },
            "status_examples": {
                key: list(value) for key, value in self.status_examples.items()
            },
        }

    def _write_counter_section(
        self,
        lines: list[str],
        *,
        title: str,
        counter: Counter[str],
    ) -> None:
        lines.append(f"## {title}")
        lines.append("")

        if not counter:
            lines.append("_None recorded._")
            lines.append("")
            return

        lines.append("| Item | Count |")
        lines.append("|---|---:|")
        for key, count in counter.most_common():
            lines.append(f"| `{key}` | {count} |")
        lines.append("")

    def _write_examples_section(
        self,
        lines: list[str],
        *,
        title: str,
        examples: dict[str, list[str]],
    ) -> None:
        lines.append(f"## {title}")
        lines.append("")

        if not examples:
            lines.append("_None recorded._")
            lines.append("")
            return

        for reason in sorted(examples):
            lines.append(f"### `{reason}`")
            lines.append("")
            for url in examples[reason][: self.max_examples_per_bucket]:
                lines.append(f"- `{url}`")
            lines.append("")

    def _append_example(
        self,
        target: dict[str, list[str]],
        key: str,
        url: str,
    ) -> None:
        bucket = target[key]

        if len(bucket) >= self.max_examples_per_bucket:
            return

        if url in bucket:
            return

        bucket.append(url)

    def _looks_like_blacklist_reason(self, reason: str) -> bool:
        lowered = reason.lower()
        blacklist_markers = (
            "blocked",
            "blacklist",
            "login",
            "signin",
            "auth",
            "forum",
            "community",
            "comment",
            "reply",
            "search",
            "cart",
            "checkout",
            "account",
            "profile",
            "client",
            "logs",
            "machine_file",
            "non_english",
        )
        return any(marker in lowered for marker in blacklist_markers)
