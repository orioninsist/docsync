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
    """Split a source with one full tokenization and bounded final verification."""
    chunks: list[FileChunk] = []
    content_tokens = counter.encode(content)
    content_bytes = content.encode("utf-8")
    token_start = 0
    byte_start = 0
    chunk_number = 1

    while token_start < len(content_tokens):
        chunk_source_path = f"{source_path} [chunk {chunk_number}]"
        source_header = f"# Source: {chunk_source_path}\n\n"
        framing_tokens = counter.count(source_header + "\n\n")
        available_tokens = effective_limit - framing_tokens

        if available_tokens <= 0:
            raise ValueError(
                f"Effective token limit is too small to split source: "
                f"{source_path} ({effective_limit} tokens)."
            )

        token_end = min(token_start + available_tokens, len(content_tokens))
        piece_bytes = counter.decode_bytes(content_tokens[token_start:token_end])

        # A BPE token boundary may fall inside a UTF-8 code point. Extend only
        # until the accumulated token bytes form valid UTF-8 again.
        while token_end < len(content_tokens):
            try:
                piece_bytes.decode("utf-8")
                break
            except UnicodeDecodeError:
                piece_bytes += counter.decode_bytes([content_tokens[token_end]])
                token_end += 1

        candidate = piece_bytes.decode("utf-8")
        search_from = int(len(candidate) * 0.80)
        cut = len(candidate)

        for separator in ("\n## ", "\n# ", "\n\n", "\n"):
            boundary = candidate.rfind(separator, search_from)
            if boundary != -1:
                cut = boundary + 1
                break

        piece = candidate[:cut]
        piece_tokens = counter.count(source_header + piece + "\n\n")

        # Framing can merge with adjacent content tokens, so verify the final
        # serialized chunk. In the rare over-limit case, trim by natural text
        # boundaries without re-running a binary search over the whole source.
        while piece_tokens > effective_limit:
            reduced = max(1, int(len(piece) * 0.995))
            boundary = piece.rfind("\n", 0, reduced)
            cut = boundary + 1 if boundary != -1 else reduced
            piece = piece[:cut]
            piece_tokens = counter.count(source_header + piece + "\n\n")

        if not piece:
            raise ValueError(
                f"Unable to split source within token limit: {source_path}."
            )

        encoded_piece = piece.encode("utf-8")
        byte_end = byte_start + len(encoded_piece)
        if content_bytes[byte_start:byte_end] != encoded_piece:
            raise ValueError(f"Split integrity check failed for source: {source_path}.")

        consumed_tokens = len(counter.encode(piece))
        if consumed_tokens <= 0:
            raise ValueError(f"Unable to advance split for source: {source_path}.")

        chunks.append(
            FileChunk(
                path=file_path,
                source_path=chunk_source_path,
                tokens=piece_tokens,
                content=piece,
            )
        )

        token_start += consumed_tokens
        byte_start = byte_end
        chunk_number += 1

    if byte_start != len(content_bytes):
        raise ValueError(f"Split integrity check failed for source: {source_path}.")

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
