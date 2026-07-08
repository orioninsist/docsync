"""Async-safe discovery root compatibility helpers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypeVar

import aiohttp

from crawler.discovery_redirect import probe_redirect_final_roots
from crawler.discovery_root_gate import promote_discovery_root

_Params = ParamSpec("_Params")
_ReturnT = TypeVar("_ReturnT")


def _make_async(
    func: Callable[_Params, _ReturnT],
) -> Callable[_Params, Awaitable[_ReturnT]]:
    """Wrap a synchronous callable as an awaitable callable."""

    @wraps(func)
    async def wrapper(*args: _Params.args, **kwargs: _Params.kwargs) -> _ReturnT:
        return func(*args, **kwargs)

    return wrapper


probe_final_working_root = _make_async(promote_discovery_root)

__all__ = [
    "probe_final_working_root",
    "probe_redirect_final_roots",
]


async def validate_root_candidates(
    session: aiohttp.ClientSession,
    *,
    seed_url: str,
    raw_urls: list[str],
) -> list[str]:
    """Resolve redirect-final root candidates without recursive discovery."""
    return await probe_redirect_final_roots(
        session,
        seed_url=seed_url,
        raw_urls=raw_urls,
    )
