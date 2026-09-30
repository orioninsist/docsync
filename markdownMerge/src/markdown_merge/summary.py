from .splitter import Part
from .validator import ValidationResult


def create_summary(
    parts: list[Part],
    token_limit: int,
    input_files: int,
    *,
    reserve_tokens: int,
    tokenizer_name: str,
    validation: ValidationResult,
) -> str:
    lines: list[str] = []

    lines.append("Markdown Merge Summary")
    lines.append("=====================")
    lines.append("")
    lines.append(f"Input Files: {input_files}")
    lines.append(f"Created Parts: {len(parts)}")
    lines.append(f"Token Limit: {token_limit}")
    lines.append(f"Reserve Tokens: {reserve_tokens}")
    lines.append(f"Tokenizer: {tokenizer_name}")
    lines.append("")

    for index, part in enumerate(parts):
        lines.append(f"Part {part.number:03d}")
        lines.append("-" * 8)
        lines.append(f"Files: {len(part.files)}")
        if index < len(validation.parts):
            lines.append(f"Tokens: {validation.parts[index].tokens}")
        else:
            lines.append(f"Planned Tokens: {part.tokens}")
        lines.append("")

    return "\n".join(lines)
