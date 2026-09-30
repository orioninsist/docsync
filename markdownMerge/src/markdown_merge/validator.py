import re
from dataclasses import dataclass
from pathlib import Path

from .tokenizer import TokenCounter

SOURCE_MARKER_RE = re.compile(r"(?m)^# Source: .+$")


@dataclass(frozen=True)
class PartValidation:
    name: str
    tokens: int
    sources: int
    status: str


@dataclass(frozen=True)
class ValidationResult:
    report: str
    passed: bool
    parts: list[PartValidation]


def validate_output(
    part_paths: list[Path],
    token_limit: int,
    *,
    model: str | None = "gpt-4o",
    encoding_name: str | None = None,
) -> ValidationResult:
    counter = TokenCounter(
        model=model,
        encoding_name=encoding_name,
    )

    lines: list[str] = [
        "Markdown Merge Validation",
        "========================",
        "",
        f"Parts Found: {len(part_paths)}",
        "",
    ]

    failed = not part_paths
    validations: list[PartValidation] = []

    for part in part_paths:
        content = part.read_text(encoding="utf-8")
        tokens = counter.count(content)
        sources = len(SOURCE_MARKER_RE.findall(content))

        if tokens > token_limit:
            status = f"FAILED: token limit exceeded ({tokens} > {token_limit})"
            failed = True
        elif sources == 0:
            status = "FAILED: no source markers found"
            failed = True
        else:
            status = "OK"

        validations.append(
            PartValidation(
                name=part.name,
                tokens=tokens,
                sources=sources,
                status=status,
            )
        )

        lines.append(part.name)
        lines.append(f"  Tokens: {tokens}")
        lines.append(f"  Sources: {sources}")
        lines.append(f"  Status: {status}")
        lines.append("")

    passed = not failed
    lines.append(f"Validation Result: {'PASSED' if passed else 'FAILED'}")

    return ValidationResult(
        report="\n".join(lines),
        passed=passed,
        parts=validations,
    )
