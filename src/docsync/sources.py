"""Source adapters for documentation that is published from an official source tree."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path


class SourceAdapter(ABC):
    """Synchronize documentation without using the browser crawler."""

    @abstractmethod
    def sync(self, *, output_dir: Path, state_dir: Path) -> dict[str, int]:
        """Write Markdown documents and return DocsSync counters."""


def _run(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _load_manifest(path: Path) -> dict[str, dict[str, str]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _save_manifest(path: Path, manifest: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _jsdoc_to_markdown(source_path: str, source: str) -> str:
    """Render official JSDoc blocks without pretending to reproduce docs.phaser.io."""
    blocks = re.findall(r"/\*\*(.*?)\*/", source, flags=re.DOTALL)
    sections: list[str] = []

    for block in blocks:
        lines = []
        for raw in block.splitlines():
            line = re.sub(r"^\s*\* ?", "", raw).rstrip()
            if line.startswith(("@author", "@copyright", "@license", "@private")):
                continue
            if line.startswith("@classdesc"):
                line = line.removeprefix("@classdesc").strip()
            elif line.startswith("@"):
                match = re.match(r"@(\S+)\s*(.*)", line)
                if match:
                    tag, value = match.groups()
                    line = f"- **{tag}:** {value}".rstrip()
            lines.append(line)

        text = "\n".join(lines).strip()
        if text:
            sections.append(text)

    if not sections:
        return ""

    return (
        f"# {source_path}\n\n"
        "> Source: official Phaser repository JSDoc. "
        "This is source-derived documentation, not a mirror of docs.phaser.io.\n\n"
        + "\n\n---\n\n".join(sections)
        + "\n"
    )


class PhaserSourceAdapter(SourceAdapter):
    """Generate Markdown from the official phaserjs/phaser source JSDoc."""

    repository = "https://github.com/phaserjs/phaser.git"
    ref = "master"

    def _checkout(self, state_dir: Path) -> tuple[Path, str]:
        checkout = state_dir / "sources" / "phaser"
        if not (checkout / ".git").exists():
            checkout.parent.mkdir(parents=True, exist_ok=True)
            _run(
                "git",
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                self.repository,
                str(checkout),
            )
        else:
            _run("git", "remote", "set-url", "origin", self.repository, cwd=checkout)

        _run("git", "fetch", "--depth=1", "origin", self.ref, cwd=checkout)
        _run("git", "checkout", "--force", "FETCH_HEAD", cwd=checkout)
        commit = _run("git", "rev-parse", "HEAD", cwd=checkout)
        return checkout, commit

    def sync(self, *, output_dir: Path, state_dir: Path) -> dict[str, int]:
        output_dir.mkdir(parents=True, exist_ok=True)
        state_dir.mkdir(parents=True, exist_ok=True)
        checkout, commit = self._checkout(state_dir)

        manifest_file = state_dir / "source-phaser.json"
        previous = _load_manifest(manifest_file)
        manifest: dict[str, dict[str, str]] = {}
        counters = {"processed": 0, "saved": 0, "unchanged": 0}

        for source_file in sorted((checkout / "src").rglob("*.js")):
            relative = source_file.relative_to(checkout).as_posix()
            markdown = _jsdoc_to_markdown(
                relative, source_file.read_text(encoding="utf-8")
            )
            if not markdown:
                continue

            counters["processed"] += 1
            digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
            target = output_dir / relative.removeprefix("src/")
            target = target.with_suffix(".md")
            old = previous.get(relative, {})

            if old.get("content_hash") == digest and target.exists():
                counters["unchanged"] += 1
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(markdown, encoding="utf-8")
                counters["saved"] += 1

            manifest[relative] = {
                "content_hash": digest,
                "filename": target.relative_to(output_dir).as_posix(),
                "source_commit": commit,
            }

        _save_manifest(manifest_file, manifest)
        return counters


def get_source_adapter(name: str) -> SourceAdapter:
    if name == "phaser":
        return PhaserSourceAdapter()
    raise ValueError(f"unknown source adapter: {name}")
