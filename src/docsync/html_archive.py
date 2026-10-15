"""Immutable source HTML archive for DocsSync."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path


def archive_html(
    html: str,
    *,
    state_dir: Path,
) -> tuple[Path, str]:
    """Store exact HTML bytes using content-addressed filenames.

    Existing archived content is never overwritten.
    """
    data = html.encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()

    directory = state_dir / "html" / "sha256" / digest[:2]
    target = directory / f"{digest}.html"

    directory.mkdir(parents=True, exist_ok=True)

    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"HTML archive integrity failure: {target}")
        return target, digest

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".docsync-",
        suffix=".tmp",
        dir=directory,
    )
    temporary = Path(temporary_name)

    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())

        try:
            os.link(temporary, target)
        except FileExistsError:
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise RuntimeError(
                    f"HTML archive integrity failure: {target}"
                ) from None
    finally:
        temporary.unlink(missing_ok=True)

    return target, digest
