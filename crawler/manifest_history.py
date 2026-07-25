"""Append-only Markdown history persistence for crawler manifests."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import final


@final
class ManifestHistory:
    """Append immutable crawler run records to a Markdown history file."""

    def __init__(self, history_path: Path) -> None:
        self._history_path: Path = history_path

    @property
    def history_path(self) -> Path:
        """Return the append-only history file path."""

        return self._history_path

    def append(
        self,
        *,
        run_id: str,
        event: str,
        fields: Mapping[str, object],
    ) -> None:
        """Append one complete Markdown record without rewriting prior records."""

        self._history_path.parent.mkdir(parents=True, exist_ok=True)

        payload = self._build_record(
            run_id=run_id,
            event=event,
            fields=fields,
        ).encode("utf-8")

        descriptor = os.open(
            self._history_path,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o644,
        )

        try:
            self._write_all(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _build_record(
        *,
        run_id: str,
        event: str,
        fields: Mapping[str, object],
    ) -> str:
        timestamp = datetime.now(UTC).isoformat()

        lines = [
            f"## {ManifestHistory._normalize_value(event)}",
            "",
            f"- Timestamp: `{timestamp}`",
            f"- Run ID: `{ManifestHistory._normalize_value(run_id)}`",
        ]

        lines.extend(
            (
                f"- {ManifestHistory._normalize_key(key)}: "
                f"{ManifestHistory._format_value(value)}"
            )
            for key, value in fields.items()
        )

        return "\n".join(lines).rstrip() + "\n\n"

    @staticmethod
    def _normalize_key(value: str) -> str:
        normalized = " ".join(value.split()).strip()

        if not normalized:
            raise ValueError("Manifest history field names must not be empty.")

        return normalized

    @staticmethod
    def _normalize_value(value: object) -> str:
        return " ".join(str(value).split()).strip()

    @staticmethod
    def _format_value(value: object) -> str:
        if value is None:
            return "`null`"

        if isinstance(value, bool):
            return f"`{str(value).lower()}`"

        if isinstance(value, (int, float)):
            return f"`{value}`"

        normalized = ManifestHistory._normalize_value(value)
        escaped = normalized.replace("`", "\\`")

        return f"`{escaped}`"

    @staticmethod
    def _write_all(descriptor: int, payload: bytes) -> None:
        remaining = memoryview(payload)

        while remaining:
            written = os.write(descriptor, remaining)

            if written <= 0:
                raise OSError("Unable to append the manifest history record.")

            remaining = remaining[written:]
