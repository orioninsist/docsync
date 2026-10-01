import re
from dataclasses import dataclass
from pathlib import Path

from .tokenizer import TokenCounter

SOURCE_MARKER_RE = re.compile(r"(?m)^# Source: .+$")
CHATGPT_MAX_BYTES = 512_000_000


@dataclass(frozen=True)
class PartValidation:
    name: str
    tokens: int
    bytes: int
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
    max_bytes: int = CHATGPT_MAX_BYTES,
    model: str | None = None,
    encoding_name: str | None = "o200k_base",
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
        f"Max Bytes: {max_bytes}",
        "",
    ]

    failed = not part_paths
    validations: list[PartValidation] = []

    for part in part_paths:
        raw = part.read_bytes()
        content = raw.decode("utf-8")
        tokens = counter.count(content)
        byte_size = len(raw)
        sources = len(SOURCE_MARKER_RE.findall(content))

        if tokens > token_limit:
            status = f"FAILED: token limit exceeded ({tokens} > {token_limit})"
            failed = True
        elif byte_size > max_bytes:
            status = f"FAILED: byte limit exceeded ({byte_size} > {max_bytes})"
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
                bytes=byte_size,
                sources=sources,
                status=status,
            )
        )

        lines.append(part.name)
        lines.append(f"  Tokens: {tokens}")
        lines.append(f"  Bytes: {byte_size}")
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
