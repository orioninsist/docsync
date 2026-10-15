"""Isolated native Crawlee worker process."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from docsync.crawler import _run_crawler_native


async def main() -> None:
    result_path = Path(sys.argv[1])
    arguments = json.loads(sys.stdin.read())

    for name in ("output_dir", "state_dir"):
        if arguments[name] is not None:
            arguments[name] = Path(arguments[name])

    result = await _run_crawler_native(**arguments)

    result_path.write_text(
        json.dumps(result),
        encoding="utf-8",
    )


if __name__ == "__main__":
    asyncio.run(main())
