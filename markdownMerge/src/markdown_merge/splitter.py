from dataclasses import dataclass
from pathlib import Path

from .tokenizer import TokenCounter


@dataclass
class FileChunk:
    path: Path
    source_path: str
    tokens: int
    content: str | None = None


@dataclass
class Part:
    number: int
    files: list[FileChunk]
    tokens: int


def _source_path(file_path: Path, root: Path | None) -> str:
    resolved_path = file_path.resolve()
    if root is None:
        return file_path.name

    try:
        return resolved_path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"Input file is outside input directory: {file_path}") from exc


def _split_oversized_content(
    *,
    file_path: Path,
    source_path: str,
    content: str,
    counter: TokenCounter,
    effective_limit: int,
) -> list[FileChunk]:
    """Split a source file into chunks that fit within the token limit."""
    chunks: list[FileChunk] = []
    remaining = content
    chunk_number = 1

    while remaining:
        chunk_source_path = f"{source_path} [chunk {chunk_number}]"
        source_header = f"# Source: {chunk_source_path}\n\n"

        low = 1
        high = len(remaining)
        best = 0

        while low <= high:
            middle = (low + high) // 2
            candidate = remaining[:middle]
            candidate_tokens = counter.count(source_header + candidate + "\n\n")

            if candidate_tokens <= effective_limit:
                best = middle
                low = middle + 1
            else:
                high = middle - 1

        if best == 0:
            raise ValueError(
                f"Effective token limit is too small to split source: "
                f"{source_path} ({effective_limit} tokens)."
            )

        cut = best
        candidate = remaining[:best]
        search_from = int(best * 0.80)

        for separator in ("\n## ", "\n# ", "\n\n", "\n"):
            boundary = candidate.rfind(separator, search_from)
            if boundary != -1:
                cut = boundary + 1
                break

        piece = remaining[:cut]
        if not piece:
            piece = remaining[:best]
            cut = best

        piece_tokens = counter.count(source_header + piece + "\n\n")
        chunks.append(
            FileChunk(
                path=file_path,
                source_path=chunk_source_path,
                tokens=piece_tokens,
                content=piece,
            )
        )

        remaining = remaining[cut:]
        chunk_number += 1

    return chunks


def _measure_files(
    files: list[Path],
    *,
    root: Path | None,
    counter: TokenCounter,
    effective_limit: int,
) -> list[FileChunk]:
    chunks: list[FileChunk] = []
    total_files = len(files)

    for index, file_path in enumerate(files, start=1):
        print(f"[{index}/{total_files}] processing {file_path.name}")

        source_path = _source_path(file_path, root)
        content = file_path.read_text(encoding="utf-8")
        source_header = f"# Source: {source_path}\n\n"
        file_tokens = counter.count(source_header + content + "\n\n")

        if file_tokens > effective_limit:
            print(
                f"  oversized source: {file_tokens} tokens > "
                f"{effective_limit}; splitting automatically"
            )

            split_chunks = _split_oversized_content(
                file_path=file_path,
                source_path=source_path,
                content=content,
                counter=counter,
                effective_limit=effective_limit,
            )

            print(f"  created {len(split_chunks)} chunks")
            chunks.extend(split_chunks)
            continue

        chunks.append(
            FileChunk(
                path=file_path,
                source_path=source_path,
                tokens=file_tokens,
            )
        )

    return chunks


def _pack_first_fit_decreasing(
    chunks: list[FileChunk],
    *,
    effective_limit: int,
) -> list[Part]:
    oversized_chunks = [chunk for chunk in chunks if chunk.content is not None]
    normal_chunks = sorted(
        (chunk for chunk in chunks if chunk.content is None),
        key=lambda chunk: (-chunk.tokens, chunk.source_path),
    )

    # Oversized-source chunks are already emitted in source order. Pack them
    # first so output part numbering preserves that order. Normal sources are
    # then allowed to fill any remaining capacity in those parts.
    parts = [
        Part(number=index, files=[chunk], tokens=chunk.tokens)
        for index, chunk in enumerate(oversized_chunks, start=1)
    ]

    for chunk in normal_chunks:
        for part in parts:
            if part.tokens + chunk.tokens <= effective_limit:
                part.files.append(chunk)
                part.tokens += chunk.tokens
                break
        else:
            parts.append(
                Part(
                    number=len(parts) + 1,
                    files=[chunk],
                    tokens=chunk.tokens,
                )
            )

    for index, part in enumerate(parts, start=1):
        part.number = index

    return parts


def split_files(
    files: list[Path],
    token_limit: int,
    *,
    input_directory: str | None = None,
    reserve_tokens: int = 50_000,
    model: str | None = None,
    encoding_name: str | None = "o200k_base",
) -> list[Part]:
    if token_limit <= 0:
        raise ValueError("token_limit must be greater than zero.")
    if reserve_tokens < 0:
        raise ValueError("reserve_tokens cannot be negative.")
    if reserve_tokens >= token_limit:
        raise ValueError("reserve_tokens must be smaller than token_limit.")

    effective_limit = token_limit - reserve_tokens
    counter = TokenCounter(
        model=model,
        encoding_name=encoding_name,
    )
    root = Path(input_directory).resolve() if input_directory else None

    chunks = _measure_files(
        files,
        root=root,
        counter=counter,
        effective_limit=effective_limit,
    )
    return _pack_first_fit_decreasing(
        chunks,
        effective_limit=effective_limit,
    )
