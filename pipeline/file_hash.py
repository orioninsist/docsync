from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK_SIZE_BYTES = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(CHUNK_SIZE_BYTES), b""):
            digest.update(chunk)

    return digest.hexdigest()
