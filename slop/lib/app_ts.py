from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRIDGE = Path(__file__).with_name("app_ts.mjs")


async def _node(ctx, script: Path, **env):
    from slop.lib.faults import FAULTS
    f = FAULTS.get(getattr(ctx, "fault", None) or "")
    env = {"SLOP_TS_REWRITES": json.dumps([list(p) for p in (f.browser if f else ())]), **env}
    return await asyncio.create_subprocess_exec(
        "node", str(BRIDGE), str(ROOT / "app"), str(script), str(ctx.stack.tmp / "app-ts-vite"),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env={**os.environ, **env}, limit=2**26)


async def run(ctx, script: Path, payload) -> dict:
    proc = await _node(ctx, script)
    out, err = await proc.communicate(json.dumps(payload).encode())
    if proc.returncode != 0:
        raise RuntimeError(f"app_ts {Path(script).name}: node exited {proc.returncode}: {err.decode()[-2000:]}")
    body = json.loads(out)
    _count(ctx, body)
    return body["out"]


class Session:
    def __init__(self, ctx, script: Path, proc) -> None:
        self.ctx, self.script, self.proc = ctx, script, proc
        self._lock = asyncio.Lock()
        self._last: dict | None = None

    async def call(self, payload):
        async with self._lock:
            self.proc.stdin.write(json.dumps(payload).encode() + b"\n")
            await self.proc.stdin.drain()
            line = await self.proc.stdout.readline()
        if not line:
            err = (await self.proc.stderr.read()).decode()[-2000:]
            raise RuntimeError(f"app_ts session {Path(self.script).name}: node exited: {err}")
        body = json.loads(line)
        if "error" in body:
            raise RuntimeError(f"app_ts session {Path(self.script).name}: {body['error'][-2000:]}")
        self._last = body
        return body["out"]

    async def close(self) -> None:
        if self.proc.returncode is None:
            self.proc.stdin.close()
            await self.proc.wait()
        if self._last is not None:
            _count(self.ctx, self._last)
            self._last = None


async def session(ctx, script: Path) -> Session:
    return Session(ctx, script, await _node(ctx, script, SLOP_TS_LINES="1"))


def _count(ctx, body: dict) -> None:
    hits = ctx.browser_fault_hits
    for rx, n in body["hits"].items():
        hits[rx] = hits.get(rx, 0) + n
    files = ctx.app_ts_fault_files
    for p, n in body["files"].items():
        files[p] = files.get(p, 0) + n
