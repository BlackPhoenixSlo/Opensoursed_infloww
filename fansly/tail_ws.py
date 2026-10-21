#!/usr/bin/env python3
"""Ad-hoc wsv3 tailer — the Fansly twin of `of_ws.py`'s __main__ tailer.

Prints every frame's serviceId/type and any TRANSLATED event, so a real inbound
DM can be watched end to end without the relay running:

    ./venv/bin/python fansly/tail_ws.py

Never prints the auth frame body — the token must not reach the log.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from fansly_client import FanslySession       # noqa: E402
from fansly_shim import FanslyShimClient      # noqa: E402
from fansly_ws import FanslyWebSocket         # noqa: E402


async def _tail() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    client = FanslyShimClient(FanslySession.load(HERE / "sessions" / "session.json"))
    ws = FanslyWebSocket(client)

    orig = ws._translate

    def tap(frame: dict):
        t = frame.get("t")
        if t == 1:
            s = (json.loads(frame.get("d") or "{}").get("session") or {})
            print(f"[auth] ok — websocketSessionId={s.get('websocketSessionId')}")
        elif t == 10000:
            env = json.loads(frame.get("d") or "{}")
            ev = json.loads(env.get("event") or "{}")
            print(f"[frame] serviceId={env.get('serviceId')} type={ev.get('type')}")
            # Raw non-auth envelope, for the two-account evidence run (prompt 06).
            # Never the t==1 auth frame — that carries the token.
            with open("/tmp/creator_ws_raw.jsonl", "a") as fh:
                fh.write(json.dumps({"serviceId": env.get("serviceId"), "event": ev}) + "\n")
        out = orig(frame)
        if out is not None:
            print("[event] " + json.dumps(out, indent=2)[:1200])
        return out

    ws._translate = tap
    print("[*] tailing Fansly wsv3 — Ctrl-C to stop")
    try:
        async for _ in ws.events():
            pass
    except KeyboardInterrupt:
        ws.stop()


if __name__ == "__main__":
    try:
        asyncio.run(_tail())
    except KeyboardInterrupt:
        pass
