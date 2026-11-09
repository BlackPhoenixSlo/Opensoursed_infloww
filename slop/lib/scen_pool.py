"""Bounded independent actor work shared by scenarios."""
from __future__ import annotations

import asyncio


async def pool(items, fn, n: int) -> None:
    it = iter(items)

    async def worker():
        for item in it:
            await fn(item)

    await asyncio.gather(*(worker() for _ in range(max(1, n))))
