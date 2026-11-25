from __future__ import annotations

import asyncio
import json
from collections import Counter


async def flushed_log(ctx) -> str | None:
    flushed = (await ctx.owner.post("/__slop/telemetry-flush", json={})).json().get("line")
    if flushed is None:
        return None
    want = json.dumps(flushed, separators=(",", ":"))
    for _ in range(50):
        text = (ctx.out / "relay.log").read_text(errors="replace")
        if want in text:
            return text
        await asyncio.sleep(0.1)
    raise TimeoutError("the flushed write_telemetry line never reached relay.log in 5 s")


def writers(text: str) -> Counter:
    out = Counter()
    for line in text.splitlines():
        i = line.find(" write_telemetry {")
        if i >= 0:
            for wn, wr in json.loads(line[i + len(" write_telemetry "):])["w"].items():
                out[wn] += wr["n"]
    return out
